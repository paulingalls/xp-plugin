"""story-002 + successors: the story-close pipeline's start and review legs.
Verify: pytest -q tests/test_close.py"""

import subprocess
import sys

import pytest
from close_helpers import (  # noqa: F401
    CARD,
    CLOSE,
    CONFIG,
    FIX_PATCH,
    PLUGIN,
    REVIEWER_NAME,
    SPAWN,
    WORK,
    close,
    close_bare,
    launches,
    make_repo,
    marker,
    marker_file,
    mint_ready,
    prose,
    stub_reviewer,
)


class TestStart:
    def test_dirty_tree_refused_naming_reason(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 3\n")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()

    def test_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="ready")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "in-progress" in r.stderr

    def test_a_card_ends_at_the_next_heading_of_any_level(self):
        """A card followed by a `### Sprint N` heading swallowed that sprint's
        whole preamble — story-017's card carried 55 lines of Sprint 4 planning
        prose, inlined at spawn as 'the whole scope' and charged against the
        teammate budget (bug 9ad0180b)."""
        sys.path.insert(0, str(CLOSE.parent))
        from close import story_card

        plan = CARD.format(status="ready", verify="true") + "\n### Sprint 2\nNEXT-SPRINT-PREAMBLE\n"
        card, status = story_card(plan, "story-042")
        assert status == "ready"
        assert "Verify: true" in card
        assert "NEXT-SPRINT-PREAMBLE" not in card, "the card swallowed the next section"

    def test_the_story_bundle_diffs_against_the_INTEGRATION_TARGET(self, tmp_path):
        """Bug 66272ab4: /story-close bundled `main...HEAD`, so under
        `release: sprint` every earlier story already integrated on the sprint
        branch rode into this story's review. Its filed falsifier greps SKILL.md
        for the absence of a token, which constraint 11 forbids — it greens on a
        rewording while the defect returns.

        The earlier story lives on the SPRINT BRANCH ONLY, never on main: that is
        what makes the two bases differ, and a first version of this test put it
        on both and passed against the injected bug."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-qb", "sprint-001", "main")
        (repo / "earlier_story.py").write_text("EARLIER_STORY_SENTINEL = 1\n")
        (repo / ".xp" / "config.yml").write_text(
            CONFIG + "\nrelease: sprint\nsprint_branch: sprint-001\n"
        )
        g("add", "-A")
        g("commit", "-qm", "an earlier story, integrated on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        g("merge", "-q", "--no-edit", "sprint-001")
        assert close(repo, env, "review").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "EARLIER_STORY_SENTINEL" not in bundle, (
            "the bundle diffed against the default branch, so an already-integrated"
            " story rode into this story's review"
        )

    def test_bundle_inlines_rules_diff_card_and_work_entries(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        subprocess.run(
            [sys.executable, str(WORK), "note", "filed-during-story"],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        bundle = launches(tmp_path)[0]["stdin"]  # the bundle is the reviewer's prompt now
        for sentinel in (
            "Communication",  # VALUES now come from the plugin root, not the repo
            "CONSTRAINT-SENTINEL",
            "SYSTEM-SENTINEL",
            "A = 2",
            "demo story",
            "filed-during-story",
        ):
            assert sentinel in bundle, f"bundle missing {sentinel}"


class TestReviewed:
    def test_verdict_flag_is_gone_so_no_verdict_can_be_hand_supplied(self, tmp_path):
        """AC 1: a lead-supplied verdict is the forgeable-verdict gap this story closes."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "unrecognized arguments: --verdict" in r.stderr

    def test_red_verify_aborts_before_merge_naming_command(self, tmp_path):
        """story-036 moved the first red one leg earlier: the REVIEW leg runs the
        card's Verify now, so a red tree never reaches a recorded round and land
        is never reached. land keeps its own copy — test_close_verify.py holds
        that half, which is what stops this becoming the only assertion."""
        repo, env, g = make_repo(tmp_path, verify="false")
        r = close(repo, env, "review")
        assert r.returncode != 0 and "false" in (r.stderr + r.stdout)
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge

    def test_green_close_merges_with_verdict_and_flips_status(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        body = g("log", "main", "-1", "--format=%B").stdout
        assert "Review round 1" in body
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()

    def test_conflicting_main_aborts_back_to_reviewing(self, tmp_path):
        """A conflict is a same-file property, so a conflicting trunk is an OVERLAP
        by construction and the overlap refusal is what fires — the reason land can
        stop refusing on motion without letting conflicts through silently."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "conflicting")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "src/thing.py" in r.stderr
        # its own remediation is where the conflict surfaces: on the story branch, in
        # the lead's working tree, before any review is spent on it
        assert g("merge", "main").returncode != 0
        g("merge", "--abort")
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_pr_mode_dry_run_pins_gh_args(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
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
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "gh pr create" in r.stdout and "Review round 1" in r.stdout
        merge_lines = [ln for ln in r.stdout.splitlines() if "gh pr merge" in ln]
        assert len(merge_lines) == 1
        assert "--merge" in merge_lines[0] and "--delete-branch" in merge_lines[0]
        assert "Review round 1" in merge_lines[0]  # rounds ride the merge, not only create
        assert any(ln.startswith("git push") for ln in r.stdout.splitlines())

    def test_reviewed_dirty_tree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "fixed.txt").write_text("untracked dirt\n")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_story_tier_runs_after_verify(self, tmp_path):
        repo, env, g = make_repo(tmp_path)  # card Verify is green (true)
        (repo / ".xp" / "config.yml").write_text(CONFIG.replace("story: true", "story: false"))
        g("add", "-A")
        g("commit", "-qm", "red story tier")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_land_without_review_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "land")
        assert r.returncode == 2 and "review" in r.stderr
        assert "Traceback" not in r.stderr

    def test_unknown_story_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-999", "review", "--merge-mode", "local"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "story-999" in r.stderr
        assert "Traceback" not in r.stderr


class TestSecondReviewRound:
    """Findings from /code-review on the story-002 diff."""

    def test_the_flip_preserves_a_sibling_lane_edit_made_DURING_land(self, tmp_path):
        """Was "post-merge flip preserves MAIN-SIDE changes": the flip was written
        after the merge so trunk's plan edits survived it. Nothing merges the plan
        now — it is one file shared by every lane — so the surviving claim is that
        an edit landing DURING land is still there after it.

        The window is what makes this a check. cmd_land snapshots the plan to read
        the card, then runs Verify and the tier for minutes, then flips; an edit
        made before land ever starts is already IN that snapshot, so writing the
        snapshot back would keep it and the test would certify. The sibling write
        therefore rides the card's own Verify command, which is the one hook that
        fires inside the window. Fault-injected: land flipping the SNAPSHOT it
        read the card from, rather than what flip_card re-reads under the lock,
        reds this and test_a_flip_that_matched_nothing_is_reported_not_swallowed
        — the same window from the other side — and nothing else.

        printf SUBSTITUTES the story id rather than spelling it: the Verify line
        is itself a line of the plan, so an assertion on a string the command
        contains verbatim passes whether or not the append ever ran."""
        sibling = "#### %s — sibling lane   [done]\\nVerify: true\\n"
        repo, env, _g = make_repo(
            tmp_path, verify=f"printf '{sibling}' story-043 >> \"$XP_DATA/plan.md\""
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        merged = (tmp_path / "data" / "plan.md").read_text()
        assert "#### story-043 — sibling lane   [done]" in merged  # the sibling edit survives
        assert "#### story-042 — demo story   [done]" in merged

    def test_local_dry_run_performs_no_mutation(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge happened
        r2 = close(repo, env, "land")
        assert r2.returncode == 0, "marker must survive a dry-run"

    def test_close_on_default_branch_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "story-042-branch")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "main" in r.stderr

    def test_missing_verify_line_refused_at_the_mint(self, tmp_path):
        """The refusal moved EARLIER (bug abc052f2): an unverifiable card is now
        stopped by the credential mint, before a teammate is spawned, rather than
        at land after the story is written. mint_ready is what reds here."""
        import subprocess
        import sys

        repo, env, _g = make_repo(tmp_path, status="planned")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true\n", ""))
        r = subprocess.run(
            [sys.executable, str(SPAWN), "ready", "story-042"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "verify" in r.stderr.lower(), r.stderr

    def test_master_default_branch_supported(self, tmp_path):
        repo, env, g = make_repo(tmp_path, branch="master")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "master", "-1", "--format=%B").stdout


class TestOverlapNotMotion:
    """story-018: a review covers the STORY's own changes. Trunk motion costs a
    round only where the two diffs touch the same files — which is also the only
    detector we have for the standing practice that parallel stories are
    file-disjoint (DESIGN §11's collision check was never built)."""

    def trunk_lands(self, repo, g, *files):
        g("checkout", "-q", "main")
        for path in files:
            (repo / path).write_text("LANDED_BY_ANOTHER_STORY = 1\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on trunk")
        g("checkout", "-q", "story-042-branch")

    def fixing_reviewer(self, tmp_path):
        stub_reviewer(tmp_path, result="fixed one thing", patch=FIX_PATCH)

    def test_disjoint_trunk_motion_lands_without_a_new_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        self.trunk_lands(repo, g, "unrelated.py")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert len(launches(tmp_path)) == 1, "disjoint motion bought a second round"
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()

    def test_overlapping_trunk_motion_refuses_naming_every_overlapping_file(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / "src" / "shared.py").write_text("C = 2\n")
        g("add", "-A")
        g("commit", "-qm", "the story touches a second file")
        assert close(repo, env, "review").returncode == 0
        # one disjoint file alongside the two overlapping ones: a refusal that
        # names the whole trunk delta is not a collision detector
        self.trunk_lands(repo, g, "src/thing.py", "src/shared.py", "unrelated.py")
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert "src/thing.py" in r.stderr and "src/shared.py" in r.stderr
        assert "unrelated.py" not in r.stderr, "the disjoint file was named as a collision"
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_the_merged_tree_is_EXECUTED_when_trunk_is_ahead(self, tmp_path):
        """The half the old motion refusal paid for without naming: it forced
        `git merge <trunk>` onto the story branch, so Verify and the tier ran on an
        integrated tree. Under overlap-not-motion nothing would — story-014's own
        shape (A changes a signature, B adds a call site elsewhere) merges clean,
        breaks the product, and no review reliably sees a call-graph break.

        The trunk file is DISJOINT on purpose: with an overlapping one the collision
        refusal fires first and this test greens with the trial merge deleted.
        """
        repo, env, g = make_repo(tmp_path, verify="! ls probe.py")
        assert close(repo, env, "review").returncode == 0
        tip = g("rev-parse", "HEAD").stdout.strip()
        self.trunk_lands(repo, g, "probe.py")
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert "merged with refs/heads/main" in r.stderr, r.stderr
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()
        assert g("status", "--porcelain").stdout == "", "the trial merge was left staged"
        assert g("rev-parse", "HEAD").stdout.strip() == tip, "the trial merge committed"

    def test_a_reviewer_range_and_a_lead_range_are_never_one_range(self, tmp_path):
        """655208fe: land printed reviewed_head..HEAD under the reviewer's name. Once
        a lead commit may follow the review, that attributes the lead's own work to
        the reviewer and names a round diff that was never written."""
        repo, env, g = make_repo(tmp_path)
        self.fixing_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 4\n")
        g("add", "-A")
        g("commit", "-qm", "LEAD-FIX-AFTER-REVIEW")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        reviewer_part, _, lead_part = r.stdout.partition("merging unreviewed")
        assert lead_part, "the lead's commits were not presented at all"
        assert "reviewer patch" in reviewer_part and "LEAD-FIX-AFTER-REVIEW" in lead_part
        assert "LEAD-FIX-AFTER-REVIEW" not in reviewer_part, (
            "the lead's commit read as the reviewer's"
        )

    def test_a_rename_of_a_file_trunk_also_edits_is_an_overlap(self, tmp_path):
        """`git diff --name-only` detects renames and prints only the NEW path, so a
        story that renames the module another story is editing read as DISJOINT. The
        trial merge is no backstop: ort follows the rename and merges it clean and
        silent — two stories sharing a file domain, which is the one thing this
        refusal exists to see."""
        repo, env, g = make_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 1\nB = 1\nC = 1\nD = 1\nE = 1\nF = 1\n")
        g("add", "-A")
        g("commit", "-qm", "a file wide enough for two stories to edit different lines")
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "story-042-branch")
        g("checkout", "-q", "story-042-branch")
        g("mv", "src/thing.py", "src/renamed.py")
        renamed = repo / "src" / "renamed.py"
        renamed.write_text(renamed.read_text().replace("A = 1", "A = 2"))
        g("add", "-A")
        g("commit", "-qm", "the story renames the module it owns")
        assert close(repo, env, "review").returncode == 0
        thing = repo / "src" / "thing.py"
        g("checkout", "-q", "main")
        thing.write_text(thing.read_text().replace("F = 1", "F = 99"))
        g("add", "-A")
        g("commit", "-qm", "another story edits the same module, under its old name")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert "src/thing.py" in r.stderr
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_a_trial_merge_that_conflicts_refuses_and_leaves_the_tree_clean(self, tmp_path):
        """f7dfec27's other half: with land no longer refusing on motion, the trial
        merge is what makes a conflict abort reachable at all. A file/directory
        collision is the shape overlap cannot pair up — the names differ."""
        repo, env, g = make_repo(tmp_path)
        (repo / "probe").write_text("the story adds a FILE\n")
        g("add", "-A")
        g("commit", "-qm", "the story adds a file named probe")
        assert close(repo, env, "review").returncode == 0
        g("checkout", "-q", "main")
        (repo / "probe").mkdir()
        (repo / "probe" / "x.py").write_text("x = 1\n")
        g("add", "-A")
        g("commit", "-qm", "another story adds a DIRECTORY named probe")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "conflicts" in r.stderr, r.stderr
        assert g("status", "--porcelain").stdout == "", "a refused trial merge stayed staged"
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_dropping_the_reviewers_commits_is_not_reported_as_merging_them(self, tmp_path):
        """The other half of what the deleted HEAD==shown_sha refusal guaranteed. It
        is not only that HEAD may move AHEAD: a lead who rejects the fixes takes the
        `git reset --hard` review.py itself offers, and then land printed the dropped
        commits under "you are merging its work" while merging none of them."""
        repo, env, g = make_repo(tmp_path)
        self.fixing_reviewer(tmp_path)
        pre = g("rev-parse", "HEAD").stdout.strip()
        assert close(repo, env, "review").returncode == 0
        g("reset", "-q", "--hard", pre)
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert "reviewer patch" not in r.stdout, "land claimed to merge commits it dropped"
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()


class TestDuplicateStoryIds:
    """Bug 6e20a525, found on the fresh-repo setup walk: the scaffold skeleton
    shipped as story-001, a user's first real card collided, and the readers
    disagreed in silence — story_card returned the first card while flip_status
    rewrote the last bracket, so spawn ran one card's Executor and flipped the
    other. One guard in story_card covers every reader that acts on a card BODY
    (the heading-only scans double an id visibly; they cannot pick a wrong card);
    the skeleton is story-000 now so the natural first id no longer collides."""

    def test_a_duplicated_id_refuses_instead_of_picking_a_card(self):
        from close import story_card

        plan = (
            "#### story-001 — a   [ready]\nExecutor: x/y\n\n"
            "#### story-001 — b   [ready]\nExecutor: (default)\n"
        )
        with pytest.raises(KeyError, match="more than once"):
            story_card(plan, "story-001")

    def test_a_prefix_shared_id_is_not_a_duplicate(self):
        from close import story_card

        plan = "#### story-1 — a   [ready]\nx\n\n#### story-10 — b   [ready]\ny\n"
        card, _status = story_card(plan, "story-1")
        assert "story-10" not in card

    def test_the_template_skeleton_cannot_collide_with_the_natural_first_id(self):
        """Constructed against the real parser, not grepped: `"#### story-001" not
        in template` reds on a skeleton named story-0010, which collides with
        nothing (measured)."""
        from close import story_card

        seeded = (PLUGIN / "templates" / "plan.md").read_text()
        card, status = story_card(seeded + "#### story-001 — first real   [planned]\n", "story-001")
        assert status == "planned" and "story-000" not in card
