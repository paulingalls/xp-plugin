"""The review leg against sprint integration and trunk motion.
Split from test_close.py at sprint-004 open."""

import subprocess
import sys

from close_helpers import (
    CLEAN,
    CLOSE,
    CONFIG,
    close,
    close_bare,
    make_repo,
    stub_reviewer,
)


class TestSprintIntegration:
    def sprint_repo(self, tmp_path, branch="sprint-001"):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        (tmp_path / "data" / "sprint_branch").write_text(branch + "\n")
        g("checkout", "-q", "main")
        g("add", "-A")
        g("commit", "-qm", "sprint config")
        # real mid-sprint shape: sprint-001 has DIVERGED from main before the story
        g("checkout", "-qb", branch)
        (repo / "sprint-work.txt").write_text("earlier story landed here\n")
        g("add", "-A")
        g("commit", "-qm", "earlier sprint story")
        # story branches off the sprint branch, not main
        g("branch", "-D", "story-042-branch")
        g("checkout", "-qb", "story-042-branch")
        (repo / "src" / "thing.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "story work")
        return repo, env, g

    def test_two_clone_roots_merge_only_into_their_recorded_sprint_branch(self, tmp_path):
        for name, branch in (("one", "sprint-one"), ("two", "sprint-two")):
            root = tmp_path / name
            root.mkdir()
            repo, env, g = self.sprint_repo(root, branch)
            assert "earlier story landed here" not in close(repo, env, "review").stdout
            landed = close(repo, env, "land")
            assert landed.returncode == 0, landed.stderr
            assert "Review round 1" in g("log", branch, "-1", "--format=%B").stdout
            assert "Review round" not in g("log", "main", "--format=%B").stdout

    def test_sprint_release_without_branch_key_falls_back_to_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "sprint release, no branch yet")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_story_release_ignores_sprint_branch_key(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: story\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("branch", "sprint-001", "main")
        g("add", "-A")
        g("commit", "-qm", "story release")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_guards_watch_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "sprint-001" in r.stderr and "conflicts" in r.stderr

    def test_main_motion_does_not_block_sprint_close(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "main-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved — sprint close's concern, not ours")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr

    def test_the_documented_invocation_works_on_a_sprint_branch(self, tmp_path):
        """Broad review B2: `merge-mode` appears in NO shipped prose, and the
        documented `close.py story <id> land` defaulted to pr — which cmd_land
        refuses whenever the integration target is not the default branch. So the
        invocation the skill tells a consuming project to run was the one that
        refuses. The mode is derived now."""
        repo, env, g = self.sprint_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close_bare(repo, env, "review").returncode == 0
        r = close_bare(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "sprint-001", "-1", "--format=%B").stdout

    def test_pr_mode_with_sprint_target_refused(self, tmp_path):
        repo, env, _g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr

    def test_start_from_default_branch_still_refused(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("checkout", "-q", "main")
        r = close(repo, env, "review")
        assert r.returncode == 2

    def test_stale_tracked_sprint_branch_refuses_with_removal(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\nsprint_branch:\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "config names a branch that does not exist")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "remove" in r.stderr and "sprint_branch" in r.stderr

    def test_recorded_sprint_branch_missing_refused(self, tmp_path):
        repo, env, _g = self.sprint_repo(tmp_path)
        (tmp_path / "data" / "sprint_branch").write_text("sprint-missing\n")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "sprint-missing" in r.stderr

    def test_tag_named_like_sprint_branch_cannot_freeze_the_guard(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("tag", "sprint-001", "main")  # refs/tags wins plain rev-parse; guard must not care
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "refs/heads/sprint-001" in r.stderr and "conflicts" in r.stderr

    def test_pr_refusal_precedes_moved_check(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "sprint-001")
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")  # overlapping: the costly check
        g("add", "-A")
        g("commit", "-qm", "moved")
        g("push", "-q", "origin", "sprint-001")  # origin's sprint branch moves too
        g("checkout", "-q", "story-042-branch")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr and "src/thing.py" not in r.stderr
