"""What `recover` says when a region has nothing to give.

Its own file because test_session_start.py sits AT constraint 8's 500-line cap:
extract, not scroll. Verify: pytest -q tests/test_session_recover.py"""

from session_start_helpers import run_recovery, xp_repo


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
