import json

import pytest
import xp
from test_land import git, make_project
from test_sprint import repo  # noqa: F401
from xpcore import hooks


def released(tmp_path, monkeypatch):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("## Sprint 1 — retro\n")
    folder = data / "sprints/1"
    folder.mkdir(parents=True)
    (folder / "release.json").write_text("{}")
    return root, data, folder


def result(monkeypatch, text="A lesson"):
    why = {"sightings": "Earlier miss", "cost": "An hour", "form": "Deletion suffices"}
    monkeypatch.setenv(
        "RETRO_RESULT",
        json.dumps(
            {
                "sightings": [{"lesson": "new:1", "text": text}],
                "proposals": [{"lessons": ["new:1"], "text": "Delete the step", "why": why}],
            }
        ),
    )


def test_direct_persistence_rerun_and_private_narrative(tmp_path, monkeypatch, fake_retro, capsys):
    root, data, folder = released(tmp_path, monkeypatch)
    git(root, "remote", "remove", "origin")
    result(monkeypatch)
    assert xp.main(["retro", "1"]) == 0
    ledger = data / "lessons.md"
    first = ledger.read_text()
    assert "- L1 [proposed] A lesson (seen: repo:1)" in first
    output = capsys.readouterr()
    assert "PRIVATE NARRATIVE" not in output.out + output.err
    for value in (
        "Delete the step",
        "Earlier miss",
        "An hour",
        "Deletion suffices",
        str(folder / "retro.md"),
    ):
        assert value in output.out
    assert "PRIVATE NARRATIVE" in (data / "logs/1-retro.log").read_text()
    assert "--model opus" in (fake_retro / "retro-argv").read_text()
    monkeypatch.setenv(
        "RETRO_MARKDOWN", "## Misses\nChanged\n## Sightings\nNew\n## Proposals\nDelete\n"
    )
    assert xp.main(["retro", "1"]) == 0
    assert ledger.read_text() == first
    assert "Changed" in (folder / "retro.md").read_text()


@pytest.mark.parametrize("failure", ["exit", "missing", "malformed", "unknown", "ledger"])
def test_failure_preserves_previous(tmp_path, monkeypatch, fake_retro, capsys, failure):
    from pathlib import Path

    root, data, folder = released(tmp_path, monkeypatch)
    git(root, "remote", "remove", "origin")
    old = folder / "retro.md"
    old.write_text("previous retro")
    ledger = data / "lessons.md"
    ledger.write_text("# previous ledger\n")
    result(monkeypatch)
    if failure == "exit":
        monkeypatch.setenv("RETRO_EXIT", "1")
    elif failure == "missing":
        monkeypatch.setenv("RETRO_MISSING", "1")
    elif failure == "malformed":
        monkeypatch.setenv("RETRO_RESULT", "{}")
    elif failure == "unknown":
        monkeypatch.setenv("RETRO_RESULT", '{"sightings":[{"lesson":"L99"}],"proposals":[]}')
    else:
        original = Path.replace

        def replace(p, target):
            if target == ledger:
                raise OSError("ledger blocked")
            return original(p, target)

        monkeypatch.setattr(Path, "replace", replace)
    assert xp.main(["retro", "1"]) != 0
    assert old.read_text() == "previous retro"
    assert ledger.read_text() == "# previous ledger\n"
    assert "xp.py retro 1" in capsys.readouterr().err


def test_hook_exits(tmp_path, monkeypatch, fake_retro):
    root, _data, _folder = released(tmp_path, monkeypatch)
    log = hooks.log_path("1-sprint-close")
    with log.open("a") as stream:
        assert (
            hooks.stream(["sh", "-c", "printf HOOK_OUTPUT_SENTINEL; exit 23"], root, stream) == 23
        )
        assert hooks.stream(["sh", "-c", "true"], root, stream) == 0
    assert "\nxp-hook-exit: 23\n" in log.read_text()
    assert xp.main(["retro", "1"]) == 0
    prompt = (fake_retro / "retro-prompt").read_text()
    assert "1-sprint-close.log: 23, 0" in prompt
    assert "HOOK_OUTPUT_SENTINEL" not in prompt
    assert "slate-review.md: absent" in prompt


def test_selected_artifacts_and_statuses(tmp_path, monkeypatch, fake_retro):
    root, data, folder = released(tmp_path, monkeypatch)
    git(root, "remote", "remove", "origin")
    (data / "plan.md").write_text(
        "## Sprint 1 — retro\n#### story-a — a [done]\n"
        "Files: a\nAcceptance: true\n## Sprint 2 — other\n#### story-b — b [done]\n"
    )
    story = data / "stories/story-a"
    story.mkdir(parents=True)
    for directory, names in (
        (story, ["plan-review.md", "review-1.md", "review-2.md", "handback.md"]),
        (
            folder,
            [
                "slate-review.md",
                "review-1.design.md",
                "review-2.security.md",
                "triage-2.security.md",
                "handback-1.md",
            ],
        ),
    ):
        for name in names:
            (directory / name).write_text(f"Evidence {name}")
    (data / "session.md").write_text("Session evidence")
    logs = data / "logs"
    logs.mkdir()
    (logs / "story-a-acceptance.log").write_text("$ old command\nPRIVATE OUTPUT\n")
    (logs / "story-b-acceptance.log").write_text("$ UNRELATED\n")
    ledger = data / "lessons.md"
    seed = "# preserved\n- Lessons remain project context.\n" + "".join(
        f"- L{i} [{status}] Lesson {i} (seen: prior:0) -> #issue disposition\n"
        for i, status in enumerate(("sighting", "proposed", "applied", "dropped"), 1)
    )
    ledger.write_text(seed)
    monkeypatch.setenv(
        "RETRO_RESULT",
        json.dumps(
            {
                "sightings": [{"lesson": f"L{i}"} for i in range(1, 5)],
                "proposals": [
                    {
                        "lessons": ["L1", "L3"],
                        "text": "Replace the rule",
                        "why": {"sightings": "S", "cost": "C", "form": "F"},
                    }
                ],
            }
        ),
    )
    assert xp.main(["retro", "1"]) == 0
    prompt = (fake_retro / "retro-prompt").read_text()
    for evidence in (
        "stories/story-a/plan-review.md:",
        "Evidence plan-review.md",
        "Evidence review-2.md",
        "Evidence handback-1.md",
        "Evidence slate-review.md",
        "Evidence triage-2.security.md",
        "Session evidence",
        "story-a-acceptance.log: unknown",
    ):
        assert evidence in prompt
    assert "UNRELATED" not in prompt and "PRIVATE OUTPUT" not in prompt
    assert "story-b-acceptance" not in prompt
    updated = ledger.read_text()
    expected = seed.replace("prior:0)", "prior:0, repo:1)")
    expected = expected.replace("- L1 [sighting]", "- L1 [proposed]")
    expected = expected.replace(
        "Lesson 1 (seen: prior:0, repo:1) -> #issue disposition",
        "Lesson 1 (seen: prior:0, repo:1) -> #issue disposition; sightings: S; cost: C; form: F",
    )
    assert updated == expected


@pytest.mark.parametrize("failure", ["harness", "role", "publish"])
def test_configuration_and_publish_failures(tmp_path, monkeypatch, fake_retro, failure):
    from pathlib import Path

    root, data, folder = released(tmp_path, monkeypatch)
    git(root, "remote", "remove", "origin")
    previous = folder / "retro.md"
    previous.write_text("old")
    ledger = data / "lessons.md"
    ledger.write_text("# old\n")
    result(monkeypatch)
    if failure == "harness":
        (tmp_path / "retro-bin/claude").unlink()
        # Isolate lookup from installed harnesses.
        from xpcore import launch

        monkeypatch.setattr(launch, "missing_harness", lambda _: "missing harness")
    elif failure == "role":
        (root / ".xp/config.yml").write_text("trunk: main\n")
    else:
        original = Path.replace

        def replace(path, target):
            if target == previous:
                raise OSError("publish denied")
            return original(path, target)

        monkeypatch.setattr(Path, "replace", replace)
    assert xp.main(["retro", "1"]) == 1
    assert previous.read_text() == "old" and ledger.read_text() == "# old\n"


def test_concurrent_clones_share_ledger(tmp_path, monkeypatch, fake_retro):
    import os
    import subprocess
    import sys

    from test_xp import XP

    root, data, folder = released(tmp_path, monkeypatch)
    # Hold both fake seats after their input snapshots, before either merge.
    script = tmp_path / "retro-bin/claude"
    source = script.read_text().replace(
        "path = re.search",
        "import time\n"
        'gate = Path(os.environ["RETRO_GATE"])\n'
        "gate.mkdir(exist_ok=True)\n"
        "(gate / Path.cwd().name).touch()\n"
        "until = time.monotonic() + 15\n"
        "while len(list(gate.iterdir())) < 2:\n"
        "    if time.monotonic() > until: sys.exit(7)\n"
        "    time.sleep(.02)\n"
        "path = re.search",
    )
    script.write_text(source)
    other = tmp_path / "second"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    other_data = tmp_path / "second-data"
    other_folder = other_data / "sprints/1"
    other_folder.mkdir(parents=True)
    (other_data / "plan.md").write_text((data / "plan.md").read_text())
    (other_folder / "release.json").write_text("{}")
    gate = tmp_path / "gate"
    processes = []
    for clone, local_data in ((root, data), (other, other_data)):
        answer = {
            "sightings": [
                {"lesson": "new:1", "text": "Common"},
                {"lesson": "new:2", "text": clone.name},
            ],
            "proposals": [],
        }
        env = os.environ | {
            "XP_DATA": str(local_data),
            "RETRO_GATE": str(gate),
            "RETRO_RESULT": json.dumps(answer),
        }
        processes.append(
            subprocess.Popen(
                [sys.executable, str(XP), "retro", "1"],
                cwd=clone,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    for process in processes:
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode == 0, stdout + stderr
    from xpcore import retro

    ledger = retro.ledger_path()
    text = ledger.read_text()
    assert "Common (seen: " in text
    assert "repo:1" in text and "second:1" in text
    assert len(retro.parse_ledger(text)) == 3
    assert (folder / "retro.md").is_file() and (other_folder / "retro.md").is_file()
    # Same clone/sprint rerun deduplicates both text and identity.
    result(monkeypatch, "Common")
    monkeypatch.setenv("RETRO_GATE", str(gate))
    assert xp.main(["retro", "1"]) == 0
    assert len(retro.parse_ledger(ledger.read_text())) == 3
    assert ledger.read_text().count("repo:1") == 2


@pytest.mark.parametrize("failed", [False, True])
def test_post_merge_runs_after_cleanup_and_dry_run_is_inert(
    repo,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
    fake_retro,
    failed,
):
    from test_land import fake_gh
    from test_sprint import merge_on_trunk
    from xpcore import config

    root, data, _ = repo
    fake_gh(tmp_path, monkeypatch)
    result(monkeypatch)
    script = tmp_path / "retro-bin/claude"
    script.write_text(
        script.read_text().replace(
            "prompt = sys.stdin.read()",
            'assert Path(os.environ["XP_DATA"], "sprints/1/release.json").is_file()\n'
            'assert not Path(os.environ["XP_DATA"], "sprint_branch").exists()\n'
            "import subprocess\n"
            'assert not subprocess.check_output(["git", "branch", "--list", "sprint-1"]).strip()\n'
            "prompt = sys.stdin.read()",
        )
    )
    assert xp.main(["sprint", "land", "1"]) == 0
    merge_on_trunk(root)
    capsys.readouterr()
    assert xp.main(["sprint", "post-merge", "1", "--dry-run"]) == 0
    folder = data / "sprints/1"
    assert not (folder / "release.json").exists()
    assert not (fake_retro / "retro-prompt").exists()
    assert not list(fake_retro.glob(".xp/projects/*/lessons.md*"))
    assert config.sprint_branch() == "sprint-1"
    if failed:
        monkeypatch.setenv("RETRO_EXIT", "1")
    assert xp.main(["sprint", "post-merge", "1"]) == 0
    output = capsys.readouterr()
    assert "PRIVATE NARRATIVE" not in output.out + output.err
    assert (folder / "release.json").is_file()
    assert config.sprint_branch() == ""
    assert git(root, "tag", "--list") == "v1.2.0"
    if failed:
        assert "xp.py retro 1" in output.err
        assert not (folder / "retro.md").exists()
    else:
        assert str(folder / "retro.md") in output.out
        assert "Deletion suffices" in output.out


@pytest.mark.parametrize(
    "origin", [None, "git@github.com:Owner/Repo.git", "https://github.com/Owner/Repo.git"]
)
def test_linked_worktree_path_and_explicit_role(tmp_path, monkeypatch, fake_retro, origin):
    from xpcore import retro

    root, data, folder = released(tmp_path, monkeypatch)
    if origin:
        git(root, "remote", "set-url", "origin", origin)
    else:
        git(root, "remote", "remove", "origin")
    (root / ".xp/config.yml").write_text(
        """trunk: main
roles:
  reviewer: claude/fallback
  retro: claude/explicit
"""
    )
    git(root, "add", ".xp/config.yml")
    git(root, "commit", "-qm", "explicit retro")
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-qb", "linked", str(linked))
    monkeypatch.chdir(linked)
    result(monkeypatch)
    assert xp.main(["retro", "1"]) == 0
    expected = fake_retro / ".xp/projects/owner-repo/lessons.md" if origin else data / "lessons.md"
    assert retro.ledger_path() == expected
    assert "(seen: repo:1)" in expected.read_text()
    assert "--model explicit" in (fake_retro / "retro-argv").read_text()
    assert (folder / "retro.md").is_file()
