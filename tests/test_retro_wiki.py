import json

import pytest
import xp
from test_land import git
from test_retro import result
from test_retro_filing import state, two_proposals, wiki_commit, wiki_read, wiki_seed
from xpcore import gitx, retro

pytest_plugins = ["test_retro_filing"]


def sighting(monkeypatch, text):
    monkeypatch.setenv(
        "RETRO_RESULT",
        json.dumps(
            {
                "sightings": [{"lesson": "new:1", "text": text}],
                "proposals": [],
            }
        ),
    )


def test_shared_across_homes(publishing, monkeypatch, tmp_path):
    root, _, folder, _, home = publishing
    sighting(monkeypatch, "First observation")
    assert xp.main(["retro", "1"]) == 0
    assert (folder / "retro.md").is_file()
    second = tmp_path / "second"
    git(tmp_path, "clone", "-q", str(root.parent / "origin.git"), str(second))
    (second / ".xp/config.yml").open("a").write("\ngithub_issues: on\n")
    data = tmp_path / "second-data"
    (data / "sprints/1").mkdir(parents=True)
    (data / "sprints/1/release.json").write_text("{}")
    (data / "plan.md").write_text("## Sprint 1 — retro\n")
    second_home = tmp_path / "second-home"
    second_home.mkdir()
    monkeypatch.chdir(second)
    monkeypatch.setenv("HOME", str(second_home))
    monkeypatch.setenv("XP_DATA", str(data))
    sighting(monkeypatch, "Second observation")
    assert xp.main(["retro", "1"]) == 0
    text = wiki_read(publishing)
    assert "- L1 [sighting] First observation (seen: repo:1)" in text
    assert "- L2 [sighting] Second observation (seen: second:1)" in text
    assert "First observation" in (second_home / "retro-prompt").read_text()
    assert (data / "sprints/1/retro.md").is_file()
    for directory in (home, second_home):
        assert not (directory / ".xp/projects").exists()
    wiki = root.parent / "origin.wiki.git"
    assert git(wiki, "show", "HEAD:Home.md") == "Wiki home"
    assert git(wiki, "ls-tree", "--name-only", "HEAD").splitlines() == ["Home.md", "Lessons.md"]


@pytest.mark.parametrize("seat_fails", [False, True])
def test_refresh_closed_lines(publishing, monkeypatch, capsys, seat_fails):
    lines = [f"- L{i} [proposed] Lesson {i} (seen: prior:0) -> act; #{i}\n" for i in range(1, 8)]
    original = "# Lessons\n\n" + "".join(lines) + "Unchanged prose\n"
    wiki_seed(publishing, original)
    s = state(publishing)
    s["issues"] = [
        dict(number=i, state=st, stateReason=reason)
        for i, st, reason in (
            (1, "CLOSED", "COMPLETED"),
            (2, "CLOSED", "NOT_PLANNED"),
            (3, "OPEN", None),
            (4, "CLOSED", "OTHER"),
            (5, "BAD", None),
        )
    ]
    # The snapshot is independent of individual receipt lookups.
    s["pages"] = [{"data": {"repository": {"issues": {"nodes": []}}}}]
    publishing[3].write_text(json.dumps(s))
    monkeypatch.setenv("RETRO_EXIT", str(int(seat_fails)))
    assert xp.main(["retro", "1"]) == int(seat_fails)
    assert wiki_read(publishing) == original.replace(lines[0], "").replace(lines[1], "")
    prompt = (publishing[4] / "retro-prompt").read_text()
    assert lines[0] not in prompt and lines[1] not in prompt
    assert all(line in prompt for line in lines[2:])
    error = capsys.readouterr().err
    assert "L4 #4 lookup failed" in error and "L5 #5 lookup failed" in error


def reject_push(publishing, monkeypatch, at):
    original = gitx.git
    pushes = []

    def git_command(*args, **kwargs):
        if args[:1] == ("push",):
            pushes.append(args)
            if len(pushes) == at:
                peer = publishing[0].parent / "wiki-seed"
                git(peer, "pull", "-q", "--ff-only")
                (peer / "Home.md").write_text("Peer writer\n")
                wiki_commit(peer)
        return original(*args, **kwargs)

    monkeypatch.setattr(gitx, "git", git_command)


def test_rejected_sighting_push(publishing, monkeypatch, capsys):
    sighting(monkeypatch, "Rejected observation")
    reject_push(publishing, monkeypatch, 1)
    assert xp.main(["retro", "1"]) == 1
    assert "xp.py retro 1" in capsys.readouterr().err
    wiki = publishing[0].parent / "origin.wiki.git"
    assert git(wiki, "show", "HEAD:Home.md") == "Peer writer"
    assert "Lessons.md" not in git(wiki, "ls-tree", "--name-only", "HEAD")
    assert not state(publishing)["issues"]


@pytest.mark.parametrize("migration", [False, True])
def test_refusal_before_seat(publishing, monkeypatch, capsys, migration):
    root, _, folder, _, home = publishing
    wiki = root.parent / "origin.wiki.git"
    before = git(wiki, "rev-parse", "HEAD")
    (folder / "retro.md").write_text("Previous retro")
    local = retro.ledger_path()
    if migration:
        local.parent.mkdir(parents=True)
        local.write_text("Old local lesson\n")
    else:
        wiki.rename(wiki.with_name("unavailable.git"))
    assert xp.main(["retro", "1"]) == 1
    error = capsys.readouterr().err
    if migration:
        assert all(s in error for s in (str(local), "merge", "Lessons.md", "remove"))
        assert local.read_text() == "Old local lesson\n"
        assert git(wiki, "rev-parse", "HEAD") == before
    else:
        assert "https://example.test/owner/project/wiki" in error
        assert not local.parent.exists()
    assert not (home / "retro-prompt").exists()
    assert (folder / "retro.md").read_text() == "Previous retro"
    assert not state(publishing)["issues"]
    assert not [a for a, _ in state(publishing)["calls"] if a[:1] in (["issue"], ["label"])]


def test_receipt_push_repair(publishing, monkeypatch, capsys):
    two_proposals(monkeypatch)
    original = gitx.git
    creations = []

    def observe(*args, **kwargs):
        if args[:1] == ("push",):
            creations.append(len(state(publishing)["issues"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(gitx, "git", observe)
    reject_push(publishing, monkeypatch, 3)
    assert xp.main(["retro", "1"]) == 1
    error = capsys.readouterr().err
    assert "xp.py retro" not in error and "retry" not in error
    assert "wiki" in error and "Lessons.md" in error
    remote = wiki_read(publishing)
    for n, key in ((224, "L1"), (225, "L2")):
        assert f"https://example.test/issues/{n}" in error
        line = next(line for line in remote.splitlines() if line.startswith(f"- {key} "))
        repair = line if f"; #{n}" in line else line + f"; #{n}"
        assert repair in error
    assert "; #224" in remote and "; #225" not in remote
    assert creations == [0, 1, 2]
    assert len(state(publishing)["issues"]) == 2
    assert git(publishing[0].parent / "origin.wiki.git", "show", "HEAD:Home.md") == "Peer writer"


def closed_citation(publishing, monkeypatch, disposition="COMPLETED"):
    issue = dict(
        number=780,
        title="Keep evidence",
        state="CLOSED",
        stateReason=disposition,
        closedAt="2026-11-26",
        labels=[{"name": "lesson"}],
    )
    snapshot = state(publishing)
    snapshot["issues"] = [issue]
    publishing[3].write_text(json.dumps(snapshot))
    result(monkeypatch)
    import os

    answer = json.loads(os.environ["RETRO_RESULT"])
    answer["sightings"] = [{"lesson": "#780"}]
    answer["proposals"][0]["lessons"] = ["#780"]
    monkeypatch.setenv("RETRO_RESULT", json.dumps(answer))
    return snapshot, answer


@pytest.mark.parametrize("disposition", ["COMPLETED", "NOT_PLANNED"])
@pytest.mark.parametrize("existing", [False, True])
def test_closed_citation_and_rerun(publishing, monkeypatch, disposition, existing):
    snapshot, _ = closed_citation(publishing, monkeypatch, disposition)
    if existing:
        snapshot["issues"].append(
            dict(
                number=99,
                title="Replacement for #780: Keep evidence",
                state="OPEN",
                stateReason=None,
                closedAt=None,
                labels=[{"name": "lesson"}],
            )
        )
        publishing[3].write_text(json.dumps(snapshot))
        wiki_seed(
            publishing,
            "- L7 [proposed] Replacement for #780: Keep evidence "
            "(seen: other:0) -> proposal: Delete the step; cost: An hour; #99\n",
        )
    assert xp.main(["retro", "1"]) == 0
    first = wiki_read(publishing)
    assert first.count("Replacement for #780: Keep evidence") == 1
    assert "other:0, repo:1" in first if existing else "seen: repo:1" in first
    assert "Delete the step" in first and "An hour" in first
    issues = state(publishing)["issues"]
    assert issues[0] == snapshot["issues"][0]
    assert len(issues) == 2 and issues[1]["state"] == "OPEN"
    assert issues[1]["title"] == "Replacement for #780: Keep evidence"
    if not existing:
        assert issues[1]["body"].startswith("Replacement for #780: Keep evidence\n\n")
        assert "Delete the step" in issues[1]["body"] and "An hour" in issues[1]["body"]
    assert f"; #{issues[1]['number']}" in first
    assert xp.main(["retro", "1"]) == 0
    assert wiki_read(publishing) == first
    assert state(publishing)["issues"] == issues
    creates = [a for a, _ in state(publishing)["calls"] if a[:2] == ["issue", "create"]]
    assert len(creates) == int(not existing)


@pytest.mark.parametrize("invalid", ["open", "nonlesson", "absent"])
def test_invalid_citation_preserves_answer(publishing, monkeypatch, capsys, invalid):
    snapshot, answer = closed_citation(publishing, monkeypatch)
    if invalid == "open":
        snapshot["issues"][0]["state"] = "OPEN"
    elif invalid == "nonlesson":
        snapshot["issues"][0]["labels"] = [{"name": "bug"}]
    else:
        snapshot["pages"] = [{"data": {"repository": {"issues": {"nodes": []}}}}]
    publishing[3].write_text(json.dumps(snapshot))
    answer["sightings"].insert(0, {"lesson": "new:1", "text": "Valid observation"})
    monkeypatch.setenv("RETRO_RESULT", json.dumps(answer))
    original = "- L1 [sighting] Stable (seen: prior:0) -> not proposed\n"
    wiki_seed(publishing, original)
    previous = publishing[2] / "retro.md"
    previous.write_text("Previous retro")
    assert xp.main(["retro", "1"]) == 1
    assert "#780" in capsys.readouterr().err
    assert wiki_read(publishing) == original and previous.read_text() == "Previous retro"
    assert state(publishing)["issues"] == snapshot["issues"]
    assert not [
        a
        for a, _ in state(publishing)["calls"]
        if a[:2] in (["issue", "create"], ["issue", "close"])
    ]
