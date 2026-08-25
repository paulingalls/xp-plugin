"""What the profile leads with, and what the cap takes when it cannot fit.

Extracted from test_session_start.py at v0.7.1 (constraint 8): every test here
needs an over-budget fixture the rest of that file has no use for.

Verify: pytest -q tests/test_session_start_cut.py"""

import re

from session_start import OUTPUT_CAP, PLUGIN_ROOT
from session_start_helpers import run_hook, xp_repo

VALUES = (PLUGIN_ROOT / "VALUES.md").read_text()
PROCESS = (PLUGIN_ROOT / "PROCESS.md").read_text()


def constraints(items: int, pad: int) -> str:
    """Shaped like the real file — numbered `N. **Title**` items, which is the
    shape the dropped-constraint search keys on."""
    body = "".join(f"{i}. **Rule {i}** {'x' * pad}\n" for i in range(1, items + 1))
    return f"# Constraints\n\n{body}"


def named(notice: str) -> list[int]:
    claim = notice.split("ARE NOT ABOVE")[0].split("CONSTRAINTS", 1)[-1]
    return [int(n) for n in re.findall(r"\b(\d+)\b", claim)]


class TestWhatTheProfileLeadsWith:
    """VALUES first, then PROCESS, and neither may be dropped (Paul, 2026-08-24):
    values set the stage for everything read after them, and the loop is how the
    work happens. They may be made smaller; they may not move or go."""

    def over_budget(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(15, 900))
        return run_hook(repo, tmp_path)

    def test_values_lead_the_profile_and_process_follows(self, tmp_path):
        r = self.over_budget(tmp_path)
        assert len(r.stdout) <= OUTPUT_CAP and "[truncated" in r.stdout
        assert r.stdout.index(VALUES[:60]) < r.stdout.index(PROCESS[:60])
        assert r.stdout.index(PROCESS[:60]) < r.stdout.index("BEGIN project content")

    def test_neither_is_dropped_by_a_cut(self, tmp_path):
        r = self.over_budget(tmp_path)
        assert VALUES in r.stdout and PROCESS in r.stdout


class TestWhatTheCutSaysItTook:
    def overflowing(self, tmp_path):
        """The project's own content past the cap: the cut lands inside
        constraints.md, which is what the notice exists for."""
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(20, 1500))
        return run_hook(repo, tmp_path)

    def test_the_constraints_it_names_are_genuinely_absent(self, tmp_path):
        r = self.overflowing(tmp_path)
        body, notice = r.stdout.split("[truncated", 1)
        assert "ARE NOT ABOVE" in notice, notice
        assert named(notice), notice
        for n in named(notice):
            assert not re.search(rf"^{n}\. \*\*", body, re.M), f"{n} named dropped but present"

    def test_process_own_numbering_cannot_mask_a_dropped_rule(self, tmp_path):
        """PROCESS.md carries `1. **Plan**` through `4. **Sprint close**` — the
        same shape a constraint has — and it is assembled BEFORE the rules, so it
        survives every cut that reaches them. Asking whether "N. **" is in the
        surviving text would therefore report constraints 1-4 present while they
        are gone: a mechanism that lies about which rules the lead is missing.
        Constructed by inflating the recovery block until NO constraint fits.
        """
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(15, 40))
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text(
            plan.read_text()
            + "".join(f"#### story-{i:03d} — filler {'y' * 90}   [ready]\n" for i in range(300))
        )
        r = run_hook(repo, tmp_path)
        notice = r.stdout[r.stdout.index("[truncated") :]
        assert "Rule 1**" not in r.stdout, "the fixture did not cut the constraints"
        assert set(named(notice)) == set(range(1, 16)), notice

    def test_the_project_block_is_terminated_even_when_the_cut_eats_its_end(self, tmp_path):
        """The notice is OURS. Unfenced, it renders inside a region the lead is
        told to treat as repo data."""
        r = self.overflowing(tmp_path)
        assert "BEGIN project content" in r.stdout and "END project content" in r.stdout
        assert r.stdout.index("END project content") < r.stdout.index("[truncated"), r.stdout[-300:]

    def test_recovery_block_survives_the_cap(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text("HUGE\n" * 5000)
        r = run_hook(repo, tmp_path)
        assert len(r.stdout) <= OUTPUT_CAP and "truncated" in r.stdout
        assert "story-042" in r.stdout
