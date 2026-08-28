"""Existing free post-merge release regressions, split for the 500-line cap."""

import json
import subprocess
import sys
from pathlib import Path

import bookkeep
import pytest
from close_helpers import SPAWN, free, free_repo, marker_file, stub_reviewer
from spawn_helpers import stub_claude
from test_close_free import BRANCH, KEY, add_free_card, commit_on_free


class TestFreeTeardown:
    def test_a_failed_worktree_lookup_is_not_reported_as_absence(self, monkeypatch, tmp_path):
        failed = subprocess.CompletedProcess([], 1, "", "broken")
        monkeypatch.setattr(bookkeep, "git", lambda *args: failed)
        tree, branch, problems = bookkeep.story_worktree(tmp_path / "keyed-tree")
        assert (tree, branch, problems) == ("", "", ["git worktree list --porcelain"])

    def spawned(self, tmp_path, teardown=""):
        repo, env, g = free_repo(tmp_path)
        config = repo / ".xp" / "config.yml"
        config.write_text(
            config.read_text().replace("roles:\n", "roles:\n  executor: claude/sonnet/medium\n")
        )
        if teardown:
            system = repo / ".xp" / "system.md"
            system.write_text(system.read_text() + f"**Worktree teardown**: `{teardown}`\n")
        g("add", "-A")
        g("commit", "-qm", "spawn fixture")
        add_free_card(env)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        commit_on_free(repo, g)
        ready = subprocess.run(
            [sys.executable, str(SPAWN), "ready", KEY],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert ready.returncode == 0, ready.stderr
        stub_claude(tmp_path)
        launched = subprocess.run(
            [sys.executable, str(SPAWN), KEY],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert launched.returncode == 0, launched.stderr
        tree = Path(env["XP_DATA"]) / "worktrees" / KEY
        spawned_branch = g("-C", str(tree), "branch", "--show-current").stdout.strip()
        stub_reviewer(tmp_path)
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().replace("— fix typo", "— renamed after spawn"))
        assert free(tree, env, "fix-typo", "review").returncode == 0
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", BRANCH, "-m", "merge free release")
        return repo, env, g, tree, spawned_branch

    def unspawned(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        commit_on_free(repo, g)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", BRANCH, "-m", "merge free release")
        return repo, env, g

    def test_post_merge_removes_the_spawn_worktree_and_both_branches(self, tmp_path):
        repo, env, g, tree, spawned_branch = self.spawned(tmp_path)
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 0, result.stderr
        assert not tree.exists()
        branches = g("branch", "--format=%(refname:short)").stdout.splitlines()
        assert spawned_branch not in branches and BRANCH not in branches

    def test_a_failed_teardown_reports_after_every_discharge_continues(self, tmp_path):
        repo, env, g, tree, spawned_branch = self.spawned(tmp_path, teardown="false")
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 3 and "teardown failed" in result.stderr.lower()
        branches = g("branch", "--format=%(refname:short)").stdout.splitlines()
        assert not tree.exists() and spawned_branch not in branches and BRANCH not in branches
        assert not marker_file(tmp_path, KEY).exists()

    def test_a_card_that_will_not_flip_still_discharges_both_branches(self, tmp_path):
        repo, env, g, tree, spawned_branch = self.spawned(tmp_path)
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[done]"))
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 3 and KEY in result.stderr
        branches = g("branch", "--format=%(refname:short)").stdout.splitlines()
        assert not tree.exists() and spawned_branch not in branches and BRANCH not in branches

    def test_an_unspawned_free_close_has_no_missing_worktree_error(self, tmp_path):
        repo, env, g = self.unspawned(tmp_path)
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 0, result.stderr
        assert BRANCH not in g("branch", "--list").stdout


class TestFreePostMerge:
    def reviewed(self, tmp_path, card=False, manifest="", extra=""):
        """A reviewed free branch whose PR has NOT merged yet — the state the
        post-merge leg must refuse from."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        if card:
            add_free_card(env)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        if manifest:
            (repo / "plugin.json").write_text(json.dumps({"version": manifest}))
            extra += "version_files: plugin.json\n"
        if extra:
            config = repo / ".xp" / "config.yml"
            config.write_text(config.read_text() + extra)
            g("add", "-A")
            g("commit", "-qm", "release identity")
        return repo, env, g

    def merge_pr(self, g):
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", BRANCH, "-m", "merge free release")

    def test_post_merge_tags_the_merged_sha_and_retires_a_card(self, tmp_path):
        repo, env, g = self.reviewed(tmp_path, card=True)
        self.merge_pr(g)
        merged = g("rev-parse", "HEAD").stdout.strip()
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 0, result.stderr
        assert g("rev-list", "-n1", "v0.2.1").stdout.strip() == merged
        assert "[done]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
        # this project configured no version_files, and a tag cut with NOTHING
        # walling the manifest must not read like one that passed a check
        assert "NO manifest was checked" in result.stdout, result.stdout

    def test_post_merge_before_the_pr_merges_refuses_and_cuts_no_tag(self, tmp_path):
        """The ordering half of AC 4, which nothing else on this leg drives:
        blanking the branch the marker records leaves the whole suite green, and
        constraint 14 can only red once a wrong tag EXISTS."""
        repo, env, g = self.reviewed(tmp_path)
        g("checkout", "-q", "main")
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == 2 and BRANCH in result.stderr
        assert "v0.2.1" not in g("tag").stdout.split()

    def test_a_free_release_leaves_the_recorded_sprint_branch_alone(self, tmp_path):
        repo, env, g = self.reviewed(tmp_path)
        path = Path(env["XP_DATA"]) / "sprint_branch"
        path.write_text("sprint-001\n")
        self.merge_pr(g)
        assert free(repo, env, "fix-typo", "post-merge").returncode == 0
        assert path.read_text().strip() == "sprint-001"

    @pytest.mark.parametrize("manifest,rc", [("0.2.0", 2), ("0.2.1", 0)], ids=["behind", "level"])
    def test_the_manifest_must_name_the_tag_being_cut(self, tmp_path, manifest, rc):
        """AC 5 in BOTH directions: a guard only ever asserted red could refuse
        every release alike and no test here would know."""
        repo, env, g = self.reviewed(tmp_path, manifest=manifest)
        self.merge_pr(g)
        result = free(repo, env, "fix-typo", "post-merge")
        assert result.returncode == rc, result.stderr
        if rc:
            assert "plugin.json" in result.stderr and "behind" in result.stderr.lower()
        else:  # the pass NAMES what it checked, or it reads like the arm above
            assert "manifests matching v0.2.1: plugin.json" in result.stdout, result.stdout
        assert ("v0.2.1" in g("tag").stdout.split()) is (rc == 0)
