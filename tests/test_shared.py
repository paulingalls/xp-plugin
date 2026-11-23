import hashlib
import json
import shutil
import socket
import subprocess

import pytest
import xp
from test_records import refused, repo, state  # noqa: F401
from xpcore import cards

CARD = """#### free-share — shared work   [planned]
Context: private local detail
Measure: distance=1
AC:
- first
  continuation

- second
Files: a.py
Acceptance: true
Evidence: git cat-file -e origin/main:read.md
Executor: codex
"""


def plan(text=CARD):
    cards.plan_path().parent.mkdir(exist_ok=True)
    cards.plan_path().write_text("## Free\n\n" + text + "\n## Later\nuntouched\n")


def save(fixture, value):
    (fixture / "issues.json").write_text(json.dumps(value))


def test_publish_and_edit(repo):  # noqa: F811
    plan()
    before = cards.plan_path().read_text()
    assert xp.main(["card", "publish", "free-share"]) == 0
    issue = state(repo)["issues"][0]
    assert issue["labels"] == [{"name": "card"}]
    owner = issue["body"].split("Published by: ")[1].strip()
    assert (
        issue["body"]
        == CARD.replace("Context: private local detail", f"Context: local to {owner}")
        + f"Published by: {owner}\n"
    )
    assert cards.plan_path().read_text().replace("Issue: #224\n", "") == before
    cards.plan_path().write_text(cards.plan_path().read_text().replace("a.py", "b.py"))
    assert xp.main(["card", "publish", "free-share"]) == 0
    s = state(repo)
    assert len(s["issues"]) == 1 and "Files: b.py" in s["issues"][0]["body"]
    assert len([c for c in s["calls"] if c[0][:2] == ["issue", "create"]]) == 1
    assert cards.plan_path().read_text().count("Issue: #224") == 1
    assert "Context: private local detail" in cards.plan_path().read_text()


@pytest.mark.parametrize("identifier", ["free-share", "story-001"])
@pytest.mark.parametrize("section_exists", [None, False, True])
def test_claim_across_clones(repo, monkeypatch, capsys, identifier, section_exists):  # noqa: F811
    monkeypatch.setattr(socket, "gethostname", lambda: "fixed-host")
    plan(CARD.replace("free-share", identifier))
    assert xp.main(["card", "publish", identifier]) == 0
    subprocess.run(["git", "clone", "-q", str(repo / "r"), str(repo / "second")], check=True)
    monkeypatch.chdir(repo / "second")
    monkeypatch.setenv("XP_DATA", str(repo / "second-data"))
    section = "Free" if identifier.startswith("free-") else "Claimed"
    cards.plan_path().parent.mkdir()
    prefix = f"## {section}\n\n" if section_exists else ""
    if section_exists is not None:
        cards.plan_path().write_text(prefix + "## Later\nuntouched\n")
    assert xp.main(["card", "claim", "224"]) == 0
    local = cards.plan_path().read_text()
    assert f"## {section}\n\n#### {identifier}" in local
    if section_exists is not None:
        assert "## Later\nuntouched\n" in local
    assert cards.find_card(identifier).field("Issue") == "#224"
    assert "AC:\n- first\n  continuation\n\n- second" in local
    label = next(
        x["name"] for x in state(repo)["issues"][0]["labels"] if x["name"].startswith("clone:")
    )
    assert label == "clone:second@" + hashlib.sha256(b"fixed-host").hexdigest()[:6]
    assert "fixed-host" not in str(state(repo)["calls"])
    cards.plan_path().write_text(local.replace("Files: a.py", "Files: unsent.py"))
    before = cards.plan_path().read_text()
    assert xp.main(["card", "claim", "224"]) == 0
    assert cards.plan_path().read_text() == before
    s = state(repo)
    assert s["issues"][0]["labels"].count({"name": label}) == 1
    s["issues"][0]["labels"].append({"name": "clone:other@123456"})
    save(repo, s)
    assert "other@123456" in refused(capsys, ["card", "claim", "224"])
    assert cards.plan_path().read_text() == before
    assert not any(c[0][:2] == ["issue", "edit"] for c in state(repo)["calls"][len(s["calls"]) :])
    monkeypatch.chdir(repo / "r")
    assert label[6:] in refused(capsys, ["card", "claim", "224"])


@pytest.mark.parametrize("body,labels", [("not a card", ["card"]), (CARD, ["bug"])])
def test_claim_requires_card_issue(repo, capsys, body, labels):  # noqa: F811
    plan()
    s = state(repo)
    s["issues"] = [{"number": 224, "body": body, "labels": [{"name": n} for n in labels]}]
    save(repo, s)
    before = cards.plan_path().read_text()
    assert "card" in refused(capsys, ["card", "claim", "224"])
    assert cards.plan_path().read_text() == before
    assert all(c[0][:2] != ["issue", "edit"] for c in state(repo)["calls"])


@pytest.mark.parametrize("missing", [False, True])
def test_publication_requires_scanning_on_create_and_edit(repo, monkeypatch, capsys, missing):  # noqa: F811
    plan()
    if not missing:
        assert xp.main(["card", "publish", "free-share"]) == 0
        (repo / "r" / ".gitleaks.toml").write_text(
            '[[rules]]\nid = "card-canary"\ndescription = "card canary"\n'
            'regex = "xp_canary_[a-f0-9]{32}"\n'
        )
        cards.plan_path().write_text(
            cards.plan_path()
            .read_text()
            .replace("a.py", "xp_canary_" + "0123456789abcdef0123456789abcdef")
        )
    else:
        isolated = repo / "isolated"
        isolated.mkdir()
        for name in ("gh", "git"):
            (isolated / name).symlink_to(shutil.which(name))
        monkeypatch.setenv("PATH", str(isolated))
    before, s = cards.plan_path().read_text(), state(repo)
    assert "gitleaks" in refused(capsys, ["card", "publish", "free-share"])
    assert state(repo) == s and cards.plan_path().read_text() == before
    if not missing:
        cards.plan_path().write_text(before.replace("Issue: #224\n", ""))
        assert "gitleaks" in refused(capsys, ["card", "publish", "free-share"])
        assert state(repo) == s


@pytest.mark.parametrize("setting", ["", "github_issues: off\n", None])
def test_issue_features_opt_in(repo, monkeypatch, capsys, setting):  # noqa: F811
    plan()
    config = repo / "r/.xp/config.yml"
    if setting is None:
        config.unlink()
    else:
        config.write_text(setting)
    before = cards.plan_path().read_text()
    for command in [
        ["card", "publish", "free-share"],
        ["card", "claim", "224"],
        ["resolve", "--ref", "224", "--falsifier", "touch forbidden"],
    ]:
        assert "github_issues: on" in refused(capsys, command)
    assert not (repo / "r/forbidden").exists()
    assert cards.plan_path().read_text() == before
    assert xp.main(["recover"]) == 0
    assert "## shared cards" not in capsys.readouterr().out
    assert not state(repo)["calls"]
    isolated = repo / "isolated"
    isolated.mkdir()
    (isolated / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(isolated))
    assert "github_issues: on" in refused(capsys, ["card", "publish", "free-share"])
    assert "github_issues: on" in refused(capsys, ["card", "claim", "224"])


def test_shared_recovery(repo, monkeypatch, capsys):  # noqa: F811
    plan()
    assert xp.main(["card", "publish", "free-share"]) == 0
    first_data = str(cards.plan_path().parent)
    subprocess.run(["git", "clone", "-q", str(repo / "r"), str(repo / "second")], check=True)
    monkeypatch.chdir(repo / "second")
    monkeypatch.setenv("XP_DATA", str(repo / "second-data"))
    plan("")
    assert xp.main(["card", "claim", "224"]) == 0
    holder = next(
        x["name"][6:] for x in state(repo)["issues"][0]["labels"] if x["name"].startswith("clone:")
    )
    capsys.readouterr()
    assert xp.main(["recover"]) == 0
    assert f"{holder} (this clone)" in capsys.readouterr().out
    monkeypatch.chdir(repo / "r")
    monkeypatch.setenv("XP_DATA", first_data)
    s = state(repo)
    s["issues"][0]["labels"].append({"name": "clone:other@123456"})
    s["issues"][0]["labels"].append({"name": "merged"})
    nodes = [dict(i, labels={"nodes": i["labels"]}) for i in s["issues"]]
    later = dict(
        nodes[0],
        number=225,
        body=CARD.replace("free-share", "free-later"),
        labels={"nodes": [{"name": "card"}]},
    )
    malformed = dict(later, number=226, body="not a card")
    s["pages"] = [
        {"data": {"repository": {"issues": {"nodes": rows}}}}
        for rows in [nodes, [later, malformed]]
    ]
    save(repo, s)
    capsys.readouterr()
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out.split("## shared cards")[1]
    for text in [
        "#224 free-share",
        "shared work",
        holder,
        "other@123456",
        "merged, awaiting evidence: git cat-file -e origin/main:read.md",
        "#225 free-later",
        "unclaimed",
        "#226",
        "one valid card",
    ]:
        assert text in out
    assert "this clone" not in out
    assert "awaiting evidence" not in next(row for row in out.splitlines() if "#225" in row)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "Refs #225"], check=True)
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out
    assert "awaiting evidence" not in next(row for row in out.splitlines() if "#225" in row)
