"""Free mode: the shared card lifecycle and distinct patch-release leg.

Every land test here has a twin on the story leg, because free mode's whole
risk is a guard the story leg has and this one lacks (story-011's close note).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from close_free_card_cases import (
    FreeCardCases,
    add_free_card,
    commit_on_free,
    control_subprocess_date,
    free_identity,
)
from close_helpers import (
    CLOSE,
    NEW_FILE_PATCH,
    PLUGIN,
    close,
    free,
    free_repo,
    gh_calls,
    make_repo,
    marker_file,
    stub_reviewer,
)
from spawn_helpers import in_tree, spawn, stub_claude
from spawn_helpers import make_repo as make_spawn_repo


def normalize(refusal: str) -> str:
    masked = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", refusal)
    return re.sub(r"close\.py \S+ \S+ review", "close.py <leg> review", masked).strip()


def reviewed(tmp_path, slug="fix-typo", tiers=()):
    """A free branch with one commit and one clean recorded round."""
    repo, env, g = free_repo(tmp_path)
    if tiers:
        story = f"  story: {tiers[0]}\n" if tiers[0] is not None else ""
        (repo / ".xp" / "config.yml").write_text(
            f"roles:\n  reviewer: claude/opus\ntests:\n{story}  full: {tiers[1]}\n"
        )
        g("commit", "-qam", "configure distinct tiers")
        g("push", "-q", "origin", "main")
    assert free(repo, env, slug, "start").returncode == 0
    _branch, key = free_identity(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    r = free(repo, env, slug, "review")
    assert r.returncode == 0, r.stderr + r.stdout
    return repo, env, g


def carded_free_patch(tmp_path):
    """A carded free branch carrying one lead commit, minted [ready] for spawn."""
    repo, env, g = free_repo(tmp_path)
    config = repo / ".xp" / "config.yml"
    config.write_text(
        config.read_text().replace("roles:\n", "roles:\n  executor: claude/sonnet/medium\n")
    )
    g("add", "-A")
    g("commit", "-qm", "executor role")
    assert free(repo, env, "fix-typo", "start").returncode == 0
    _branch, key = free_identity(g)
    add_free_card(env, key)
    commit_on_free(repo, g)
    assert spawn(repo, env, "ready", key).returncode == 0
    return repo, env, g


class TestFreeStart:
    def test_start_cuts_the_dated_branch_off_the_default_branch(self, tmp_path):
        """AC 1: the branch is dated so two closes of the same slug never share
        a name — and so never share the marker keyed off it."""
        repo, env, g = free_repo(tmp_path)
        main = g("rev-parse", "main").stdout.strip()
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 0, r.stderr
        branch, _key = free_identity(g)
        assert branch.endswith("-fix-typo")
        assert g("rev-parse", branch).stdout.strip() == main

    def test_start_names_the_card_required_before_review(self, tmp_path):
        repo, env, _g = free_repo(tmp_path)
        result = free(repo, env, "fix-typo", "start")
        assert result.returncode == 0 and "card required" in result.stdout

    def test_a_carded_spawn_reuses_the_free_branch_and_lands_from_its_worktree(self, tmp_path):
        repo, env, g = carded_free_patch(tmp_path)
        branch, key = free_identity(g)
        (repo / "lead-left.txt").write_text("mine\n")
        refused = spawn(repo, env, key)
        assert refused.returncode == 2 and "commit your work" in refused.stderr
        assert g("branch", "--show-current").stdout.strip() == branch
        (repo / "lead-left.txt").unlink()
        stub_claude(tmp_path)
        result = spawn(repo, env, key)
        assert result.returncode == 0, result.stderr
        tree = Path(env["XP_DATA"]) / "worktrees" / key
        assert in_tree(tree, env, "branch", "--show-current") == branch
        assert (tree / "src" / "free.py").read_text() == "B = 1\n"
        assert f"at {tree} (continued, not cut)" in result.stdout
        assert "`/free-close` from that worktree" in result.stdout
        assert "close.py story" not in result.stdout
        stub_reviewer(tmp_path)
        review = free(tree, env, "fix-typo", "review")
        assert review.returncode == 0, review.stderr + review.stdout
        land = free(tree, env, "fix-typo", "land")
        assert land.returncode == 0, land.stderr + land.stdout
        create = [call for call in gh_calls(tmp_path) if call[:2] == ["pr", "create"]]
        assert len(create) == 1 and create[0][create[0].index("--base") + 1] == "main"

    def test_spawn_handoff_routes_story_and_free_to_their_skills(self, tmp_path):
        story_root = tmp_path / "story"
        repo, env, _g = make_spawn_repo(story_root, executor="claude/sonnet/medium")
        stub_claude(story_root)
        story = spawn(repo, env, "story-042")
        assert story.returncode == 0, story.stderr

        free_root = tmp_path / "free"
        repo, env, g = carded_free_patch(free_root)
        stub_claude(free_root)
        freed = spawn(repo, env, free_identity(g)[1])
        assert freed.returncode == 0, freed.stderr

        assert story.stdout.endswith("Read it, then run `/story-close`.\n")
        assert freed.stdout.endswith("Read it, then run `/free-close` from that worktree.\n")

    def test_free_start_names_release_timing_without_telling_the_lead_to_commit(self, tmp_path):
        outputs = []
        for name, slug in (("one", "fix-one"), ("two", "fix-two")):
            repo, env, g = free_repo(tmp_path / name)
            result = free(repo, env, slug, "start")
            assert result.returncode == 0, result.stderr
            outputs.append(result.stdout)
            key = free_identity(g)[1]
            assert result.stdout.index(f"spawn.py ready {key}") < result.stdout.index("review")
            assert result.stdout.index("release artifacts") < result.stdout.index("review")
            assert "Commit, then" not in result.stdout
        assert outputs[0] != outputs[1]

    def test_a_spawn_from_off_the_free_branch_names_the_checkout(self, tmp_path):
        """The lead's own checkout is the only thing missing, and `git branch -D`
        is the obvious recovery from a bare already-exists — it discards the
        release commits `free start` left on that branch."""
        repo, env, g = carded_free_patch(tmp_path)
        branch, key = free_identity(g)
        g("checkout", "-q", "main")
        refused = spawn(repo, env, key)
        assert refused.returncode == 2 and f"git checkout {branch}" in refused.stderr
        assert g("rev-parse", "--verify", "-q", branch).returncode == 0

    def test_start_anywhere_but_the_default_branch_refuses_naming_it(self, tmp_path):
        """AC 2: a free branch cut off a story branch carries that story's
        unreleased work into a patch release."""
        repo, env, g = free_repo(tmp_path)
        g("checkout", "-q", "story-042-branch")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2
        assert "main" in r.stderr and "story-042-branch" in r.stderr

    def test_start_refuses_a_dirty_tree(self, tmp_path):
        repo, env, _g = free_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 99\n")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2 and "dirty" in r.stderr

    def test_start_refuses_an_existing_branch(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        branch, _key = free_identity(g)
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2 and branch in r.stderr

    def test_start_refuses_a_slug_that_would_be_truncated(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        before = g("rev-parse", "HEAD").stdout.strip()
        slug = "codex-posture-and-budget"
        r = free(repo, env, slug, "start")
        assert r.returncode == 2
        assert "20" in r.stderr
        assert "t/free-" in r.stderr and "-codex-posture-and-bu" in r.stderr
        assert g("rev-parse", "HEAD").stdout.strip() == before
        assert "codex-posture-and-bu" not in g("branch", "--format=%(refname:short)").stdout

    @pytest.mark.parametrize(
        "slug,tail",
        # 20 chars EXACTLY is the boundary slugify keeps whole, and the cheapest
        # wrong fix (`len(...) >= 20`) refuses it: without this arm the full suite
        # stays green against that off-by-one, because every other free fixture
        # here uses a slug of eight characters or fewer.
        [("Fix Typo.", "fix-typo"), ("a" * 20, "a" * 20)],
    )
    def test_start_accepts_a_fitting_slug(self, tmp_path, slug, tail):
        repo, env, g = free_repo(tmp_path / tail)
        r = free(repo, env, slug, "start")
        assert r.returncode == 0, r.stderr
        assert g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().endswith(f"-{tail}")


class TestFreeCardLifecycle(FreeCardCases):
    pass


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


class TestSharedLandGuards:
    """AC 5. Each guard is fault-injected on BOTH legs and the refusal texts are
    asserted IDENTICAL — the property is one implementation, not two that agree
    today. A grep for the string in free.py would pass a rebuilt copy."""

    def rewrite_history(self, g):
        """The 012b/N2 injection: the recorded round's sha stops being an
        ancestor of HEAD, so it describes a tree that no longer exists."""
        g("commit", "-q", "--amend", "-m", "rewritten")

    def edit_gate_file(self, repo, g):
        (repo / ".xp" / "config.yml").write_text("roles:\n  reviewer: claude/opus\n")
        g("add", "-A")
        g("commit", "-qm", "swap the tier land runs")

    def story_refusal(self, tmp_path, inject):
        repo, env, g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        inject(repo, g)
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        return r.stderr

    def free_refusal(self, tmp_path, inject):
        repo, env, g = reviewed(tmp_path)
        inject(repo, g)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2, r.stdout
        assert not gh_calls(tmp_path), "refused, but the PR was already open"
        return r.stderr

    @pytest.mark.parametrize(
        "inject,marks",
        [
            (lambda repo, g: TestSharedLandGuards().rewrite_history(g), ("does not contain",)),
            (
                lambda repo, g: TestSharedLandGuards().edit_gate_file(repo, g),
                (".xp/config.yml", "gate"),
            ),
        ],
        ids=["ancestor", "gate-file"],
    )
    @pytest.mark.slow
    def test_both_legs_refuse_with_the_same_words(self, tmp_path, inject, marks):
        story = self.story_refusal(tmp_path / "s", inject)
        freed = self.free_refusal(tmp_path / "f", inject)
        for mark in marks:
            assert mark in story, story
            assert mark in freed, freed
        assert "close.py free fix-typo review" in freed, freed
        assert "close.py story story-042 review" in story, story
        # EQUAL, not merely overlapping, modulo the two things that legitimately
        # differ: the sha each fixture produced and the leg's own review command.
        assert normalize(story) == normalize(freed)

    @pytest.mark.parametrize("story,full,expected", [("true", "false", 0), ("false", "true", 2)])
    @pytest.mark.slow
    def test_free_land_runs_the_merged_trees_story_tier(self, tmp_path, story, full, expected):
        repo, env, g = reviewed(tmp_path)
        branch, _key = free_identity(g)
        g("checkout", "-q", "main")
        (repo / ".xp" / "config.yml").write_text(
            f"roles:\n  reviewer: claude/opus\ntests:\n  story: {story}\n  full: {full}\n"
        )
        g("add", "-A")
        g("commit", "-qm", "trunk changes the tiers")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", branch)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == expected, r.stderr
        assert ("test tier red on the tree merged" in r.stderr) is (expected == 2), r.stderr
        assert bool(gh_calls(tmp_path)) is (expected == 0)

    def test_identical_tiers_run_one_gate_and_dry_run_names_it(self, tmp_path):
        gate = tmp_path / "one-shot"
        gate.write_text('#!/bin/sh\ntest ! -e "$0.ran" || exit 1\ntouch "$0.ran"\n')
        gate.chmod(0o755)
        repo, env, _g = reviewed(tmp_path, tiers=(str(gate), str(gate)))
        preview = free(repo, env, "fix-typo", "land", "--dry-run")
        assert f"would run: {gate}" in preview.stdout
        landed = free(repo, env, "fix-typo", "land")
        assert landed.returncode == 0
        assert "tests.story" not in landed.stdout + landed.stderr
        assert gate.with_name("one-shot.ran").exists()

    @pytest.mark.parametrize("tier", [None, "EDIT-ME"], ids=["missing", "unedited"])
    def test_free_release_refuses_a_story_tier_that_cannot_run(self, tmp_path, tier):
        """The dry run answers IDENTICALLY: a preview that lists `gh pr create` for
        a land that refuses describes a release that cannot happen."""
        repo, env, _g = reviewed(tmp_path, tiers=(tier, "true"))
        expected = (
            "refused: tests.story is unset or still EDIT-ME in .xp/config.yml — no test tier"
            " ran. Set tests.story to your suite's command, then retry\n"
        )
        preview = free(repo, env, "fix-typo", "land", "--dry-run")
        assert preview.returncode == 2 and preview.stderr == expected
        assert "gh pr create" not in preview.stdout

        landed = free(repo, env, "fix-typo", "land")
        assert landed.returncode == 2 and landed.stderr == expected
        assert "PATH" not in landed.stderr and not gh_calls(tmp_path)

    def test_land_refuses_on_overlap_with_trunk(self, tmp_path):
        """The third shared guard: trunk touched a file this branch touched and
        no review covered the two together."""
        repo, env, g = reviewed(tmp_path)
        branch, _key = free_identity(g)
        g("checkout", "-q", "main")
        commit_on_free(repo, g, "B = 2\n", "src/free.py", "trunk touched it too")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", branch)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2
        assert "src/free.py" in r.stderr and "no review covered" in r.stderr
        assert not gh_calls(tmp_path)


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
