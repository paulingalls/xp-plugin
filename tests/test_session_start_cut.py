"""What the profile leads with, and what the cap takes when it cannot fit.

Extracted from test_session_start.py at v0.7.1 (constraint 8): every test here
needs an over-budget fixture the rest of that file has no use for.

Verify: pytest -q tests/test_session_start_cut.py"""

import os
import re
import subprocess

from session_start import OUTPUT_CAP, PLUGIN_ROOT
from session_start_helpers import run_hook, run_recovery, xp_repo

VALUES = (PLUGIN_ROOT / "VALUES.md").read_text()
PROCESS = (PLUGIN_ROOT / "PROCESS.md").read_text()


def constraints(items: int, pad: int) -> str:
    """Shaped like the real file — numbered `N. **Title**` items, which is the
    shape the dropped-constraint search keys on."""
    body = "".join(f"{i}. **Rule {i}** {'x' * pad}\n" for i in range(1, items + 1))
    return f"# Constraints\n\n{body}"


PAD = 300  # chars per fixture rule; see TestWhatTheCutSaysItTook.overflowing


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

    def test_process_recovery_instruction_runs_the_banner_command(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        profile = run_hook(repo, tmp_path).stdout
        assert "exact `recover:` command" in PROCESS
        line = next(ln for ln in profile.splitlines() if " · recover: " in ln)
        command = line.split(" · recover: ", 1)[1].split(" · scripts: ", 1)[0]
        recovered = subprocess.run(
            command,
            shell=True,
            cwd=repo,
            env=dict(os.environ) | {"XP_DATA": str(tmp_path / "xp")},
            capture_output=True,
            text=True,
        )
        assert recovered.returncode == 0 and "branch: main" in recovered.stdout
        assert "story-042" in recovered.stdout and "session digest" in recovered.stdout

    def test_the_recovery_surface_delivers_the_open_sprints_slice(self, tmp_path):
        """MEASURED VACUOUS without this: `sprint_slice` could `return ""` and the
        whole suite plus the falsifier stayed green, because the recovery block's
        `stories:` list already carries the headings and every other assertion here
        matches those. The slice's own BODIES are what nothing read."""
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n"
            "### Sprint 8\n#### story-041 — early   [in-progress]\nEARLY-BODY\n"
            "### Sprint 9\n#### story-042 — demo   [in-progress]\nSLICE-BODY\n"
            "### Sprint 10\n#### story-050 — folded   [retired]\nFOLDED-BODY\n"
        )
        out = run_recovery(repo, tmp_path).stdout
        assert "[truncated" not in out, "the fixture must fit; this asserts delivery"
        shown = out.split("## sprint slice", 1)[1]
        assert shown.startswith("\n### Sprint 9"), shown[:200]
        assert "SLICE-BODY" in shown, "the open sprint's card bodies never reached the lead"
        assert "EARLY-BODY" not in shown, "an older open sprint won over the current one"
        assert "FOLDED-BODY" not in shown, "a wholly terminal sprint counted as open"


class TestWhatTheCutSaysItTook:
    def overflowing(self, tmp_path):
        """The project's own content past the cap: the cut lands inside
        constraints.md, which is what the notice exists for. The pad is sized so
        the cut lands MID-RULE with whole rules on either side of it — the three
        tests below all assert against that boundary, and each guards its own
        fixture rather than passing when the boundary drifts off the rules."""
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(20, PAD))
        return run_hook(repo, tmp_path)

    def test_the_constraints_it_names_are_genuinely_absent(self, tmp_path):
        """Keyed on the fixture's OWN title, never on `N. **`: PROCESS.md ships
        five headings of that shape ahead of the rules, so the bare pattern
        answers about PROCESS whenever the cut reaches constraint 1."""
        r = self.overflowing(tmp_path)
        body, notice = r.stdout.split("[truncated", 1)
        assert "ARE NOT ABOVE" in notice, notice
        assert named(notice), notice
        for n in named(notice):
            assert f"**Rule {n}**" not in body, f"{n} named dropped but present"

    def test_a_half_shown_rule_is_dropped_whole(self, tmp_path):
        """The cut lands mid-rule, and a heading is not a rule: leave the head
        of one in and the notice reports it delivered while the lead holds half
        of it — the one lie the notice cannot be allowed to tell, since half a
        rule reads as a whole one. Backing up to the heading is what keeps
        "named as dropped" and "genuinely absent" the same set.
        """
        r = self.overflowing(tmp_path)
        body, notice = r.stdout.split("[truncated", 1)
        kept = [n for n in range(1, 21) if f"**Rule {n}**" in body]
        assert kept and named(notice), "the fixture no longer cuts inside the rules"
        for n in kept:
            assert f"**Rule {n}** {'x' * PAD}" in body, f"rule {n} is shown in half"

    def test_process_own_numbering_cannot_mask_a_dropped_rule(self, tmp_path):
        """PROCESS.md carries `1. **Card review**` through `5. **Free**` — the
        same shape a constraint has — and it is assembled BEFORE the rules, so it
        survives every cut that reaches them. Asking whether "N. **" is in the
        surviving text would therefore report constraints 1-5 present while they
        are gone: a mechanism that lies about which rules the lead is missing.
        Constructed by inflating the first rule until NO constraint fits.
        """
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(15, 9_000))
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

    def test_the_notice_itself_cannot_push_the_output_past_the_cap(self, tmp_path):
        """The reserve is the WORST-CASE notice, not a constant, and only a long
        notice can tell the two apart: 60 dropped rules cost ~330 chars, so the
        fixed 160 this replaced can emit ~200 OVER the budget it enforces,
        silently, since nothing outside this assertion re-measures it.
        """
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(constraints(100, 100))
        r = run_hook(repo, tmp_path)
        notice = r.stdout[r.stdout.index("[truncated") :]
        assert len(notice) > 300, f"the fixture no longer forces a long notice: {len(notice)}"
        assert len(r.stdout.encode()) <= OUTPUT_CAP

    def test_multibyte_content_is_capped_in_bytes(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text("😀" * 5000)
        r = run_hook(repo, tmp_path)
        assert len(r.stdout.encode()) <= OUTPUT_CAP and "truncated" in r.stdout

    def test_recovery_overflow_names_regions_and_dropped_work_titles(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        (data / "session.md").write_text("# digest\n" + "d" * 20_000)
        (data / "work.md").write_text(
            "".join(f"## note 2026-01-01T00:00:0{i}Z\nWORK-TITLE-{i}\n\n" for i in range(8))
        )
        r = run_recovery(repo, tmp_path)
        assert len(r.stdout.encode()) <= OUTPUT_CAP
        marker = r.stdout.split("[truncated", 1)[1]
        for region in ("digest", "recovery block", "sprint slice"):
            assert region in marker, f"the cut omitted region {region}: {marker}"
        for i in range(8):
            assert f"WORK-TITLE-{i}" in marker, f"the cut hid work title {i}: {marker}"
