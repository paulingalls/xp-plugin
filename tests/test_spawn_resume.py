"""story-049: a stopped story is resumed by a fresh teammate in its own tree."""

import json
import os
import subprocess
import sys

from spawn_helpers import SPAWN, in_tree, make_repo, spawn, stub_claude


def stopped_story(tmp_path):
    repo, env, g = make_repo(tmp_path)
    plans = tmp_path / "data" / "plans"
    plans.mkdir(exist_ok=True)
    (plans / "story-042.plan.md").write_text("DRAFT-SENTINEL\n")
    stub_claude(tmp_path, commit=False)
    stopped = spawn(repo, env, "story-042")
    assert stopped.returncode == 2 and "no commits" in stopped.stderr.lower(), stopped.stderr
    tree = tmp_path / "data" / "worktrees" / "story-042"
    marker = plans / "story-042.handoff.json"
    assert tree.is_dir() and marker.is_file()
    return repo, env, g, tree, marker


def commit(tree, env, name="predecessor.py"):
    (tree / name).write_text("PREDECESSOR-SENTINEL\n")
    subprocess.run(["git", "add", name], cwd=tree, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "predecessor work"], cwd=tree, env=env, check=True)
    return in_tree(tree, env, "rev-parse", "HEAD")


def stub_takeover(tmp_path, adopted=(), nested=False):
    bin_dir = tmp_path / "bin"
    rec = tmp_path / "resume-launch.json"
    nested_result = tmp_path / "nested-resume.json"
    second_launch = tmp_path / "second-launch"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, subprocess, sys",
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

    def test_plain_spawn_still_refuses_the_existing_worktree(self, tmp_path):
        repo, env, _g, _tree, _marker = stopped_story(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = spawn(repo, env, "story-042")

        assert result.returncode == 2 and "already spawned" in result.stderr
        assert not rec.exists(), "plain spawn launched a second teammate"

    def test_card_drift_refuses_until_the_real_remint_route_runs(self, tmp_path):
        repo, env, _g, tree, _marker = stopped_story(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: answer added."))

        refused = resume(repo, env)

        assert refused.returncode == 2 and "edited after its plan review" in refused.stderr
        for instruction in ("[planned]", "plan_review.py", "spawn.py ready", "spawn.py resume"):
            assert instruction in refused.stderr, refused.stderr
        assert in_tree(tree, env, "rev-parse", "HEAD")

        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]"))
        minted = spawn(repo, env, "ready", "story-042")
        assert minted.returncode == 0, minted.stderr
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

    def test_resume_without_a_handoff_marker_cannot_join_a_live_teammate(self, tmp_path):
        repo, env, _g, _tree, marker = stopped_story(tmp_path)
        marker.unlink()
        rec = tmp_path / "launch.json"
        rec.unlink()

        result = resume(repo, env)

        assert result.returncode == 2 and "still be running" in result.stderr.lower()
        assert not rec.exists(), "resume launched without evidence of a stop"

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
