"""Free mode: the card-less branch, its review, and the release it opens.

Every land test here has a twin on the story leg, because free mode's whole
risk is a guard the story leg has and this one lacks (story-011's close note).
"""

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from close_helpers import (
    CLOSE,
    CONFIG_PATCH,
    NEW_FILE_PATCH,
    close,
    free,
    free_repo,
    gh_calls,
    make_repo,
    marker_file,
    stub_reviewer,
)
from spawn_helpers import in_tree, spawn, stub_claude

TODAY = datetime.date.today().isoformat()
BRANCH = f"t/free-{TODAY}-fix-typo"
KEY = f"free-{TODAY}-fix-typo"


def normalize(refusal: str) -> str:
    masked = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", refusal)
    return re.sub(r"close\.py \S+ \S+ review", "close.py <leg> review", masked).strip()


def commit_on_free(repo, g, text="B = 1\n", path="src/free.py", msg="free work"):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    g("add", "-A")
    g("commit", "-qm", msg)


def reviewed(tmp_path, slug="fix-typo"):
    """A free branch with one commit and one clean recorded round."""
    repo, env, g = free_repo(tmp_path)
    assert free(repo, env, slug, "start").returncode == 0
    commit_on_free(repo, g)
    r = free(repo, env, slug, "review")
    assert r.returncode == 0, r.stderr + r.stdout
    return repo, env, g


def add_free_card(env, verify="true"):
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(
        plan.read_text()
        + f"\n### Free\n#### {KEY} — fix typo   [planned]\n"
        + f"Context: small release.\nVerify: {verify}\n"
    )


def carded_free_patch(tmp_path):
    """A carded free branch carrying one lead commit, minted [ready] for spawn."""
    repo, env, g = free_repo(tmp_path)
    config = repo / ".xp" / "config.yml"
    config.write_text(
        config.read_text().replace("roles:\n", "roles:\n  executor: claude/sonnet/medium\n")
    )
    g("add", "-A")
    g("commit", "-qm", "executor role")
    add_free_card(env)
    assert free(repo, env, "fix-typo", "start").returncode == 0
    commit_on_free(repo, g)
    assert spawn(repo, env, "ready", KEY).returncode == 0
    return repo, env, g


class TestFreeStart:
    def test_start_cuts_the_dated_branch_off_the_default_branch(self, tmp_path):
        """AC 1: the branch is dated so two closes of the same slug never share
        a name — and so never share the marker keyed off it."""
        repo, env, g = free_repo(tmp_path)
        main = g("rev-parse", "main").stdout.strip()
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 0, r.stderr
        assert g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == BRANCH
        assert g("rev-parse", BRANCH).stdout.strip() == main

    def test_start_names_the_card_already_in_the_plan(self, tmp_path):
        repo, env, _g = free_repo(tmp_path)
        add_free_card(env)
        result = free(repo, env, "fix-typo", "start")
        assert result.returncode == 0
        assert "card in the plan" in result.stdout and "no card" not in result.stdout

    def test_start_still_names_the_designed_cardless_mode(self, tmp_path):
        repo, env, _g = free_repo(tmp_path)
        result = free(repo, env, "fix-typo", "start")
        assert result.returncode == 0 and "no card" in result.stdout

    def test_a_carded_spawn_reuses_the_free_branch_and_its_commits(self, tmp_path):
        repo, env, g = carded_free_patch(tmp_path)
        (repo / "lead-left.txt").write_text("mine\n")
        refused = spawn(repo, env, KEY)
        assert refused.returncode == 2 and "commit your work" in refused.stderr
        assert g("branch", "--show-current").stdout.strip() == BRANCH
        (repo / "lead-left.txt").unlink()
        stub_claude(tmp_path)
        result = spawn(repo, env, KEY)
        assert result.returncode == 0, result.stderr
        tree = Path(env["XP_DATA"]) / "worktrees" / KEY
        assert in_tree(tree, env, "branch", "--show-current") == BRANCH
        assert (tree / "src" / "free.py").read_text() == "B = 1\n"
        assert f"at {tree} (continued, not cut)" in result.stdout
        assert "`close.py free fix-typo review` from that worktree" in result.stdout
        assert "close.py story" not in result.stdout

    def test_a_spawn_from_off_the_free_branch_names_the_checkout(self, tmp_path):
        """The lead's own checkout is the only thing missing, and `git branch -D`
        is the obvious recovery from a bare already-exists — it discards the
        release commits `free start` left on that branch."""
        repo, env, g = carded_free_patch(tmp_path)
        g("checkout", "-q", "main")
        refused = spawn(repo, env, KEY)
        assert refused.returncode == 2 and f"git checkout {BRANCH}" in refused.stderr
        assert g("rev-parse", "--verify", "-q", BRANCH).returncode == 0

    def test_a_carded_in_place_spawn_keeps_the_free_branch(self, tmp_path):
        repo, env, g = carded_free_patch(tmp_path)
        result = spawn(repo, env, KEY, "--in-place")
        assert result.returncode == 0, result.stderr
        assert g("branch", "--show-current").stdout.strip() == BRANCH
        assert (repo / "src" / "free.py").read_text() == "B = 1\n"

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
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2 and BRANCH in r.stderr

    def test_start_refuses_a_slug_that_would_be_truncated(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        before = g("rev-parse", "HEAD").stdout.strip()
        slug = "codex-posture-and-budget"
        r = free(repo, env, slug, "start")
        assert r.returncode == 2
        assert "20" in r.stderr
        assert f"t/free-{TODAY}-codex-posture-and-bu" in r.stderr
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


class TestFreeReview:
    def test_a_dirty_refusal_does_not_advance_an_optional_card(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        add_free_card(env)
        (repo / "dirty.py").write_text("dirty = True\n")
        result = free(repo, env, "fix-typo", "review")
        assert result.returncode == 2 and "dirty" in result.stderr
        assert "[planned]" in (Path(env["XP_DATA"]) / "plan.md").read_text()

    def test_a_free_card_is_reviewed_minted_and_its_edit_reaches_shared_drift(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        add_free_card(env)
        reviewed = free(repo, env, "fix-typo", "review")
        assert reviewed.returncode == 0, reviewed.stderr
        from close_helpers import launches

        assert "#### free-" in launches(tmp_path)[-1]["stdin"]
        plan = (Path(env["XP_DATA"]) / "plan.md").read_text()
        assert "[in-progress]" in plan
        assert (Path(env["XP_DATA"]) / "markers" / f"{KEY}.ready.json").exists()
        (Path(env["XP_DATA"]) / "plan.md").write_text(plan.replace("Verify: true", "Verify: false"))
        landed = free(repo, env, "fix-typo", "land")
        assert landed.returncode == 2
        assert "edited after its plan review" in landed.stderr
        assert "--- reviewed" in landed.stderr and "+++ now" in landed.stderr
        plan_path = Path(env["XP_DATA"]) / "plan.md"
        plan_path.write_text(plan_path.read_text().replace("[in-progress]", "[planned]"))
        # story-036: the re-minted card's Verify is RUN by the review leg, so the
        # red lands there rather than at the merge it would otherwise have reached
        verified = free(repo, env, "fix-typo", "review")
        assert verified.returncode == 2 and "Verify red" in verified.stderr

    def test_a_deleted_free_card_cannot_drop_the_credential_it_minted(self, tmp_path):
        """A free card is OPTIONAL, so a missing one reads as a card-less close —
        but THIS one was minted and handed to the reviewer, and deleting it
        between the two legs would silently drop its Verify and its digest. The
        ready marker is what says a card was there to begin with."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        add_free_card(env)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().split(f"#### {KEY} ")[0])
        result = free(repo, env, "fix-typo", "land")
        assert result.returncode == 2 and KEY in result.stderr
        assert not [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]

    def test_cardless_notice_varies_with_the_diff_and_reaches_stderr(self, tmp_path):
        notices = []
        for name, text in (("one", "B = 1\n"), ("two", "B = 1\nC = 2\n")):
            repo, env, g = free_repo(tmp_path / name)
            free(repo, env, "fix-typo", "start")
            commit_on_free(repo, g, text=text)
            result = free(repo, env, "fix-typo", "review")
            assert result.returncode == 0, result.stderr
            notices.append(
                next(ln for ln in result.stderr.splitlines() if ln.startswith("warning: card-less"))
            )
        assert notices[0] != notices[1]

    def test_the_bundle_carries_no_story_card(self, tmp_path):
        """AC 1: card-less is the point — the bundle must SAY there is no card,
        not omit the section and let the reviewer invent a scope."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        r = free(repo, env, "fix-typo", "review")
        assert r.returncode == 0, r.stderr
        from close_helpers import launches

        bundle = launches(tmp_path)[-1]["stdin"]
        assert "#### story-042" not in bundle, "a free bundle carried a story card"
        assert "free branch" in bundle
        assert "B = 1" in bundle, "the bundle carried no diff"

    def test_a_reviewer_that_edits_a_gate_file_is_refused(self, tmp_path):
        """No card means no `Files:` line, so the shared `.xp/` scope in
        check_reviewer_motion admits nothing at all. Fault-injected: the stub
        commits a config edit as the reviewer."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        stub_reviewer(tmp_path, patch=CONFIG_PATCH)
        r = free(repo, env, "fix-typo", "review")
        assert r.returncode == 2, r.stdout
        assert ".xp/config.yml" in r.stderr and "Files line" in r.stderr


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
        repo, env, _g = reviewed(tmp_path)
        path = marker_file(tmp_path, KEY)
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
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and BRANCH in r.stderr
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
        g("checkout", "-q", "main")
        (repo / "sprint.md").write_text("shipped\n")
        g("add", "-A")
        g("commit", "-qm", "sprint 5 released")
        g("tag", "v0.3.0")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", BRANCH)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        create = next(c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"])
        assert "v0.3.1" in " ".join(create), create
        assert "v0.3.1" in r.stdout, r.stdout

    @pytest.mark.slow
    def test_a_branch_cut_yesterday_still_lands_today(self, tmp_path):
        """The key is read off HEAD, never recomputed from today's date: a free
        close that spans midnight would otherwise lose the round it recorded."""
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        g("branch", "-m", f"t/free-{yesterday}-fix-typo")
        commit_on_free(repo, g)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]

    @pytest.mark.slow
    def test_land_names_the_full_diff_when_the_reviewer_changed_the_tree(self, tmp_path):
        """Assent is given by RUNNING land, so the artifact it rests on must be
        addressable HERE — the story leg prints the path, and a stat without one
        tells the lead work happened but not where to read it."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        stub_reviewer(tmp_path, patch=NEW_FILE_PATCH)
        assert free(repo, env, "fix-typo", "review").returncode == 0
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr
        assert "the reviewer changed this tree" in r.stdout
        assert f"full diff: {tmp_path}" in r.stdout, r.stdout
        assert f"{KEY}.round-1.diff" in r.stdout, r.stdout

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

    @pytest.mark.slow
    def test_the_tier_that_gates_is_the_one_the_merged_tree_declares(self, tmp_path):
        """The other half of the gate-file threat: a tier arriving on TRUNK is
        invisible to a shown..HEAD guard, and land read its command string
        before the trial merge — so the merge ran the tier it replaced."""
        repo, env, g = reviewed(tmp_path)
        g("checkout", "-q", "main")
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:\n  story: true\n  full: false\n"
        )
        g("add", "-A")
        g("commit", "-qm", "trunk tightens the release tier")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", BRANCH)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2, "ran the tier trunk replaced, and opened the PR"
        assert "tier red" in r.stderr, r.stderr
        assert not gh_calls(tmp_path)

    def test_land_refuses_on_overlap_with_trunk(self, tmp_path):
        """The third shared guard: trunk touched a file this branch touched and
        no review covered the two together."""
        repo, env, g = reviewed(tmp_path)
        g("checkout", "-q", "main")
        commit_on_free(repo, g, "B = 2\n", "src/free.py", "trunk touched it too")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", BRANCH)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2
        assert "src/free.py" in r.stderr and "no review covered" in r.stderr
        assert not gh_calls(tmp_path)


class TestFreeIsUndocumentedNowhere:
    def test_free_help_names_the_four_actions(self, tmp_path):
        """Constraint 12: a surface a consuming project drives must answer
        --help without doing anything."""
        r = subprocess.run(
            [sys.executable, str(CLOSE), "free", "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert r.returncode == 0
        for action in ("start", "review", "land", "post-merge"):
            assert action in r.stdout
