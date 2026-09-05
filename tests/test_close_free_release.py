"""Free mode's patch-release leg: the land guards, the bump it reads, and the
judgment its skill carries that no script can."""

import json
import subprocess
import sys

import pytest
from close_free_card_cases import (
    add_free_card,
    commit_on_free,
    control_subprocess_date,
    free_identity,
)
from close_helpers import (
    CLOSE,
    NEW_FILE_PATCH,
    PLUGIN,
    free,
    free_repo,
    gh_calls,
    marker_file,
    stub_reviewer,
)
from test_close_free import reviewed


class TestFreeCloseSkill:
    def test_it_carries_only_the_judgment_the_scripts_cannot(self):
        """The word budget lives with its siblings in test_close_prose.py, at the
        LIVE size; a second cap here was 41 words of slack. This is the budget's
        counterweight: the sentences it must not be satisfied by deleting, and the
        release enumeration it must not admit (the sprint-close twin's negative)."""
        body = (PLUGIN / "skills" / "free-close" / "SKILL.md").read_text().split("---", 2)[2]
        text = " ".join(body.split())
        assert "`close.py free <slug> review`" in text
        assert "`close.py free <slug> land`" in text
        assert "release artifacts are yours" in text.lower()
        assert "before review" in text.lower()
        assert "bump" not in text.lower() and "changelog" not in text.lower()
        assert "inside the round that found" in text
        assert "past what the review covered" in text and "confirming round" in text
        assert "finding bar" in text and "JUDGMENT.md" in text


class TestFreeLand:
    @pytest.mark.slow
    def test_land_opens_the_pr_to_main_with_the_patch_bump(self, tmp_path):
        """AC 3: v0.2.0 -> v0.2.1. A free close targeting main IS a release, and
        a minor bump here would claim a sprint's worth of change."""
        repo, env, _g = reviewed(tmp_path)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        create = [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]
        assert len(create) == 1, gh_calls(tmp_path)
        assert "v0.2.1" in " ".join(create[0])
        assert "--base" in create[0] and create[0][create[0].index("--base") + 1] == "main"

    def test_land_with_no_report_refuses(self, tmp_path):
        """AC 4: the report is pipeline-received, so its absence is the whole
        gate — there is no flag that supplies one."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2
        assert "review" in r.stderr and not gh_calls(tmp_path)

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, g = reviewed(tmp_path)
        _branch, key = free_identity(g)
        path = marker_file(tmp_path, key)
        state = json.loads(path.read_text())
        state["rounds"][-1]["blocking"] = ["a real defect"]
        path.write_text(json.dumps(state))
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and "a real defect" in r.stderr

    def test_land_refuses_from_anywhere_but_its_own_free_branch(self, tmp_path):
        """The recorded round names a branch; land pushes HEAD. Without this,
        a merged free close replays from main — every other guard passes there,
        because shown_sha is an ancestor of main once the PR lands."""
        repo, env, g = reviewed(tmp_path)
        branch, _key = free_identity(g)
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and branch in r.stderr
        assert not gh_calls(tmp_path)

    def test_land_refuses_a_dirty_tree(self, tmp_path):
        repo, env, _g = reviewed(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 99\n")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and "dirty" in r.stderr

    def test_the_bump_comes_off_trunk_not_off_this_branch(self, tmp_path):
        """A sprint released v0.3.0 while this branch was open. Its tag is not
        REACHABLE from a branch cut before it, so a bump read here re-ships a
        version already shipped — and the instruction tags v0.2.1 at content
        that is v0.3.0 plus this fix."""
        repo, env, g = reviewed(tmp_path)
        branch, _key = free_identity(g)
        g("checkout", "-q", "main")
        (repo / "sprint.md").write_text("shipped\n")
        g("add", "-A")
        g("commit", "-qm", "sprint 5 released")
        g("tag", "v0.3.0")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", branch)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        create = next(c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"])
        assert "v0.3.1" in " ".join(create), create
        assert "v0.3.1" in r.stdout, r.stdout

    @pytest.mark.slow
    def test_branch_and_key_follow_the_subprocess_date_across_fixture_load(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        control_subprocess_date(tmp_path, env, "2040-12-31")
        assert free(repo, env, "fix-typo", "start").returncode == 0
        branch, key = free_identity(g)
        assert (branch, key) == (
            "t/free-2040-12-31-fix-typo",
            "free-2040-12-31-fix-typo",
        )
        commit_on_free(repo, g)
        add_free_card(env, key)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        env["XP_TEST_TODAY"] = "2041-01-01"
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert marker_file(tmp_path, key).exists()
        assert [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]

    @pytest.mark.slow
    def test_land_names_the_full_diff_when_the_reviewer_changed_the_tree(self, tmp_path):
        """Assent is given by RUNNING land, so the artifact it rests on must be
        addressable HERE — the story leg prints the path, and a stat without one
        tells the lead work happened but not where to read it."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        stub_reviewer(tmp_path, patch=NEW_FILE_PATCH)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr
        assert "the reviewer changed this tree" in r.stdout
        assert f"full diff: {tmp_path}" in r.stdout, r.stdout
        assert f"{key}.round-1.diff" in r.stdout, r.stdout

    def test_land_reports_a_lead_commit_the_round_never_covered(self, tmp_path):
        repo, env, g = reviewed(tmp_path)
        commit_on_free(repo, g, "C = 1\n", "src/late.py", "after the review")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr
        assert "unreviewed" in r.stdout, r.stdout


class TestFreeIsUndocumentedNowhere:
    def test_free_help_names_the_five_actions(self, tmp_path):
        """Constraint 12: a surface a consuming project drives must answer
        --help without doing anything."""
        r = subprocess.run(
            [sys.executable, str(CLOSE), "free", "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert r.returncode == 0
        for action in ("start", "review", "salvage", "land", "post-merge"):
            assert action in r.stdout
