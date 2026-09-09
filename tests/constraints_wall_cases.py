import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from session_start_helpers import BUDGET_WARNING

# LC_ALL=C ALONE PROVES NOTHING: PEP 538 silently coerces a C locale to C.UTF-8, so
# the character count came out right for a reason the wall did not own. Disabling
# coercion and UTF-8 mode is what makes the locale test able to red.
C_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}


class ConstraintsWallCases:
    def cap_value(self, path):
        line = next(
            ln for ln in path.read_text().splitlines() if ln.startswith("constraints_chars_cap:")
        )
        return int(line.split(":", 1)[1].split("#", 1)[0])

    def test_constraints_character_cap_is_the_same_in_both_configs(self):
        ours = self.cap_value(self.OURS / "config.yml")
        assert ours == self.cap_value(self.SHIPPED / "config.yml") == 4_500

    def run_constraints_wall(
        self, tmp_path, cap, size, character="x", tier="fast", path=None, write=True
    ):
        xp = tmp_path / ".xp"
        xp.mkdir(exist_ok=True)
        setting = "" if cap is None else f"constraints_chars_cap: {cap}\n"
        tiers = "".join(f"  {name}: true\n" for name in ("fast", "story", "full"))
        (xp / "config.yml").write_text(f"{setting}tests:\n{tiers}")
        if write:
            (xp / "constraints.md").write_text(character * size, encoding="utf-8")
        hook_lib = self.SHIPPED / "hook-lib.sh"
        env = dict(os.environ) | {"HOOK_LIB": str(hook_lib)} | C_LOCALE
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["sh", "-c", f'. "$HOOK_LIB"; run_tier {tier}'],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_the_wall_refuses_when_the_MEASUREMENT_itself_fails(self, tmp_path):
        """A gate that reports green having run nothing is worse than no gate —
        hook-lib.sh opens with that rule and constraints_size used to break it: an
        empty `count` makes `[ "" -gt N ]` error, which reads as under-cap. One
        injection per guard: no python3 on PATH, and a constraints.md the reader
        cannot open. The first matches the STANZA'S OWN SENTENCE rather than the
        bare word `python3`, because the shell prints `python3: command not found`
        itself — measured: with the `command -v` guard deleted the looser match
        still saw `python3` and `nothing measured`, so it pinned nothing.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("sed", "head", "sh", "cat"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        blind = self.run_constraints_wall(tmp_path, 4_500, 10, path=str(bin_dir))
        assert blind.returncode != 0, blind.stdout
        assert "python3 not installed" in blind.stderr, blind.stderr
        assert "nothing measured" in blind.stderr and "then retry" in blind.stderr, blind.stderr

        (tmp_path / ".xp" / "constraints.md").chmod(0o000)
        try:
            unreadable = self.run_constraints_wall(tmp_path, 4_500, 10, write=False)
        finally:
            (tmp_path / ".xp" / "constraints.md").chmod(0o644)
        assert unreadable.returncode != 0, unreadable.stdout
        assert "could not measure" in unreadable.stderr, unreadable.stderr
        assert "then retry" in unreadable.stderr, unreadable.stderr

    def test_scaffolded_wall_refuses_constraints_over_the_character_cap(self, tmp_path):
        red = self.run_constraints_wall(tmp_path, 4_500, 4_501)
        assert red.returncode != 0
        for claim in ("constraints.md", "4501", "4500", "retire", "shorten"):
            assert claim in red.stderr, red.stderr

        green = self.run_constraints_wall(tmp_path, 4_502, 4_501)
        assert green.returncode == 0, green.stderr

    def test_constraints_wall_distinguishes_missing_and_invalid_caps(self, tmp_path):
        missing = self.run_constraints_wall(tmp_path, None, 1)
        assert missing.returncode != 0 and "missing" in missing.stderr
        default = self.cap_value(self.SHIPPED / "config.yml")
        assert f"add `constraints_chars_cap: {default}`" in missing.stderr.lower()
        assert ".xp/config.yml" in missing.stderr
        added = self.run_constraints_wall(tmp_path, default, 1)
        assert added.returncode == 0, added.stderr
        invalid = self.run_constraints_wall(tmp_path, "many", 1)
        assert invalid.returncode != 0 and "invalid" in invalid.stderr

    def test_constraints_wall_counts_unicode_characters_independent_of_locale(self, tmp_path):
        red = self.run_constraints_wall(tmp_path, 4_500, 4_501, "\N{GRINNING FACE}")
        assert red.returncode != 0 and "4501 characters" in red.stderr, red.stderr
        under = self.run_constraints_wall(tmp_path, 4_500, 4_499, "\N{GRINNING FACE}")
        assert under.returncode == 0, under.stderr  # 17,996 BYTES, and still under cap

    def test_every_tier_re_checks_the_character_cap(self, tmp_path):
        """pre-commit is not the only gate that runs it: a scaffolded pre-push runs
        `run_tier story`, and `git merge` fires no pre-commit at all. Wired to fast
        alone, story and full both exited 0 over a cap they were meant to hold."""
        for tier in ("fast", "story", "full"):
            red = self.run_constraints_wall(tmp_path, 4_500, 4_501, tier=tier)
            assert red.returncode != 0, f"run_tier {tier} passed an over-cap constraints.md"
            assert "4500" in red.stderr, red.stderr

    # Constructed, not inherited: installed paths measured near 70/45 and our
    # spawn worktrees near 102/40. Exact headroom moves with shipped prose.
    PLUGIN_PATH_BUDGET = 110
    DATA_ROOT_BUDGET = 70

    def _at_path_length(self, base, name, target):
        """A directory whose ABSOLUTE path is exactly `target` chars.

        CONSTRUCTED, never inherited: read off wherever the checkout happens to
        live, this test passed at a 59-char path and failed at 102 — reporting the
        machine, not the guarantee (constraint 11). It does NOT skip when the base
        is too long: a skip is a measurement of nothing that reads as a pass.
        """
        pad = target - len(str(base / name))
        assert pad >= 0, (
            f"cannot measure: {base}/{name} is already {-pad} chars over the"
            f" {target}-char budget, so nothing was tested. Run from a shorter TMPDIR"
        )
        return base / (name + "d" * pad)

    def _run_ascii_profile(self, tmp_path, constraints, plugin_path_budget=None):
        base = Path(tempfile.mkdtemp())
        plugin_root = self._at_path_length(base, "p", plugin_path_budget or self.PLUGIN_PATH_BUDGET)
        data_root = self._at_path_length(base, "d", self.DATA_ROOT_BUDGET)
        shutil.copytree(self.REPO / "plugins" / "xp-plugin", plugin_root)
        data_root.mkdir(parents=True, exist_ok=True)
        repo = tmp_path / "repo"
        xp = repo / ".xp"
        xp.mkdir(parents=True, exist_ok=True)
        (xp / "config.yml").write_text((self.SHIPPED / "config.yml").read_text())
        (xp / "constraints.md").write_text(constraints)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        try:
            result = subprocess.run(
                [sys.executable, str(plugin_root / "scripts" / "session_start.py")],
                input=json.dumps({"cwd": str(repo), "session_id": "s", "source": "startup"}),
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": str(data_root),
                    "XP_DATA": str(data_root),
                    # PINNED, not inherited from the hook's `get("XP_ROLE", "lead")`
                    # default: bug 10ecc92e records that default as constraint 15's
                    # absence-is-not-a-state, so the day it is corrected the role gate
                    # returns its teammate line here and all three callers below red
                    # blaming the byte budget for a profile that was never built.
                    "XP_ROLE": "lead",
                },
                cwd=repo,
                capture_output=True,
                text=True,
            )
        finally:
            shutil.rmtree(base, ignore_errors=True)
        assert result.returncode == 0, result.stderr
        assert not result.stderr, result.stderr
        # run_hook is ADVISORY: a hook that raises exits 0 with the traceback on
        # stderr and NOTHING on stdout, which every byte-budget assertion below
        # reads as "no warning" rather than as a crash (constraint 2).
        assert result.stdout, "the hook printed nothing; stderr holds the traceback"
        assert "teammate session" not in result.stdout, "the role gate ate the profile"
        return result.stdout

    def test_a_file_over_the_session_budget_still_passes_the_character_wall(self, tmp_path):
        cap = self.cap_value(self.SHIPPED / "config.yml")
        seed = "# Constraints\n\n" + "\n".join(f"{n}. **Rule {n}**" for n in range(1, 16))
        constraints = seed + "x" * (6_000 - len(seed))
        # The two walls can only be shown independent where the byte allowance is
        # BELOW the character cap, and at the budgeted path it no longer is: story-131
        # bought back the banner's duplicate root. A longer path buys the gap instead.
        match = BUDGET_WARNING.search(
            self._run_ascii_profile(
                tmp_path, constraints, plugin_path_budget=self.PLUGIN_PATH_BUDGET + 100
            )
        )
        assert match, "the constructed profile did not report its SessionStart byte budget"
        overage, allowance = map(int, match.groups())
        assert overage == len(constraints.encode()) - allowance
        size = allowance + 1
        assert allowance < size <= cap
        wall = tmp_path / "wall"
        wall.mkdir()
        result = self.run_constraints_wall(wall, cap, size)
        assert result.returncode == 0, result.stderr

    def test_ascii_constraints_at_the_full_cap_fit_the_byte_profile(self, tmp_path):
        """PROCESS.md and every other document in the lead injection are walled
        HERE, which is why none of them carries a character cap of its own.

        THE INSTALL NOTICE IS SILENT IN THIS PROFILE — no harness variable is set,
        so install_status reports "ambiguous" and renders nothing — while a real
        stale install renders AHEAD of the constraints. The true bound is
        therefore LOWER than this one, so the margin this leaves is not room to
        spend: re-measure against the case at hand, never cite this test's.
        """
        from session_start import OUTPUT_CAP

        cap = self.cap_value(self.SHIPPED / "config.yml")  # never a literal: the
        seed = (self.SHIPPED / "constraints.md").read_text()  # cap is what moves
        oversized = seed + "x" * (6_000 - len(seed))
        match = BUDGET_WARNING.search(self._run_ascii_profile(tmp_path, oversized))
        assert match, "the oversized probe reported no constraints byte budget"
        overage, allowance = map(int, match.groups())
        assert overage == len(oversized.encode()) - allowance
        # A FLOOR, not a fact: every byte of shipped prose comes out of the adopter's
        # allowance, and 4,576 is what a file at the 4,500-CHARACTER wall can still be
        # told about AT THIS HARNESS'S 110-character plugin path. Under it, the two
        # numbers a project sees drift further apart than this story left them, so the
        # shipped prose is what to cut — not this number.
        assert allowance >= 4_576, (
            f"shipped prose has taken the adopter's constraints budget down to {allowance}"
            " bytes; shorten VALUES/JUDGMENT/PROCESS or the banner, do not lower this floor"
        )
        ceiling = seed + "x" * (cap - len(seed))
        assert len(ceiling) == cap
        out = self._run_ascii_profile(tmp_path, ceiling)
        assert len(out.encode()) <= OUTPUT_CAP
        assert ceiling in out, "the shipped character ceiling does not reach the lead whole"
        assert not BUDGET_WARNING.search(out)
        assert "[truncated at" not in out

    def test_the_warning_does_not_cost_the_constraints_it_reports_on(self, tmp_path):
        """constraints_budget subtracts a WORST-CASE warning, so the first file
        that triggers the warning must still deliver every rule. Pinned as that
        PROPERTY and not as the arithmetic (constraint 11): the round-1 reviewer
        measured that `one_byte_overage`, `strict_render_and_print_newline` and
        the `join` term can EACH be deleted with the whole profile suite still
        green, because ~33 bytes of accidental slack in the worst-case string
        holds the boundary instead. The reserve was load-bearing and unpinned at
        the same time, which is constraint 2's shape.

        At the allowance the profile is whole and silent; one byte over it warns
        and stays whole. The sibling full-cap case pins the adopter-facing ceiling.
        """
        from session_start import OUTPUT_CAP

        seed = (self.SHIPPED / "constraints.md").read_text()
        oversized = seed + "x" * (6_000 - len(seed))
        probe = BUDGET_WARNING.search(self._run_ascii_profile(tmp_path, oversized))
        assert probe, "the probe profile reported no byte budget to derive the allowance from"
        allowance = int(probe.groups()[1])
        over = seed + "x" * (allowance - len(seed.encode()) + 1)
        assert len(over.encode()) == allowance + 1, "the fixture is not one byte over"
        out = self._run_ascii_profile(tmp_path, over)
        assert BUDGET_WARNING.search(out), "one byte over the allowance did not warn"
        assert over in out, "the warning displaced the very constraints it reports on"
        assert "truncated at the" not in out, "the warning pushed the profile over the cap"
        assert len(out.encode()) <= OUTPUT_CAP
