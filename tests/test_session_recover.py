"""What session recovery says when state is empty or names the next loop action.

Its own file because test_session_start.py sits AT constraint 8's 500-line cap:
extract, not scroll. Verify: pytest -q tests/test_session_recover.py"""

import pytest
from session_recover_next_cases import NextLoopActionCases, next_lines
from session_start_helpers import run_recovery, xp_repo


def sprint_slice(output):
    return output.split("## sprint slice\n", 1)[1].split("--- END project content ---", 1)[0]


class TestTheNextLoopAction(NextLoopActionCases):
    pass


class TestTheOpenSprintSelection:
    @staticmethod
    def plan(open_id="21"):
        return (
            f"# plan\n### Sprint {open_id}\n"
            "#### story-021 — open   [ready]\nOPEN-SENTINEL\n"
            "### Sprint 22\n#### story-022 — draft   [planned]\nDRAFT-SENTINEL\n"
        )

    def test_the_recorded_sprint_wins_over_a_higher_draft_and_reports_the_disagreement(
        self, tmp_path
    ):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(self.plan())
        (root / "sprint_branch").write_text("sprint-021\n")

        result = run_recovery(repo, tmp_path)
        shown = sprint_slice(result.stdout)

        assert result.returncode == 0, result.stderr
        assert "recorded branch sprint-021 selected plan Sprint 21" in shown
        assert "highest plan heading Sprint 22 disagrees" in shown
        assert "OPEN-SENTINEL" in shown and "DRAFT-SENTINEL" not in shown
        assert next_lines(result.stdout) == [
            "NEXT: story-021 is [ready] — run `spawn.py story-021`"
        ]

    @pytest.mark.parametrize("recorded", ["sprint-021-hotfix", "021", "release/sprint-021"])
    def test_a_record_that_is_not_a_sprint_branch_name_refuses_rather_than_guessing(
        self, tmp_path, recorded
    ):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(self.plan())
        (root / "sprint_branch").write_text(f"{recorded}\n")

        shown = sprint_slice(run_recovery(repo, tmp_path).stdout)

        if recorded.startswith("sprint-"):
            assert f"recorded branch {recorded} has no matching heading" in shown
        else:
            assert f"recorded branch {recorded} is not named sprint-N" in shown
        assert "OPEN-SENTINEL" not in shown and "DRAFT-SENTINEL" not in shown

    def test_no_recorded_sprint_uses_and_names_the_highest_numbered_fallback(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(self.plan())

        result = run_recovery(repo, tmp_path)
        shown = sprint_slice(result.stdout)

        assert result.returncode == 0, result.stderr
        assert (
            "no sprint branch recorded; highest-numbered fallback selected plan Sprint 22" in shown
        )
        assert "DRAFT-SENTINEL" in shown and "OPEN-SENTINEL" not in shown

    def test_a_recorded_sprint_absent_from_the_plan_refuses_instead_of_falling_back(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(self.plan())
        (root / "sprint_branch").write_text("sprint-023\n")

        recovery = run_recovery(repo, tmp_path)
        shown = sprint_slice(recovery.stdout)

        assert recovery.returncode == 0 and "sprint slice UNAVAILABLE" in shown
        assert "sprint-023 has no matching heading" in shown
        assert "Sprint 21, Sprint 22" in shown
        assert "OPEN-SENTINEL" not in shown and "DRAFT-SENTINEL" not in shown
        assert next_lines(recovery.stdout) == [
            "NEXT: recovery required — next-action state is unreadable: recorded branch "
            "sprint-023 has no matching heading in the plan; available headings: "
            "Sprint 21, Sprint 22"
        ]

    @pytest.mark.parametrize("open_id", ["021", "21"])
    def test_the_recorded_branch_matches_both_plan_padding_directions(self, tmp_path, open_id):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(self.plan(open_id))
        (root / "sprint_branch").write_text("sprint-021\n")

        shown = sprint_slice(run_recovery(repo, tmp_path).stdout)

        assert f"recorded branch sprint-021 selected plan Sprint {open_id}" in shown
        assert f"### Sprint {open_id}" in shown and "OPEN-SENTINEL" in shown
        assert "UNAVAILABLE" not in shown and "DRAFT-SENTINEL" not in shown

    def test_all_numerically_matching_sections_survive_mixed_padding(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            "# plan\n### Sprint 21\nFIRST-SECTION\n"
            "### Sprint 021\nSECOND-SECTION\n### Sprint 22\nDRAFT-SECTION\n"
        )
        (root / "sprint_branch").write_text("sprint-021\n")

        shown = sprint_slice(run_recovery(repo, tmp_path).stdout)

        assert "FIRST-SECTION" in shown and "SECOND-SECTION" in shown
        assert "DRAFT-SECTION" not in shown

    def test_an_empty_sprint_branch_record_costs_only_the_sprint_slice(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(self.plan())
        (root / "sprint_branch").write_text("")

        recovery = run_recovery(repo, tmp_path)

        assert recovery.returncode == 0
        assert "sprint slice UNAVAILABLE" in recovery.stdout
        assert "sprint_branch is empty" in recovery.stdout
        assert "## digest" in recovery.stdout and "## recovery block" in recovery.stdout
        assert len(next_lines(recovery.stdout)) == 1
        assert "sprint_branch is empty" in recovery.stdout


class TestARegionThatProducedNothing:
    """`recover` builds every region as `("<name>", "## <name>\n" + body)`, so the
    HEADING is always truthy: render's `if text` filter can never drop a region and
    the notice — which lists only regions the cut reached — never names one either.
    A region that produced nothing must therefore say so itself."""

    def test_a_dead_builder_names_its_cause_instead_of_a_bare_heading(self, tmp_path):
        """Fault-injected exactly as measured: plan.md replaced by a DIRECTORY.
        Before, `recover` printed bare `## recovery block` and `## sprint slice`
        headings with no notice and exit 0 — the lead reads that as "nothing open"."""
        repo, _g = xp_repo(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.unlink()
        plan.mkdir()
        r = run_recovery(repo, tmp_path)
        assert r.returncode == 0, r.stderr
        for region in ("recovery block", "sprint slice"):
            assert f"## {region}\n({region} UNAVAILABLE" in r.stdout, r.stdout
        assert str(plan) in r.stdout, "the cause is what the lead repairs"

    def test_an_empty_region_says_which_nothing_it_has(self, tmp_path):
        """Distinct states stay distinct: a plan carrying no `### Sprint` section is
        not a plan whose read blew up, and neither is a bare heading."""
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text("# plan with no sprint sections\n")
        r = run_recovery(repo, tmp_path)
        assert "## sprint slice\n(sprint slice: nothing recorded)" in r.stdout, r.stdout
        assert "UNAVAILABLE" not in r.stdout, "an empty region read as a failed one"
