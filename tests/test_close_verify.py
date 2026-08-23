"""The Verify: line's gates — the credential mint and land, one rule at two depths.

Its own file rather than more of test_close_land.py, which stood at the 500-line
cap (constraint 8: extract, never trim a test to fit).
"""

import json
import pathlib

from close import story_card
from close_helpers import close, make_repo


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
        from work import card_digest, ready_marker_path

        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        original = plan.read_text()

        def recredential(text):
            plan.write_text(text)
            card = story_card(text, "story-042")[0]
            marker = pathlib.Path(env["XP_DATA"]) / "markers" / "story-042.ready.json"
            marker.write_text(json.dumps({"digest": card_digest(card), "card": card}))
            assert marker.exists() and ready_marker_path

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
