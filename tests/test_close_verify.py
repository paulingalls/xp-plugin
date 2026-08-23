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
