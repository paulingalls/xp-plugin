"""story-049: a stopped story is resumed by a fresh teammate in its own tree."""

import json
import os
import subprocess
import sys

import pytest
from spawn_helpers import SPAWN, in_tree, make_repo, spawn, stub_claude


def stopped_story(tmp_path):
    repo, env, g = make_repo(tmp_path)
    plans = tmp_path / "data" / "plans"
    plans.mkdir(exist_ok=True)
    (plans / "story-042.plan.md").write_text("DRAFT-SENTINEL\n")
    stub_claude(tmp_path, commit=False)
    stopped = spawn(repo, env, "story-042")
    assert stopped.returncode == 2 and "no commits" in stopped.stderr.lower(), stopped.stderr
    # the FIRST stop is the one that has to name the verb; nothing else will
    assert "spawn.py resume story-042" in stopped.stderr, stopped.stderr
    tree = tmp_path / "data" / "worktrees" / "story-042"
    marker = plans / "story-042.handoff.json"
    assert tree.is_dir() and marker.is_file()
    return repo, env, g, tree, marker


def finished_story(tmp_path):
    repo, env, g = make_repo(tmp_path)
    stub_claude(tmp_path)
    finished = spawn(repo, env, "story-042")
    assert finished.returncode == 0, finished.stderr
    tree = tmp_path / "data" / "worktrees" / "story-042"
    marker = tmp_path / "data" / "plans" / "story-042.handoff.json"
    assert json.loads(marker.read_text())["state"] == "FINISHED"
    return repo, env, g, tree, marker


def commit(tree, env, name="predecessor.py"):
    (tree / name).write_text("PREDECESSOR-SENTINEL\n")
    subprocess.run(["git", "add", name], cwd=tree, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "predecessor work"], cwd=tree, env=env, check=True)
    return in_tree(tree, env, "rev-parse", "HEAD")


def stub_killer(tmp_path):
    """A launch that dies without ever handing back — story-060's own incident."""
    killer = tmp_path / "bin" / "claude"
    killer.write_text(
        "#!/usr/bin/env python3\nimport os, signal, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']: sys.exit(1)\nsys.stdin.read()\n"
        "os.kill(os.getppid(), signal.SIGKILL)\n"
    )
    killer.chmod(0o755)


def stub_takeover(tmp_path, adopted=(), nested=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "resume-launch.json"
    nested_result = tmp_path / "nested-resume.json"
    second_launch = tmp_path / "second-launch"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, subprocess, sys",
        "if sys.argv[1:] == ['plugin', 'list', '--json']: sys.exit(1)",
        "stdin = sys.stdin.read()",
        f"json.dump({{'stdin': stdin}}, open({str(rec)!r}, 'w'))",
        f"if os.environ.get('NESTED_RESUME'): open({str(second_launch)!r}, 'w').write('launched')",
    ]
    if nested:
        body += [
            "if not os.environ.get('NESTED_RESUME'):",
            "    env = dict(os.environ, NESTED_RESUME='1')",
            f"    p = subprocess.run([{sys.executable!r}, {str(SPAWN)!r}, 'resume',",
            "                        'story-042'], env=env, capture_output=True, text=True)",
            f"    json.dump({{'rc': p.returncode, 'stderr': p.stderr}},"
            f" open({str(nested_result)!r}, 'w'))",
        ]
    if adopted:
        body += [
            f"subprocess.run(['git', 'add', {', '.join(repr(p) for p in adopted)}], check=True)",
            "subprocess.run(['git', 'commit', '-qm', 'adopt predecessor work'], check=True)",
        ]
    else:
        body.append("subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'successor work'])")
    body.append("print(json.dumps({'type': 'result', 'subtype': 'success'}))")
    path = bin_dir / "claude"
    path.write_text("\n".join(body) + "\n")
    path.chmod(0o755)
    return rec, nested_result, second_launch


def resume(repo, env, *args):
    return spawn(repo, env, "resume", "story-042", *args)


class TestResume:
    def test_a_clean_finished_handback_is_resumed_without_recreating_it(self, tmp_path):
        repo, env, _g, tree, _marker = finished_story(tmp_path)
        predecessor = in_tree(tree, env, "rev-parse", "HEAD")
        stub_takeover(tmp_path)

        result = resume(repo, env)

        assert result.returncode == 0, result.stderr
        commits = in_tree(tree, env, "log", "--format=%H")
        assert predecessor in commits and len(commits.splitlines()) >= 3

    def test_a_killed_successor_does_not_leave_a_finished_credential(self, tmp_path):
        repo, env, _g, _tree, marker = finished_story(tmp_path)
        stub_killer(tmp_path)

        killed = resume(repo, env)

        assert killed.returncode < 0
        assert json.loads(marker.read_text())["state"] == "RUNNING"
        rec, _nested, _second = stub_takeover(tmp_path)
        refused = resume(repo, env)
        assert refused.returncode == 2 and "RUNNING" in refused.stderr
        assert "FINISHED" not in refused.stderr, "a dead launch was offered the credential"
        assert not rec.exists(), "resume trusted a FINISHED state from the earlier run"

    def test_an_interrupted_launch_takes_the_repair_its_refusal_names(self, tmp_path):
        """Constraint 12: the refusal prescribes a repair, so walk it rather than ship it
        unrun. `spawn.py resume` is the only route back to a tree a dead launch left."""
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        stub_killer(tmp_path)
        assert resume(repo, env).returncode < 0
        refused = resume(repo, env)
        assert refused.returncode == 2 and "INTERRUPTED" in refused.stderr, refused.stderr
        rec, _nested, _second = stub_takeover(tmp_path)

        marker.write_text(json.dumps(json.loads(marker.read_text()) | {"state": "STOPPED"}))

        assert resume(repo, env).returncode == 0, "the prescribed repair does not resume"
        assert "STOPPED" in json.loads(rec.read_text())["stdin"]

    def test_fresh_teammate_reuses_the_tree_commit_branch_and_draft(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        predecessor = commit(tree, env)
        rec = stub_claude(tmp_path)

        result = resume(repo, env)

        assert result.returncode == 0, result.stderr
        assert tree.is_dir()
        assert in_tree(tree, env, "branch", "--show-current") == "ada/story-042-demo-story"
        assert predecessor in in_tree(tree, env, "log", "--format=%H")
        assert "DRAFT-SENTINEL" in json.loads(rec.read_text())["stdin"]

    def test_a_tree_off_its_stopped_branch_is_never_taken_over(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        subprocess.run(["git", "checkout", "-q", "--detach"], cwd=tree, env=env, check=True)
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "not on stopped branch" in result.stderr
        assert not rec.exists(), "resume launched into a tree it could not identify"

    def test_a_removed_worktree_refuses_rather_than_launching_nowhere(self, tmp_path):
        repo, env, g, tree, _marker = stopped_story(tmp_path)
        assert g("worktree", "remove", "--force", str(tree)).returncode == 0
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "is missing" in result.stderr, result.stderr
        assert not rec.exists(), "resume launched with no tree to take over"

    def test_an_unreadable_handoff_is_not_read_as_an_absent_one(self, tmp_path):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        marker.write_text('{"why": "no comm')
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "unreadable" in result.stderr, result.stderr
        assert "INTERRUPTED" not in result.stderr  # constraint 15: different problems
        assert not rec.exists(), "a truncated marker was taken as proof of a stop"

    def test_resume_refuses_a_card_no_longer_open_for_work(self, tmp_path):
        repo, env, _g, _tree, _marker = stopped_story(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]"))
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "resume requires" in result.stderr, result.stderr
        assert not rec.exists(), "resume launched on a card no reviewer had cleared"

    def test_the_successor_is_told_which_commits_are_not_its_own(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        predecessor = commit(tree, env)
        rec = stub_claude(tmp_path)

        assert resume(repo, env).returncode == 0

        prompt = json.loads(rec.read_text())["stdin"]
        assert predecessor[:7] in prompt and "predecessor work" in prompt, prompt
        assert "NOT yours" in prompt, "the inherited commits are handed over unlabelled"

    def test_a_finished_successor_preserves_the_predecessor_record_chain(self, tmp_path):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        root = tmp_path / "data"
        (root / "work.md").write_text(
            "## note 2026-08-27T00:00:00Z\nId: deadbeef\nStory: story-042\nRECORD-SENTINEL\n"
        )
        state = json.loads(marker.read_text())
        state["records"] = ["deadbeef"]
        marker.write_text(json.dumps(state))
        stub_takeover(tmp_path)
        assert resume(repo, env).returncode == 0
        finished = json.loads(marker.read_text())
        assert finished["state"] == "FINISHED" and finished["records"] == ["deadbeef"]
        rec, _nested, _second = stub_takeover(tmp_path)

        assert resume(repo, env).returncode == 0

        prompt = json.loads(rec.read_text())["stdin"]
        assert "FINISHED" in prompt and "RECORD-SENTINEL" in prompt
        assert "Why the predecessor stopped" not in prompt

    @pytest.mark.parametrize("state", ["STOPPED", "FINISHED"])
    def test_the_successor_is_told_which_handback_state_it_inherits(self, tmp_path, state):
        case = tmp_path / state.lower()
        case.mkdir()
        if state == "STOPPED":
            repo, env, _g, tree, marker = stopped_story(case)
            predecessor = commit(tree, env)
        else:
            repo, env, _g, tree, marker = finished_story(case)
            predecessor = in_tree(tree, env, "rev-parse", "HEAD")
        assert json.loads(marker.read_text())["state"] == state
        rec, _nested, _second = stub_takeover(case)

        result = resume(repo, env)

        assert result.returncode == 0, result.stderr
        prompt = json.loads(rec.read_text())["stdin"]
        assert state in prompt and predecessor[:7] in prompt, prompt

    @pytest.mark.parametrize("marker_state", [None, "UNKNOWN", "EMPTY", "NONSTRING"])
    def test_marker_presence_without_a_valid_state_proves_nothing(self, tmp_path, marker_state):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        contents = json.loads(marker.read_text())
        if marker_state == "EMPTY":
            contents.clear()
        elif marker_state == "NONSTRING":
            contents["state"] = []
        elif marker_state is None:
            contents.pop("state", None)
        else:
            contents["state"] = marker_state
        marker.write_text(json.dumps(contents))
        rec, _nested, _second = stub_takeover(tmp_path)

        result = resume(repo, env)

        assert result.returncode == 2 and "invalid handoff state" in result.stderr
        assert all(
            text in result.stderr
            for text in ("discard", "real STOPPED recovery", "never forge FINISHED")
        )
        assert not rec.exists(), "resume launched from an unenumerated marker state"

    def test_plain_spawn_still_refuses_a_running_teammates_worktree(self, tmp_path):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        marker.unlink()
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = spawn(repo, env, "story-042")

        assert result.returncode == 2 and "already spawned" in result.stderr
        assert not rec.exists(), "plain spawn launched a second teammate"

    def test_plain_spawn_refuses_a_finished_worktree_too(self, tmp_path):
        repo, env, _g, _tree, _marker = finished_story(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))

        result = spawn(repo, env, "story-042")

        assert result.returncode == 2 and "already spawned" in result.stderr

    def test_card_drift_refuses_until_the_real_remint_route_runs(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: answer added."))

        refused = resume(repo, env)

        assert refused.returncode == 2 and "edited after its plan review" in refused.stderr
        assert "spawn.py amend story-042" in refused.stderr, refused.stderr
        assert in_tree(tree, env, "rev-parse", "HEAD")

        amended = spawn(
            repo, env, "amend", "story-042", "--reason", "the answer changed during execution"
        )
        assert amended.returncode == 0, amended.stderr
        stub_claude(tmp_path)
        assert resume(repo, env).returncode == 0
        assert "[in-progress]" in plan.read_text()

    def test_predecessor_commit_is_not_credited_to_a_successor_that_commits_nothing(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        commit(tree, env)
        stub_claude(tmp_path, commit=False)

        result = resume(repo, env)

        assert result.returncode == 2
        assert "no commits" in result.stderr.lower(), result.stderr

    def test_dirty_diff_is_evidence_and_partial_adoption_stays_a_handback(self, tmp_path):
        repo, env, _g, tree, marker = stopped_story(tmp_path)
        (tree / "first.py").write_text("first predecessor edit\n")
        (tree / "second.py").write_text("second predecessor edit\n")
        rec, _nested, _second = stub_takeover(tmp_path, adopted=("first.py",))

        result = resume(repo, env)

        assert result.returncode == 2, result.stderr
        prompt = json.loads(rec.read_text())["stdin"]
        for evidence in ("first.py", "second.py", "git diff", "predecessor"):
            assert evidence in prompt, prompt
        assert "second.py" in result.stderr, result.stderr
        assert "spawn.py resume story-042" in result.stderr, result.stderr
        assert marker.exists(), "a partial takeover was made non-resumable"

    def test_a_finished_tree_that_became_dirty_loses_its_credential(self, tmp_path):
        repo, env, _g, tree, _marker = finished_story(tmp_path)
        (tree / "after-finish.txt").write_text("late dirt\n")
        rec, _nested, _second = stub_takeover(tmp_path)

        result = resume(repo, env)

        assert result.returncode == 2, result.stderr
        assert "FINISHED" in result.stderr and "after-finish.txt" in result.stderr
        assert not rec.exists(), "resume inherited a changed clean-success tree"

    def test_a_finished_successor_failure_names_its_own_remaining_work(self, tmp_path):
        repo, env, _g, _tree, _marker = finished_story(tmp_path)
        stub_claude(tmp_path, write_file=True, add_all=False)

        result = resume(repo, env)

        assert result.returncode == 2
        assert "remaining work" in result.stderr
        assert "remaining predecessor diff" not in result.stderr

    def test_resume_names_a_story_that_was_never_spawned(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec, _nested, _second = stub_takeover(tmp_path)

        result = resume(repo, env)

        assert result.returncode == 2 and "NEVER SPAWNED" in result.stderr
        assert not rec.exists(), "resume launched without a predecessor worktree"

    def test_a_marker_less_tree_is_named_interrupted_rather_than_running(self, tmp_path):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        marker.unlink()
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "INTERRUPTED" in result.stderr, result.stderr
        assert not rec.exists(), "resume launched without evidence of a stop"

    def test_a_teammate_that_is_actually_running_is_refused_by_the_lock(self, tmp_path):
        """The other arm: what entitles the refusal above to say a marker-less tree is
        NOT running. A live teammate holds the launch lock and never reaches validate."""
        repo, env, g, tree, marker = stopped_story(tmp_path)
        assert g("worktree", "remove", "--force", str(tree)).returncode == 0
        assert g("branch", "-D", "ada/story-042-demo-story").returncode == 0
        marker.unlink()
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        _rec, nested, second = stub_takeover(tmp_path, nested=True)

        assert spawn(repo, env, "story-042").returncode == 0

        attempted = json.loads(nested.read_text())
        assert attempted["rc"] == 2 and "launch in progress" in attempted["stderr"]
        assert "INTERRUPTED" not in attempted["stderr"], "a live teammate was called abandoned"
        assert not second.exists(), "resume joined a running teammate"

    def test_a_second_resume_refuses_while_the_first_holds_the_story(self, tmp_path):
        repo, env, _g, _tree, _marker = stopped_story(tmp_path)
        _rec, nested, second = stub_takeover(tmp_path, nested=True)

        outer = resume(repo, env)

        assert outer.returncode == 0, outer.stderr
        attempted = json.loads(nested.read_text())
        assert attempted["rc"] == 2 and "already" in attempted["stderr"].lower()
        assert not second.exists(), "the nested resume launched a second teammate"

    def test_resume_cannot_join_a_normal_respawn_with_an_old_handoff(self, tmp_path):
        repo, env, g, tree, _marker = stopped_story(tmp_path)
        assert g("worktree", "remove", "--force", str(tree)).returncode == 0
        assert g("branch", "-D", "ada/story-042-demo-story").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        _rec, nested, second = stub_takeover(tmp_path, nested=True)

        outer = spawn(repo, env, "story-042")

        assert outer.returncode == 0, outer.stderr
        attempted = json.loads(nested.read_text())
        assert attempted["rc"] == 2 and "already" in attempted["stderr"].lower()
        assert not second.exists(), "resume joined the normal respawn"


def test_resume_help_names_the_explicit_verb():
    result = subprocess.run(
        [sys.executable, str(SPAWN), "resume", "--help"],
        env=os.environ,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and "spawn.py resume" in result.stdout
