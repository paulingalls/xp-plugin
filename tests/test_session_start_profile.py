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

# `original - truncated` in every one of the six Sprint-8 cuts, exactly, across three
# different tails: Codex bounds a hook payload in TOKENS. OUTPUT_CAP is a character
# proxy for it, so the conversion is the assumption that can rot — those 2,458 tokens
# carried 9,912 chars of this repo's markdown, and its own tool outputs measure 3.98
# chars/token, so the floor below is where the proxy stops holding (AUDIT.md §10).
CODEX_RETAINED_TOKENS = 2_458
DENSITY_FLOOR = 3.7  # chars/token


class TestTheRealProfileAgainstTheRealCap:
    """Every other test here drives TOY fixtures — a two-line VALUES, a
    ten-item constraints. So the suite stayed green while this repo's own
    profile grew past the cap and the cut landed INSIDE constraints.md,
    dropping four rules the lead is judged by. Found by the sprint closer,
    caused by the retro that added constraint 15 so the lead would read it.
    """

    def run_real(self):
        """XP_ROLE PINNED, and the marker asserted absent: the whole suite runs
        under a reviewer role at every sprint review, where the hook's role gate
        prints its 121-char teammate line and returns before a profile is built.
        Both tests below then took their early `return` and asserted NOTHING —
        vacuous exactly when a review is what would have caught it (constraint 2).

        EMPTY IS ITS OWN STATE, and the one measured live: `run_hook` is advisory,
        so a hook that raises exits 0 with the traceback on STDERR and nothing on
        stdout. That output passes the marker check above and then sends the two
        early-return tests home green. Measured in the Sprint-8 Codex-lead
        transcript, where the sandbox denied the data root and this script's
        sibling falsifier died on `out.index` instead (AUDIT.md §10).
        """
        repo = Path(__file__).parent.parent
        payload = {"hook_event_name": "SessionStart", "cwd": str(repo)}
        out = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=repo,
            env=dict(os.environ) | {"XP_ROLE": "lead"},
        ).stdout
        assert "teammate session" not in out, "the role gate ate the profile; this asserts nothing"
        assert out.strip(), "the hook printed nothing (stderr holds the traceback); nothing asserts"
        return out

    def test_our_own_digest_is_within_the_bound_the_hook_enforces(self):
        """The dogfood arm of bug 597c32db. Ours was 380 lines and 26,797 chars
        when the sprint closer found it — by reading, not by any gate — and the
        toy fixtures next door stayed green throughout, which is this file's
        whole reason to exist.

        Absent reads as zero: a fresh clone legitimately has no digest yet, and
        that is a different state from one too big to inject (constraint 15).
        """
        sys.path.insert(0, str(Path(__file__).parent.parent / "plugins/xp-plugin/scripts"))
        from session_start import DIGEST_CAP, data_root

        digest = data_root() / "session.md"
        count = len(digest.read_text().splitlines()) if digest.exists() else 0
        assert count <= DIGEST_CAP, f"{digest} is {count} lines against {DIGEST_CAP}"

    def test_this_repos_profile_fits_with_values_and_process_leading_it(self):
        """Bug ab6a1354, on the HOOK'S OWN STDOUT — not on a sum of parts, which
        misses the joins and the trust markers by 117 chars.

        ORDER is asserted alongside size, and it is the half a size check cannot
        carry: a size-only assertion passes under any arrangement at all.
        """
        from session_start import OUTPUT_CAP

        assert OUTPUT_CAP <= CODEX_RETAINED_TOKENS * DENSITY_FLOOR, (
            f"OUTPUT_CAP {OUTPUT_CAP} is ~{OUTPUT_CAP / 4.03:.0f} tokens of this repo's"
            f" markdown against Codex's measured {CODEX_RETAINED_TOKENS}-token retention"
            " — the harness would eat the middle again and name none of it"
        )
        out = self.run_real()
        assert len(out) <= OUTPUT_CAP, f"the profile assembles {len(out)} against {OUTPUT_CAP}"
        plugin = Path(__file__).parent.parent / "plugins" / "xp-plugin"
        values = (plugin / "VALUES.md").read_text()[:60]
        process = (plugin / "PROCESS.md").read_text()[:60]
        assert out.index(values) < out.index(process) < out.index("BEGIN project content"), (
            "VALUES sets the stage and PROCESS is the loop; they lead the profile"
        )

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
        rules_on = body.split("BEGIN project content", 1)[-1]  # PROCESS ships `N. **` too
        for n in named:
            assert not re.search(rf"^{n}\. \*\*", rules_on, re.M), (
                f"constraint {n} is named as dropped but IS in the profile"
            )
