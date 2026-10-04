import argparse
import json
import os
import subprocess

import pytest
from xpcore import cards, gitx, hooks, land, release

CONFIG = "trunk: main\nversion_files: package.json\nroles:\n  reviewer: claude/opus\n"
CHECK = "import pathlib, sys\nsys.exit(pathlib.Path('merged.txt').read_text() != 'ok\\n')\n"
CARD = "## Sprint 1 — s\n\n#### story-001 — add   [in-progress]\nAcceptance: python3 check.py\n"


def git(cwd, *args, env=None, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0 or not check, proc.stderr
    return proc.stdout.strip() if check else proc.returncode


def commit(cwd, files, message, when=None):
    for name, text in files.items():
        (cwd / name).parent.mkdir(parents=True, exist_ok=True)
        (cwd / name).write_text(text)
    git(cwd, "add", "-A")
    env = os.environ | ({"GIT_COMMITTER_DATE": f"@{when} +0000"} if when else {})
    git(cwd, "commit", "-qm", message, env=env)
    return git(cwd, "rev-parse", "HEAD")


def manifest(version):
    return {"package.json": json.dumps({"version": version}), "CHANGELOG.md": f"## {version}\n"}


def ns(identifier, dry_run=False):
    return argparse.Namespace(id=identifier, dry_run=dry_run)


def make_project(tmp_path, monkeypatch, config=CONFIG):
    origin, root, data = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "data"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(root))
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    commit(root, {".xp/config.yml": config, **manifest("1.1.0")}, "init")
    git(root, "push", "-q", "-u", "origin", "main")
    data.mkdir()
    monkeypatch.setenv("XP_DATA", str(data))
    monkeypatch.chdir(root)
    return root, data


def fake_gh(tmp_path, monkeypatch):
    (bin_ := tmp_path / "bin").mkdir()
    log = tmp_path / "gh.log"
    (bin_ / "gh").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    (bin_ / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.fixture
def story(tmp_path, monkeypatch):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text(CARD)
    git(root, "switch", "-qc", "sprint-001")
    (data / "sprint_branch").write_text("sprint-001\n")
    wt = data / "worktrees" / "story-001"
    git(root, "worktree", "add", "-q", "-b", "story-001-thing", str(wt))
    seen = commit(wt, {"check.py": CHECK}, "add check")
    review = data / "stories" / "story-001" / "review-1.md"
    review.parent.mkdir(parents=True)
    review.write_text(f"no findings\nreviewed: {seen}\n")
    late = commit(wt, {"later.txt": "x\n"}, "after the review")
    # The lead annotates the review after its commit; the file's age must not cover that.
    os.utime(review, (4_000_000_000, 4_000_000_000))
    return root, data, wt, late


def test_green_acceptance_on_the_merged_tree_lands_and_closes(story):
    root, data, wt, late = story
    # check.py reads merged.txt, which only the sprint branch has: green needs the trial merge.
    commit(root, {"merged.txt": "ok\n"}, "sprint work")
    assert land.cmd_story_land(ns("story-001")) == 0
    body = git(root, "log", "-1", "--format=%B")
    seen = git(root, "rev-parse", f"{late}^")
    assert "review-1.md" in body and f"unreviewed: {seen[:10]}..{late[:10]}" in body
    assert git(root, "rev-parse", "HEAD^2") == late
    assert cards.find_card("story-001").status == "done"
    closed = json.loads((data / "closes.jsonl").read_text())
    assert closed["id"] == "story-001" and closed["merge"] == git(root, "rev-parse", "HEAD")
    assert not wt.exists() and git(root, "branch", "--list", "story-001-thing") == ""


def test_red_acceptance_refuses_and_leaves_everything_unmerged(story, capsys):
    root, data, wt, _ = story
    before = commit(root, {"merged.txt": "bad\n"}, "sprint work")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_story_land(ns("story-001"))
    assert exit_.value.code == 2 and "Acceptance exited 1" in capsys.readouterr().err
    assert git(wt, "status", "--porcelain") == "" and not (wt / "merged.txt").exists()
    assert git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False) != 0
    assert git(root, "rev-parse", "HEAD") == before
    assert cards.find_card("story-001").status == "in-progress"
    assert (data / "logs" / "story-001-acceptance.log").is_file()


def test_unsafe_acceptance_refuses_before_merging(story, capsys):
    data = story[1]
    (data / "plan.md").write_text(CARD.replace("python3 check.py", "python3 check.py | cat"))
    with pytest.raises(SystemExit):
        land.cmd_story_land(ns("story-001"))
    assert "only `&&` chains" in capsys.readouterr().err


def test_overlap_warns_and_never_refuses(story, capsys):
    root = story[0]
    commit(root, {"merged.txt": "ok\n", "later.txt": "x\n"}, "sprint work")
    assert land.cmd_story_land(ns("story-001")) == 0
    assert "warning: sprint-001 also changed later.txt" in capsys.readouterr().out


def free_patch(tmp_path, monkeypatch, acceptance="python3 -c 1", files=None):
    root, data = make_project(tmp_path, monkeypatch)
    card = f"#### free-fix — f   [in-progress]\nAcceptance: {acceptance}\n"
    (data / "plan.md").write_text(card)
    wt = data / "worktrees" / "free-fix"
    git(root, "worktree", "add", "-q", "-b", "free-fix-x", str(wt))
    commit(wt, manifest("1.1.1") if files is None else files, "fix")
    return root, data, wt


def test_free_patch_lands_by_pr_then_tags_after_the_merge(tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    root, data, wt = free_patch(tmp_path, monkeypatch)
    (data / "stories" / "free-fix").mkdir(parents=True)
    (data / "stories" / "free-fix" / "review-1.md").write_text("ok\n")
    assert land.cmd_free_land(ns("fix")) == 0
    called = gh.read_text()
    assert "pr create --base main --head free-fix-x --title f --body free-fix: f" in called
    assert "review-1.md" in called and "--fill" not in called
    assert git(root, "ls-remote", "origin", "free-fix-x")
    with pytest.raises(SystemExit):
        land.cmd_free_post_merge(ns("fix"))
    assert "is not merged into main" in capsys.readouterr().err
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert git(root, "cat-file", "-t", "v1.1.1") == "tag"
    assert cards.find_card("free-fix").status == "done" and not wt.exists()


def test_target_moving_during_land_refuses_before_the_merge(story, monkeypatch, capsys):
    root = story[0]
    commit(root, {"merged.txt": "ok\n"}, "sprint work")

    def advance(*_):
        commit(root, {"other.txt": "x\n"}, "landed meanwhile")
        return 0

    monkeypatch.setattr(hooks, "run_acceptance", advance)
    with pytest.raises(SystemExit) as exit_:
        land.cmd_story_land(ns("story-001"))
    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert "sprint-001 moved during land; run xp.py story land story-001 again" in err
    assert git(root, "log", "-1", "--format=%s") == "landed meanwhile"
    assert cards.find_card("story-001").status == "in-progress"


def test_branch_without_commits_refuses(story, capsys):
    wt = story[2]
    git(wt, "reset", "-q", "--hard", "main")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_story_land(ns("story-001"))
    assert exit_.value.code == 2 and (
        "story-001 has no commits on story-001-thing; run xp.py story story-001"
        in capsys.readouterr().err
    )
    assert cards.find_card("story-001").status == "in-progress"


@pytest.mark.parametrize(
    "spoil, named",
    [
        (lambda root, wt: git(root, "switch", "-q", "main"), "must be on sprint-001"),
        (lambda root, wt: (wt / "stray.txt").write_text("x"), "has uncommitted changes"),
    ],
)
def test_wrong_lead_branch_or_dirty_worktree_refuses(story, capsys, spoil, named):
    root, _, wt, _ = story
    commit(root, {"merged.txt": "ok\n"}, "sprint work")
    spoil(root, wt)
    before = git(root, "rev-parse", "sprint-001")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_story_land(ns("story-001"))
    assert exit_.value.code == 2 and named in capsys.readouterr().err
    assert git(root, "rev-parse", "sprint-001") == before
    assert cards.find_card("story-001").status == "in-progress"


def test_missing_acceptance_binary_is_red(story, capsys):
    data = story[1]
    (data / "plan.md").write_text(CARD.replace("python3 check.py", "no-such-binary-xp"))
    with pytest.raises(SystemExit):
        land.cmd_story_land(ns("story-001"))
    assert "Acceptance exited 127" in capsys.readouterr().err
    assert cards.find_card("story-001").status == "in-progress"


def test_free_land_trial_merges_the_fetched_origin_trunk(tmp_path, monkeypatch):
    gh = fake_gh(tmp_path, monkeypatch)
    files = {**manifest("1.1.1"), "check.py": CHECK}
    free_patch(tmp_path, monkeypatch, "python3 check.py", files)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    commit(other, {"merged.txt": "ok\n"}, "pushed elsewhere")
    git(other, "push", "-q", "origin", "main")
    # Only a fetch brings merged.txt, so a green Acceptance proves origin/main was merged.
    assert land.cmd_free_land(ns("fix")) == 0
    assert "pr create" in gh.read_text()


def test_free_land_without_origin_merges_local_trunk_and_says_so(tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    root, _, _ = free_patch(tmp_path, monkeypatch)
    git(root, "remote", "remove", "origin")
    assert land.cmd_free_land(ns("fix")) == 0
    out = capsys.readouterr().out
    assert "no remote named origin; trial-merging the local main" in out
    assert "open the PR to main by hand" in out and not gh.exists()


def test_free_land_walls_the_version_before_the_pr(tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    root, _, _ = free_patch(tmp_path, monkeypatch, files={"fix.txt": "x\n"})
    git(root, "tag", "v1.1.0")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_free_land(ns("fix"))
    assert exit_.value.code == 2 and "tag v1.1.0 already exists" in capsys.readouterr().err
    assert not gh.exists() and not git(root, "ls-remote", "origin", "free-fix-x")


def test_free_post_merge_runs_acceptance_on_trunk_before_tagging(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    files = {**manifest("1.1.1"), "check.py": CHECK, "merged.txt": "ok\n"}
    root, _, wt = free_patch(tmp_path, monkeypatch, "python3 check.py", files)
    assert land.cmd_free_land(ns("fix")) == 0
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    commit(root, {"merged.txt": "bad\n"}, "trunk broke it")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_free_post_merge(ns("fix"))
    err = capsys.readouterr().err
    assert exit_.value.code == 2 and "Acceptance exited 1 on main at " in err
    assert "then run xp.py free post-merge fix again" in err
    assert git(root, "tag", "--list", "v1.1.1") == ""
    assert cards.find_card("free-fix").status == "in-progress" and wt.exists()


def test_a_card_changed_since_spawn_is_shown_and_named_never_refused(story, capsys):
    root, data = story[0], story[1]
    (data / "stories" / "story-001" / "card.md").write_text(CARD.split("\n", 2)[2])
    (data / "plan.md").write_text(CARD.replace("check.py\n", "check.py\nAC: less.\n"))
    commit(root, {"merged.txt": "ok\n"}, "sprint work")
    assert land.cmd_story_land(ns("story-001")) == 0
    assert "card changed since spawn: AC" in git(root, "log", "-1", "--format=%B")
    assert "+AC: less." in capsys.readouterr().out


def test_a_land_whose_close_failed_finishes_on_rerun(story, monkeypatch, capsys):
    root, data, wt, _ = story
    commit(root, {"merged.txt": "ok\n"}, "sprint work")
    remove = gitx.worktree_remove

    def locked(*_, **__):
        raise gitx.GitError("git worktree remove: locked")

    monkeypatch.setattr(gitx, "worktree_remove", locked)
    with pytest.raises(gitx.GitError):
        land.cmd_story_land(ns("story-001"))
    merged = git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(gitx, "worktree_remove", remove)
    assert land.cmd_story_land(ns("story-001")) == 0
    assert "finished a previous land of story-001" in capsys.readouterr().out
    assert cards.find_card("story-001").status == "done" and not wt.exists()
    assert json.loads((data / "closes.jsonl").read_text())["merge"] == merged


def test_free_post_merge_accepts_a_squash_merge_and_discourages_it(tmp_path, monkeypatch, capsys):
    root, _, wt = free_patch(tmp_path, monkeypatch)
    git(root, "merge", "-q", "--squash", "free-fix-x")
    git(root, "commit", "-qm", "squashed PR")
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert "free-fix was squash-merged; its history is not on main" in capsys.readouterr().out
    assert git(root, "cat-file", "-t", "v1.1.1") == "tag" and not wt.exists()


def test_free_post_merge_unmerged_names_squash_merges(tmp_path, monkeypatch, capsys):
    free_patch(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        land.cmd_free_post_merge(ns("fix"))
    assert "if the PR was squash- or rebase-merged" in capsys.readouterr().err


def test_free_post_merge_rerun_after_its_tag_finishes_without_tagging(tmp_path, monkeypatch):
    root, _, wt = free_patch(tmp_path, monkeypatch)
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    git(root, "tag", "-a", "v1.1.1", "-m", "v1.1.1")

    def no_second_tag(_):
        raise AssertionError("tagged twice")

    monkeypatch.setattr(release, "tag", no_second_tag)
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert cards.find_card("free-fix").status == "done" and not wt.exists()
