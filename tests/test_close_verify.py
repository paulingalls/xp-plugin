"""The Verify: line's gates — the credential mint and land, one rule at two depths.

Its own file rather than more of test_close_land.py, which stood at the 500-line
cap (constraint 8: extract, never trim a test to fit).
"""

import json
import pathlib

import pytest
from close import story_card
from close_helpers import (
    CLEAN,
    FIX_PATCH,
    close,
    launches,
    make_repo,
    marker,
    marker_file,
    ready_marker,
    stub_reviewer,
)


class TestVerifyGate:
    def test_an_empty_verify_line_is_not_reported_as_a_missing_one(self, tmp_path):
        """Field report (Legacy): a card authored as `Verify:` with its commands
        bulleted below parses EMPTY, and land refused with "has no Verify: line"
        about a card that visibly has one — the absent-vs-present-but-unreadable
        conflation, third instance after the bootstrap label and system.md.

        The credential is RE-MINTED onto the edited text rather than the card being
        edited under it, because the drift guard fires first otherwise. That also
        models the only way this reaches land once mint refuses it: a card minted
        by a version that had no such guard.
        """
        from work import card_digest

        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        original = plan.read_text()

        def recredential(text):
            plan.write_text(text)
            card = story_card(text, "story-042")[0]
            ready_marker(tmp_path).write_text(
                json.dumps({"digest": card_digest(card), "card": card})
            )

        recredential(original.replace("Verify: true", "Verify:\n- `pytest -q`\n- `bun test`"))
        empty = close(repo, env, "land")
        assert empty.returncode != 0
        assert "same line" in empty.stderr.lower(), empty.stderr

        recredential(original.replace("Verify: true\n", ""))
        absent = close(repo, env, "land")
        assert absent.returncode != 0
        assert "no Verify:" in absent.stderr, absent.stderr
        assert "same line" not in absent.stderr.lower(), absent.stderr

    @pytest.mark.parametrize("substitution", ["`touch {path}`", "$(touch {path})"])
    def test_command_substitution_is_refused_before_review_and_land(self, tmp_path, substitution):
        from work import card_digest

        def rewrite_card(root, sentinel):
            plan = root / "data" / "plan.md"
            text = plan.read_text().replace(
                "Verify: true", f"Verify: {substitution.format(path=sentinel)}"
            )
            plan.write_text(text)
            card = story_card(text, "story-042")[0]
            ready_marker(root).write_text(json.dumps({"digest": card_digest(card), "card": card}))

        review_root = tmp_path / "review"
        review_root.mkdir()
        sentinel = review_root / "substituted"
        repo, env, _g = make_repo(review_root)
        rewrite_card(review_root, sentinel)
        refused = close(repo, env, "review")
        assert refused.returncode == 2 and "command substitution" in refused.stderr
        assert "remove" in refused.stderr.lower() and not sentinel.exists()
        assert launches(review_root) == [], "spent a reviewer on a refused Verify"

        land_root = tmp_path / "land"
        land_root.mkdir()
        sentinel = land_root / "substituted"
        repo, env, _g = make_repo(land_root)
        assert close(repo, env, "review").returncode == 0
        rewrite_card(land_root, sentinel)
        refused = close(repo, env, "land")
        assert refused.returncode == 2 and "command substitution" in refused.stderr
        assert not sentinel.exists(), "land substituted the refused Verify"

    def test_verify_keeps_both_commands_in_an_and_chain(self, tmp_path):
        """A chain through a MOVE, not two touches: reading the same line as one
        ARGV — the change most likely to retire chaining — still creates both
        names, because touch takes many operands, so `touch a && touch b` greens
        against exactly the regression this test exists to catch. Only two
        commands run in order leave the source gone and the target there."""
        first, second = tmp_path / "first", tmp_path / "second"
        repo, env, _g = make_repo(tmp_path, verify=f"touch {first} && mv {first} {second}")
        assert close(repo, env, "review").returncode == 0
        assert second.exists() and not first.exists()
        second.unlink()
        assert close(repo, env, "land").returncode == 0
        assert second.exists() and not first.exists()


class TestIncompletePlanReviewReachesTheLead:
    """plan_review.py leaves a marker when its review produced no findings; the
    close leg is where the lead and the story reviewer both meet it.

    Measured twice in the field, both invisible from here: a codex teammate whose
    review was killed at the model's own timeout guess, and a claude teammate that
    backgrounded the review and then YIELDED — headless `-p` ends on yield, so the
    review died with its parent. The second was caught only because that teammate
    happened to leave work uncommitted; committing first would have handed back a
    story whose mandatory gate never ran, with nothing to say so.
    """

    def marker(self, env):
        p = pathlib.Path(env["XP_DATA"]) / "markers" / "story-042.plan-review-incomplete"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def test_the_lead_and_the_reviewer_are_both_told(self, tmp_path):
        from close_helpers import launches, stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        self.marker(env).write_text("story-042: plan review started against /d/draft.md")
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "plan review" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
        bundle = launches(tmp_path)[0]["stdin"]
        assert "plan review" in bundle.lower(), bundle[:600]

    def test_a_story_whose_review_completed_says_nothing(self, tmp_path):
        """An always-present line is wallpaper (constraint 3): the silence is the
        assertion, so it is tested positively."""
        from close_helpers import launches, stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "did not complete" not in (r.stdout + r.stderr).lower()
        assert "did not complete" not in launches(tmp_path)[0]["stdin"].lower()


class TestTheRoundIsRecordedOnlyIfVerifyRan:
    """story-036. `blocking: []` is today the reviewer's OWN judgment that Verify
    ran, and a reviewer whose sandbox cannot reach a leg reports green in good
    faith — note 1b45d1c7 measured four rounds of bun+tsc green with the native
    build dead. The pipeline already knows how: land computes verify_commands and
    runs it, so the same call at REVIEW time turns the claim into a fact.
    """

    def test_a_green_report_on_a_red_tree_is_refused(self, tmp_path):
        """AC 1: the whole card. The reviewer is CLEAN and the tree is red."""
        from close_helpers import marker_file

        repo, env, _g = make_repo(tmp_path, verify="false")
        r = close(repo, env, "review")
        assert r.returncode != 0, r.stdout
        assert "Verify red" in r.stderr, r.stderr
        assert not marker_file(tmp_path).exists(), "a refused round was recorded anyway"

    def test_a_verify_that_cannot_run_is_not_a_verify_that_failed(self, tmp_path):
        """AC 2: the lead's next action differs — one is a code fix, the other is
        a harness or posture problem, and the shell's own 127 is the difference."""
        repo, env, _g = make_repo(tmp_path, verify="xp-no-such-command-036")
        r = close(repo, env, "review")
        assert r.returncode != 0, r.stdout
        assert "could not be RUN" in r.stderr, r.stderr
        assert "Verify red" not in r.stderr, r.stderr

    def test_a_refused_round_says_so_in_the_file_a_reader_opens(self, tmp_path):
        """AC 3: close.py keeps a refused round's report on purpose — its findings
        exist nowhere else — and the file then reads `blocking: []` whether the
        round was accepted or thrown away. Asserted by READING the report, never
        by a sibling marker."""
        repo, env, _g = make_repo(tmp_path, verify="false")
        assert close(repo, env, "review").returncode != 0
        (report,) = (tmp_path / "data" / "reports").glob("*.json")
        recorded = json.loads(report.read_text())
        assert "Verify red" in recorded["refused"], recorded
        assert next(iter(recorded)) == "refused", "the refusal must be the first key read"

    def test_an_accepted_report_is_left_exactly_as_the_reviewer_wrote_it(self, tmp_path):
        """AC 4: the stamp must not become wallpaper on every file (constraint 3).

        The fixture writes an INDENTED report on purpose: `json.dumps` reproduces
        the stub's default form byte for byte, so a round-trip through the accept
        path would pass this assertion for a reason unrelated to the property.
        """
        from close_helpers import stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        written = json.dumps(CLEAN, indent=2) + "\n"
        stub_reviewer(tmp_path, report=written)
        assert close(repo, env, "review").returncode == 0
        (report,) = (tmp_path / "data" / "reports").glob("*.json")
        assert report.read_text() == written

    def test_the_findings_of_a_refused_round_still_reach_the_lead_first(self, tmp_path):
        """AC 5: a report the pipeline rejects still cost a full review, and its
        findings exist nowhere else — close.py prints them before every refusal
        below it, and this card must not regress that."""
        from close_helpers import stub_reviewer

        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, result="F1: the retry flag is inverted")
        r = close(repo, env, "review")
        assert r.returncode != 0
        assert "F1: the retry flag is inverted" in r.stdout, r.stdout

    def test_land_still_runs_verify_after_the_review_leg_does(self, tmp_path):
        """AC 6: this card ADDS a gate, it does not move one, and the cheapest
        wrong implementation deletes land's copy as a duplicate.

        The TREE moves rather than the Verify line, so the card keeps its ready
        credential and the reds are attributable to the two legs separately.
        """
        repo, env, g = make_repo(tmp_path, verify="test -f sentinel")
        (repo / "sentinel").write_text("green at review time\n")
        g("add", "-A")
        g("commit", "-qm", "sentinel")
        assert close(repo, env, "review").returncode == 0, "review's own Verify was red"
        (repo / "sentinel").unlink()
        g("add", "-A")
        g("commit", "-qm", "the lead broke Verify after the round was recorded")
        landed = close(repo, env, "land")
        assert landed.returncode != 0, landed.stdout
        assert "Verify red" in landed.stderr, landed.stderr


class TestTheRoundNeedsItsHandoffDiff:
    """One rule, two implementations, and only story-047's sprint half was told.

    The story leg calls write_reviewer_diff with no arm for a write that fails —
    and the reviewer's fix is already COMMITTED by the time it runs, so the lead
    is left holding reviewer commits nothing handed over, no round recording
    them, and a next review that refuses on the HEAD this one moved.
    """

    def test_a_round_is_not_recorded_without_its_handoff_diff(self, tmp_path):
        """Constructed the same way test_sprint_review.py asserts it of the sprint
        leg: the handoff path is a DIRECTORY, so writing it raises."""
        repo, env, g = make_repo(tmp_path)
        before = g("rev-parse", "HEAD").stdout.strip()
        stub_reviewer(tmp_path, patch=FIX_PATCH)
        (pathlib.Path(env["XP_DATA"]) / "reports" / "story-042.round-1.diff").mkdir(parents=True)

        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert "could not write reviewer handoff" in r.stderr, r.stderr
        assert "refused: refused:" not in r.stderr, "the refusal was wrapped twice"
        assert "close.py story story-042 review" in r.stderr, r.stderr
        assert g("rev-parse", "HEAD").stdout.strip() == before, "the applied fix was not undone"
        assert not marker_file(tmp_path).exists(), "a round was recorded without its handoff"
        assert close(repo, env, "land").returncode != 0


class TestTheReviewersOwnFixIsUnderTheGateItPasses:
    """close.py::_record_round runs Verify AFTER applying the reviewer's patch, so
    the round certifies the same tree it stores as `shown_sha`. Nothing pinned that
    order: measured on this tree, swapping the two statements so Verify reads the
    PRE-patch tree left all 844 tests green, because every other test's reviewer
    stub leaves a tree that is red both before and after its patch. Story-036's own
    argument is the property — "a reviewer that cannot run tests still produces
    confident fixes, and they are exactly as wrong as the confidence is unearned".

    The consequence is bounded and must not be read as larger: land runs Verify
    again on the tree it merges (test_land_still_runs_verify_after_the_review_leg_
    does), so a bad reviewer patch is still caught one leg later and no wrong merge
    lands. What a swap costs is the review-time catch and the truth of a RECORDED
    round, not the merge gate.
    """

    # green on the reviewed tree (`A = 2`), red on the tree the reviewer leaves
    VERIFY = "! grep -q BROKEN src/thing.py"
    BREAKS_VERIFY = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+BROKEN = 1
"""

    def test_a_reviewer_patch_that_reds_verify_records_no_round(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify=self.VERIFY)
        thing = repo / "src" / "thing.py"
        assert "BROKEN" not in thing.read_text(), "Verify was already red before the patch"
        stub_reviewer(tmp_path, patch=self.BREAKS_VERIFY)

        r = close(repo, env, "review")
        assert r.returncode != 0, r.stdout
        assert "Verify red" in r.stderr, r.stderr
        # BOTH halves, or the assertion above passes for the wrong reason: a patch
        # that never applied would red Verify only by failing to apply.
        assert "BROKEN" in thing.read_text(), "the reviewer's patch never reached the tree"
        assert not marker_file(tmp_path).exists(), "a round certified a tree Verify never saw"

    def test_a_recorded_round_is_not_offered_an_undo_that_denies_it(self, tmp_path):
        """The same red tree, but with findings, so story-054 records the round.
        The `git reset --hard` this refusal still offers would orphan the sha that
        round names, and the sentence above it used to say no round existed."""
        repo, env, _g = make_repo(tmp_path, verify=self.VERIFY)
        report = {"fixed": [], "blocking": ["B"], "noted": []}
        stub_reviewer(tmp_path, patch=self.BREAKS_VERIFY, report=report)

        r = close(repo, env, "review")
        assert r.returncode != 0 and "git reset --hard" in r.stderr, r.stderr
        assert "No round was" not in r.stderr and "IS recorded" in r.stderr, r.stderr
        assert marker(tmp_path)["rounds"][-1]["blocking"] == ["B"]

    def test_a_recorded_round_says_so_even_when_no_undo_is_offered(self, tmp_path):
        """The same recording, with the reviewer writing NO patch: the tree never
        moves, abort_text takes its short path, and the round's fate rode in the
        undo sentence the short path drops. Exit 2 over a silently recorded round
        sends the lead to re-review a story that already has one."""
        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": ["B"], "noted": []})

        r = close(repo, env, "review")
        assert r.returncode != 0 and "git reset --hard" not in r.stderr, r.stderr
        assert "IS recorded" in r.stderr, r.stderr
        assert marker(tmp_path)["rounds"][-1]["blocking"] == ["B"]
