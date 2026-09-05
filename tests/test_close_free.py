"""Free mode: start, the shared card lifecycle, and the land guards it shares
with the story leg. The patch-release leg is test_close_free_release.py.

Every land test here has a twin on the story leg, because free mode's whole
risk is a guard the story leg has and this one lacks (story-011's close note).
"""

import re
from pathlib import Path

import pytest
from close_free_card_cases import (
    FreeCardCases,
    add_free_card,
    commit_on_free,
    free_identity,
)
from close_helpers import (
    close,
    free,
    free_repo,
    gh_calls,
    make_repo,
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
    # NO refresh receipt: the free lane is exempt, and a fixture that seeds one
    # stops walking that exemption (constraint 12)
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
        """The printed next action is RUN, not just named (constraint 12): the
        card refresh story-103 put in front of the mint has no free lane, so
        `spawn.py ready <key>` refuses here unless the exemption is the lane's."""
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
            add_free_card(env, key)
            commit_on_free(repo, g)
            minted = spawn(repo, env, "ready", key)
            assert minted.returncode == 0, minted.stderr
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
