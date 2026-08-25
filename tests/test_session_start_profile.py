"""THIS repo's real profile against the real cap.

Verify: pytest -q tests/test_session_start_profile.py

Extracted from test_session_start.py at the sprint-6 close (constraint 8: over
cap means extract, not scroll). It is a cohesive leaf — every other test in that
file drives TOY fixtures, which is exactly why the suite stayed green while this
repo's own profile outgrew the budget.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from session_start_helpers import HOOK


class TestTheRealProfileAgainstTheRealCap:
    """Every other test here drives TOY fixtures — a two-line VALUES, a
    ten-item constraints. So the suite stayed green while this repo's own
    profile grew past the cap and the cut landed INSIDE constraints.md,
    dropping four rules the lead is judged by. Found by the sprint closer,
    caused by the retro that added constraint 15 so the lead would read it.
    """

    def run_real(self):

        repo = Path(__file__).parent.parent
        payload = {"hook_event_name": "SessionStart", "cwd": str(repo)}
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=repo,
            env=dict(os.environ),
        ).stdout

    def test_a_truncated_profile_names_the_constraints_it_dropped(self):
        """The budget is allowed not to fit. It is NOT allowed to hide which
        rules it cut: a silently-absent constraint is one the lead never knew it
        was breaking, which is why session_start orders them ahead of the digest
        in the first place."""
        out = self.run_real()
        if "[truncated" not in out:
            return  # everything fit; nothing to name
        marker = out[out.index("[truncated") :]
        assert "constraints.md" in marker, f"the cut does not say where to read them: {marker}"
        assert re.search(r"CONSTRAINTS [\d, ]+ ARE NOT ABOVE", marker), marker

    def test_the_constraints_it_names_are_genuinely_absent(self):
        """And the claim must be TRUE — a marker naming the wrong numbers sends
        the lead to re-read rules it already has and to skip ones it does not."""
        out = self.run_real()
        if "[truncated" not in out:
            return
        body, marker = out.split("[truncated", 1)
        if "ARE NOT ABOVE" not in marker:
            return  # test 1 owns "there must be a claim"; this one owns its truth
        claim = marker.split("ARE NOT ABOVE")[0].split("CONSTRAINTS", 1)[-1]
        named = [int(n) for n in re.findall(r"\b(\d+)\b", claim)]
        assert named, marker
        for n in named:
            assert not re.search(rf"^{n}\. \*\*", body, re.M), (
                f"constraint {n} is named as dropped but IS in the profile"
            )
