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
import tempfile
from pathlib import Path

import pytest
from session_start_helpers import BUDGET_WARNING, HOOK

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

    def run_real(self, tmp_path, hook=HOOK, recorded_root=None):
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

        THE DATA ROOT IS A COPY, not the real one: this runs the hook as a LEAD,
        so against the real root it MOVES the live pin — and the cap-mutation case
        below moves it to a tmp plugin pytest then deletes. The suite was the
        defect the story it guards exists to fix.
        """
        sys.path.insert(0, str(HOOK.parent))
        from env import data_root, plugin_version

        source = data_root()
        isolated = tmp_path / "profile-data"
        isolated.mkdir()
        for name in ("plan.md", "installed-claude-version", "installed-codex-version"):
            if (path := source / name).exists():
                shutil.copy2(path, isolated / name)
        if (source / "markers").exists():
            shutil.copytree(source / "markers", isolated / "markers")
        plugin = hook.parent.parent
        (isolated / "env.json").write_text(
            json.dumps(
                {
                    "plugin_root": str(plugin if recorded_root is None else recorded_root),
                    "plugin_version": plugin_version(plugin),
                }
            )
        )
        repo = Path(__file__).parent.parent
        payload = {"hook_event_name": "SessionStart", "cwd": str(repo)}
        out = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=repo,
            env=dict(os.environ) | {"XP_ROLE": "lead", "XP_DATA": str(isolated)},
        ).stdout
        assert "teammate session" not in out, "the role gate ate the profile; this asserts nothing"
        assert out.strip(), "the hook printed nothing (stderr holds the traceback); nothing asserts"
        return out

    def path_at_length(self, base, name, target):
        pad = target - len(str(base / name))
        assert pad >= 0, f"{base / name} is longer than the requested {target}-byte path"
        path = base / (name + "p" * pad)
        assert len(str(path)) == target
        return path

    def copied_plugin(self, tmp_path, name, target, output_cap=None):
        root = self.path_at_length(tmp_path, name, target)
        shutil.copytree(HOOK.parent.parent, root)
        if output_cap is not None:
            hook = root / "scripts" / "session_start.py"
            text = hook.read_text()
            # The SPELLING of the cap is not the guarantee (constraint 11): pinned
            # to `9_500` this harness reds on a retune of the very number it exists
            # to inject. Matched, and required to be unique so a second literal
            # cannot leave half the file rewritten.
            text, swapped = re.subn(r"OUTPUT_CAP = \S+", f"OUTPUT_CAP = {output_cap:_}", text)
            assert swapped == 1, "session_start.py no longer assigns OUTPUT_CAP exactly once"
            hook.write_text(text)
        return root

    def constraints_at_bytes(self, size, character="x"):
        seed = "# Constraints\n\n" + "\n".join(f"{n}. **Rule {n}**" for n in range(1, 16))
        room = size - len(seed.encode())
        width = len(character.encode())
        assert room >= 0
        rules = seed + character * (room // width) + "x" * (room % width)
        assert len(rules.encode()) == size
        assert len(re.findall(r"^\d+\. \*\*", rules, re.M)) == 15
        return rules

    def run_constructed(self, tmp_path, name, plugin, rules, recorded_root=None):
        repo = tmp_path / f"{name}-repo"
        data = tmp_path / f"{name}-data"
        (repo / ".xp").mkdir(parents=True)
        data.mkdir()
        (repo / ".xp" / "config.yml").write_text("constraints_chars_cap: 4500\n")
        (repo / ".xp" / "constraints.md").write_text(rules)
        manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
        (data / "env.json").write_text(
            json.dumps(
                {
                    "plugin_root": str(plugin if recorded_root is None else recorded_root),
                    "plugin_version": manifest["version"],
                }
            )
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        result = subprocess.run(
            [sys.executable, str(plugin / "scripts" / "session_start.py")],
            input=json.dumps({"cwd": str(repo), "session_id": "s", "source": "startup"}),
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(data),
                "XP_DATA": str(data),
                "XP_ROLE": "lead",
            },
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert not result.stderr, result.stderr
        assert result.stdout, "the copied hook emitted no profile"
        return result.stdout

    def budget_report(self, out):
        matches = BUDGET_WARNING.findall(out)
        assert len(matches) == 1, out
        return tuple(map(int, matches[0]))

    def test_changing_OUTPUT_CAP_moves_the_derived_constraints_budget(self, tmp_path):
        target = max(len(str(tmp_path / name)) for name in ("cap-a", "cap-b")) + 20
        first = self.copied_plugin(tmp_path, "cap-a", target)
        second = self.copied_plugin(tmp_path, "cap-b", target, output_cap=9_300)
        rules = self.constraints_at_bytes(6_000)
        first_budget = self.budget_report(self.run_constructed(tmp_path, "cap-a", first, rules))[1]
        second_budget = self.budget_report(self.run_constructed(tmp_path, "cap-b", second, rules))[
            1
        ]
        assert first_budget - second_budget == 200

    def test_multibyte_constraints_overage_is_reported_in_bytes(self, tmp_path):
        target = len(str(tmp_path / "unicode")) + 20
        plugin = self.copied_plugin(tmp_path, "unicode", target)
        seed = self.constraints_at_bytes(300)
        ascii_rules = seed + "x" * 5_000
        unicode_rules = seed + "界" * 5_000
        assert len(ascii_rules) == len(unicode_rules)
        for name, rules in (("ascii", ascii_rules), ("multi", unicode_rules)):
            overage, budget = self.budget_report(
                self.run_constructed(tmp_path, name, plugin, rules)
            )
            assert overage == len(rules.encode()) - budget

    def test_a_one_byte_overage_warns_without_truncating_constraints(self, tmp_path):
        from session_start import OUTPUT_CAP

        target = len(str(tmp_path / "one-byte")) + 20
        plugin = self.copied_plugin(tmp_path, "one-byte", target)
        oversized = self.run_constructed(
            tmp_path, "probe-one", plugin, self.constraints_at_bytes(6_000)
        )
        budget = self.budget_report(oversized)[1]
        rules = self.constraints_at_bytes(budget + 1)
        out = self.run_constructed(tmp_path, "exact-one", plugin, rules)
        assert self.budget_report(out) == (1, budget)
        assert "constraints.md is 1 byte over" in out
        assert rules in out
        headings = re.findall(r"^\d+\. \*\*[^\n]+", rules, re.M)
        assert len(headings) == 15 and all(heading in out for heading in headings)
        assert "[truncated at" not in out
        assert len(out.encode()) <= OUTPUT_CAP

    @pytest.mark.parametrize(
        "recorded_root", [None, Path("/previous")], ids=["no-notice", "move-notice"]
    )
    def test_a_longer_plugin_path_reduces_the_measured_allowance(self, tmp_path, recorded_root):
        delta = 17
        short_target = max(len(str(tmp_path / name)) for name in ("short", "other")) + 20
        short = self.copied_plugin(tmp_path, "short", short_target)
        longer = self.copied_plugin(tmp_path, "other", short_target + delta)
        oversized = self.constraints_at_bytes(6_000)
        short_out = self.run_constructed(
            tmp_path, "short", short, oversized, recorded_root=recorded_root
        )
        long_out = self.run_constructed(
            tmp_path, "other", longer, oversized, recorded_root=recorded_root
        )
        short_budget = self.budget_report(short_out)[1]
        long_budget = self.budget_report(long_out)[1]
        assert short_budget - long_budget == delta
        if recorded_root is not None:
            for out in (short_out, long_out):
                assert "plugin root moved from" in out
                assert "[environment notice shortened]" not in out
        rules = self.constraints_at_bytes(long_budget + 1)
        out = self.run_constructed(tmp_path, "again", longer, rules, recorded_root=recorded_root)
        assert self.budget_report(out) == (1, long_budget)
        assert rules in out and "[truncated at" not in out

    def test_a_large_overage_warns_before_render_reports_what_it_cut(self, tmp_path):
        target = len(str(tmp_path / "large")) + 20
        plugin = self.copied_plugin(tmp_path, "large", target)
        probe = self.run_constructed(tmp_path, "probe", plugin, self.constraints_at_bytes(6_000))
        budget = self.budget_report(probe)[1]
        rules = self.constraints_at_bytes(budget + 3_000)
        out = self.run_constructed(tmp_path, "large", plugin, rules)
        overage, reported = self.budget_report(out)
        assert (overage, reported) == (len(rules.encode()) - budget, budget)
        assert out.count("[truncated at") == 1
        assert out.index("[constraints.md is") < out.index("[truncated at")
        body, marker = out.split("[truncated at", 1)
        # THE PRESENCE OF THE CLAIM IS ASSERTED FIRST, and it is what the round-3
        # reviewer found missing: `split` returns the WHOLE marker when its
        # separator is absent, so the number scan below fell through to the
        # notice's own "9500" and greened. Measured: with `notice(lost, ...)`
        # mutated to `notice([], ...)` — the entire dropped-constraint disclosure
        # deleted — this test and the other 38 stayed green.
        assert "ARE NOT ABOVE" in marker, f"the cut named no dropped constraints: {marker}"
        claim = marker.split(" ARE NOT ABOVE", 1)[0].rsplit("CONSTRAINTS ", 1)[-1]
        lost = re.findall(r"\b(\d+)\b", claim)
        assert lost, marker
        assert all(not re.search(rf"^{number}\. \*\*", body, re.M) for number in lost)
        # AND IT IS COMPLETE: naming a true subset is how a lead reads a rule it
        # never got as one it merely skimmed. Every heading absent from the body
        # must appear in the claim.
        absent = [
            n
            for n in re.findall(r"^(\d+)\. \*\*", rules, re.M)
            if not re.search(rf"^{n}\. \*\*", body, re.M)
        ]
        assert absent and sorted(absent) == sorted(lost), f"cut {absent}, named {lost}"

    def test_this_repos_constraints_survive_a_long_checkout_path(self, tmp_path):
        """AC6's property for the file we actually ship under, CONSTRUCTED rather than
        read off this checkout (constraint 11) — the sibling above certifies only the
        78-character path the suite happens to sit in, which is how a worktree-length
        path went unnoticed until one blocked the commit wall (764bd9e).

        THE BUDGET WARNING IS NOT FREE: it is emitted into the budget it reports on,
        so it buys its 102 bytes out of delivery margin. Re-measured at THIS HEAD
        against .xp/constraints.md: the warning starts at a 147-character plugin
        path and all 15 rules still land through 162; 163 is the first that cuts
        one. THIS NUMBER ROTS ON EVERY SHIPPED-PROSE EDIT and already has — it read
        "~132, 13/15 by 150" one commit before 591c2b9 returned 81 bytes to the
        budget. Re-measure it here; never cite it, and never cite the card's ~175.
        """
        base = Path(tempfile.mkdtemp())
        try:
            plugin = self.path_at_length(base, "p", 110)
            shutil.copytree(HOOK.parent.parent, plugin)
            out = self.run_real(tmp_path, plugin / "scripts" / "session_start.py")
        finally:
            shutil.rmtree(base, ignore_errors=True)
        assert "[truncated at" not in out, "a 110-character plugin path already cuts the profile"
        self.assert_all_constraints_delivered(out)

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

    def test_this_repos_profile_delivers_every_constraint_in_bytes(self, tmp_path):
        """Bug ab6a1354, on the HOOK'S OWN STDOUT — not on a sum of parts, which
        misses the joins and the trust markers by 117 chars.

        ORDER is asserted alongside size, and it is the half a size check cannot
        carry: a size-only assertion passes under any arrangement at all.
        """
        from session_start import OUTPUT_CAP

        assert all(head + tail == CODEX_OUTPUT_BOUND for head, tail in CODEX_RETAINED_BYTES)
        assert CODEX_OUTPUT_BOUND - OUTPUT_CAP == HEADROOM
        out = self.run_real(tmp_path)
        assert len(out.encode()) <= OUTPUT_CAP, (
            f"{len(out.encode())} bytes over {OUTPUT_CAP}; NEXT is the newest region, but any"
            " of them can be the one that grew — read the profile, do not assume"
        )
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

    @pytest.mark.parametrize("suffix", ["a" * 5_000, "界" * 2_500])
    def test_a_root_move_notice_preserves_every_constraint(self, tmp_path, suffix):
        previous = Path(str(HOOK.parents[4] / "story-123") + suffix) / "plugins" / "xp-plugin"
        out = self.run_real(tmp_path, recorded_root=previous)
        from session_start import OUTPUT_CAP

        self.assert_all_constraints_delivered(out)
        assert "plugin root moved from" in out
        assert "[environment notice shortened]" in out
        assert len(out.encode()) <= OUTPUT_CAP

    def test_lowering_the_real_hook_cap_reds_the_delivery_check(self, tmp_path):
        plugin = tmp_path / "xp-plugin"
        shutil.copytree(HOOK.parent.parent, plugin)
        hook = plugin / "scripts" / "session_start.py"
        hook.write_text(hook.read_text().replace("OUTPUT_CAP = 9_500", "OUTPUT_CAP = 7_500"))
        out = self.run_real(tmp_path, hook)
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

    def test_digest_recovery_and_sprint_slice_are_not_injected(self, tmp_path):
        out = self.run_real(tmp_path)
        for removed in ("branch:", "recent work.md entries:", "stories:", "Session digest"):
            assert removed not in out, f"{removed!r} still spends the SessionStart payload"

    def test_a_truncated_profile_names_the_constraints_it_dropped(self, tmp_path):
        """The budget is allowed not to fit. It is NOT allowed to hide which
        rules it cut: a silently-absent constraint is one the lead never knew it
        was breaking, which is why session_start orders them ahead of the digest
        in the first place."""
        out = self.run_real(tmp_path)
        if "[truncated" not in out:
            return  # everything fit; nothing to name
        marker = out[out.index("[truncated") :]
        assert "constraints.md" in marker, f"the cut does not say where to read them: {marker}"
        assert re.search(r"CONSTRAINTS [\d, ]+ ARE NOT ABOVE", marker), marker

    def test_the_constraints_it_names_are_genuinely_absent(self, tmp_path):
        """And the claim must be TRUE — a marker naming the wrong numbers sends
        the lead to re-read rules it already has and to skip ones it does not."""
        out = self.run_real(tmp_path)
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
