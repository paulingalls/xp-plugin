import json
import subprocess
import sys

import xp
from test_land import commit, fake_gh, free_patch, git, ns
from xpcore import land

URL = "https://example.test/pull/232"


def run_land(root):
    return subprocess.run(
        [sys.executable, xp.__file__, "free", "land", "fix"],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_land_again_edits_the_open_pr_instead_of_creating(tmp_path, monkeypatch):
    gh = fake_gh(tmp_path, monkeypatch)
    root, data, wt = free_patch(tmp_path, monkeypatch)
    first = run_land(root)
    assert first.returncode == 0, first.stderr
    assert gh.read_text().count("pr create") == 1

    (data / "plan.md").write_text("#### free-fix — g   [in-progress]\nAcceptance: python3 -c 1\n")
    (data / "stories" / "free-fix").mkdir(parents=True, exist_ok=True)
    (data / "stories" / "free-fix" / "review-2.md").write_text("ok\n")
    commit(wt, {"more.txt": "x\n"}, "fix review")
    (tmp_path / "gh-view.json").write_text(json.dumps({"state": "OPEN", "url": URL}))
    gh.unlink()

    second = run_land(root)
    assert second.returncode == 0, second.stderr
    calls = gh.read_text()
    assert "pr view free-fix-x --json state,url" in calls
    assert "pr create" not in calls
    edit = next(line for line in calls.splitlines() if line.startswith("pr edit"))
    assert edit.startswith(f"pr edit {URL} --title g --body ")
    assert "review-2.md" in calls
    assert URL in second.stdout
    assert "after it merges, run `xp.py free post-merge free-fix`" in second.stdout
    assert git(root, "ls-remote", "origin", "free-fix-x").split()[0] == git(wt, "rev-parse", "HEAD")


def test_merged_pr_is_not_edited_a_new_one_is_created(tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    (tmp_path / "gh-view.json").write_text(json.dumps({"state": "MERGED", "url": URL}))
    free_patch(tmp_path, monkeypatch)
    assert land.cmd_free_land(ns("fix")) == 0
    calls = gh.read_text()
    assert calls.count("pr create --base main --head free-fix-x --title f --body") == 1
    assert "pr edit" not in calls
    assert "after it merges, run" in capsys.readouterr().out
