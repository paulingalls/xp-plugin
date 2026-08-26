"""The Verify: line's gates — the credential mint and land, one rule at two depths.

Its own file rather than more of test_close_land.py, which stood at the 500-line
cap (constraint 8: extract, never trim a test to fit).
"""

import json
import pathlib

from close import story_card
from close_helpers import (
    CLEAN,
    FIX_PATCH,
    close,
    make_repo,
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
        assert "close.py story story-042 review" in r.stderr, r.stderr
        assert g("rev-parse", "HEAD").stdout.strip() == before, "the applied fix was not undone"
        assert not marker_file(tmp_path).exists(), "a round was recorded without its handoff"
        assert close(repo, env, "land").returncode != 0
