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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from session_start_helpers import HOOK

CODEX_RETAINED_BYTES = [(4_916, 5_084)] * 6
CODEX_OUTPUT_BOUND = 10_000
HEADROOM = 500

# The `recover` surface writes to the TOOL channel, whose bound is a different
# number in a different unit: codex 0.149.0's help text for `exec` reads
# "`max_output_tokens` sets the token budget for direct `exec` results. Defaults
# to 10000 tokens". There is no byte figure to measure, so RECOVER_CAP is a byte
# PROXY and the density is what can rot — AUDIT §10 measured 4.03 chars/token for
# this repo's markdown and a 3.98 median for codex's own tool output; the floor
# below is deliberately under both, because the recovery block is denser than
# prose (branch names, SHAs, timestamps).
CODEX_EXEC_TOKEN_BOUND = 10_000
DENSITY_FLOOR = 3.5  # bytes/token


class TestTheRealProfileAgainstTheRealCap:
    """Every other test here drives TOY fixtures — a two-line VALUES, a
    ten-item constraints. So the suite stayed green while this repo's own
    profile grew past the cap and the cut landed INSIDE constraints.md,
    dropping four rules the lead is judged by. Found by the sprint closer,
    caused by the retro that added constraint 15 so the lead would read it.
    """

    def run_real(self, hook=HOOK):
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
            [sys.executable, str(hook)],
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

    def assert_all_constraints_delivered(self, out):
        rules = (Path(__file__).parent.parent / ".xp" / "constraints.md").read_text()
        headings = re.findall(r"^(\d+\. \*\*[^\n]+)", rules, re.M)
        assert len(headings) == 15, "the fixture is no longer at constraints_cap"
        delivered = [heading for heading in headings if heading in out]
        assert len(delivered) == 15, f"only {len(delivered)}/15 constraints reached the lead"

    def test_this_repos_profile_delivers_every_constraint_in_bytes(self):
        """Bug ab6a1354, on the HOOK'S OWN STDOUT — not on a sum of parts, which
        misses the joins and the trust markers by 117 chars.

        ORDER is asserted alongside size, and it is the half a size check cannot
        carry: a size-only assertion passes under any arrangement at all.
        """
        from session_start import OUTPUT_CAP

        assert all(head + tail == CODEX_OUTPUT_BOUND for head, tail in CODEX_RETAINED_BYTES)
        assert CODEX_OUTPUT_BOUND - OUTPUT_CAP == HEADROOM
        out = self.run_real()
        assert len(out.encode()) <= OUTPUT_CAP, "the NEXT region outgrew the real lead profile"
        assert len([line for line in out.splitlines() if line.startswith("NEXT:")]) == 1, (
            "the NEXT region did not reach the real lead profile exactly once"
        )
        self.assert_all_constraints_delivered(out)
        plugin = Path(__file__).parent.parent / "plugins" / "xp-plugin"
        values = (plugin / "VALUES.md").read_text()[:60]
        process = (plugin / "PROCESS.md").read_text()[:60]
        assert out.index(values) < out.index(process) < out.index("BEGIN project content"), (
            "VALUES sets the stage and PROCESS is the loop; they lead the profile"
        )

    def test_lowering_the_real_hook_cap_reds_the_delivery_check(self, tmp_path):
        plugin = tmp_path / "xp-plugin"
        shutil.copytree(HOOK.parent.parent, plugin)
        hook = plugin / "scripts" / "session_start.py"
        hook.write_text(hook.read_text().replace("OUTPUT_CAP = 9_500", "OUTPUT_CAP = 7_500"))
        out = self.run_real(hook)
        with pytest.raises(AssertionError, match=r"only \d+/15 constraints"):
            self.assert_all_constraints_delivered(out)

    def test_the_recover_cap_sits_under_the_tool_channels_own_bound(self):
        """A cap AT the bound fails on the first sentence anyone adds, and this one
        cannot even see the bound it is under: codex counts the exec channel in
        TOKENS and truncates the MIDDLE, naming no region. Our cut must land first,
        or `recover`'s whole disclosure mechanism never runs. 40,000 — one round's
        value — was ~10,000 tokens at the density already on record, i.e. exactly
        the units error this card exists to correct, one channel over.
        """
        from session_start import RECOVER_CAP

        tokens = RECOVER_CAP / DENSITY_FLOOR
        assert tokens < CODEX_EXEC_TOKEN_BOUND, (
            f"RECOVER_CAP {RECOVER_CAP} is ~{tokens:.0f} tokens at {DENSITY_FLOOR} bytes/token"
            f" against codex's {CODEX_EXEC_TOKEN_BOUND}-token exec budget"
        )

    def test_digest_recovery_and_sprint_slice_are_not_injected(self):
        out = self.run_real()
        for removed in ("branch:", "recent work.md entries:", "stories:", "Session digest"):
            assert removed not in out, f"{removed!r} still spends the SessionStart payload"

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
