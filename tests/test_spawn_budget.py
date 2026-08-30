"""The teammate profile budget. Extracted from test_spawn_run.py at
story-021, which needed the room under constraint 8's 500-line cap for the
codex leg's tee ACs — the card's Verify names test_spawn_run.py."""

from pathlib import Path

from spawn_helpers import _total, make_repo, spawn, stub_claude


class TestBudget:
    """(i) is a hard cap on prose WE ship. There is deliberately no assertion on
    the composed total: CLAUDE.md, constraints.md and the cards belong to the
    consuming project, and a plugin gate over prose we do not own would red on
    someone else's file."""

    def test_plugin_shipped_profile_within_cap(self):
        from spawn import PLUGIN_SHIPPED_CAP, component_metadata_chars, plugin_shipped_chars

        # inner cap FIRST: a newly added skill or agent must red THIS line, not
        # the total — otherwise the ratchet blames TEAMMATE.md for a defect that
        # is a new component shipping unbudgeted prose into every spawn
        components = component_metadata_chars() // 4
        assert components <= 300, (
            f"always-on component metadata is {components} tokens (cap 300) —"
            " a skill or agent grew; retire prose there, not in TEAMMATE.md"
        )
        shipped = plugin_shipped_chars() // 4
        assert shipped <= PLUGIN_SHIPPED_CAP, (
            f"plugin-shipped profile is {shipped} tokens (cap {PLUGIN_SHIPPED_CAP});"
            f" components account for {components}"
        )

    def test_composed_total_is_computed_not_printed(self, tmp_path):
        """A print-a-constant implementation passes 'it prints a total' forever."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        before = spawn(repo, env, "story-042", "--dry-run").stdout
        plan = tmp_path / "data" / "plan.md"
        # the lead's whole sequence after changing a cleared card: edit, back to
        # [planned], re-review, re-mint — an edit alone now refuses the spawn
        plan.write_text(
            plan.read_text()
            .replace("Context: demo.", "Context: " + "x" * 4000)
            .replace("[ready]", "[planned]")
        )
        assert spawn(repo, env, "ready", "story-042").returncode == 0
        after = spawn(repo, env, "story-042", "--dry-run").stdout
        assert _total(before) != _total(after)
        assert _total(after) > _total(before)

    def test_printed_plugin_shipped_is_the_capped_quantity(self, tmp_path):
        """Two computations shipped under one name: the printed figure omitted
        templates/constraints.md, so a lead read ~300 tokens of headroom where
        the ratchet had 52 — the story-009 note's failure, in the instrument."""
        from spawn import PLUGIN_SHIPPED_CAP, plugin_shipped_chars

        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        out = spawn(repo, env, "story-042", "--dry-run").stdout
        assert f"plugin-shipped {plugin_shipped_chars() // 4}/{PLUGIN_SHIPPED_CAP}" in out

    def test_warning_names_the_largest_project_owned_contributor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        quiet = spawn(repo, env, "story-042", "--dry-run")
        assert "over the" not in quiet.stderr

        (repo / ".xp" / "constraints.md").write_text("# Constraints\n" + "bloat\n" * 3000)
        loud = spawn(repo, env, "story-042", "--dry-run")
        assert "constraints.md" in loud.stderr and "over the" in loud.stderr
        assert loud.returncode == 0  # reports, never refuses: the project's tradeoff

    def test_an_inherited_handoff_is_a_contributor_the_breakdown_names(self, tmp_path):
        """It is the only contributor that grows while every file the breakdown
        lists holds still, so omitting it blames a 34-token card for the overage
        and the lead cannot find the tokens. Listed only when there IS one."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert "predecessor handoff" not in spawn(repo, env, "story-042", "--dry-run").stdout

        plans = Path(env["XP_DATA"]) / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        (plans / "story-042.handoff.json").write_text('{"why": "no commits", "records": []}')
        (plans / "story-042.plan.md").write_text("PLAN\n" + "bloat\n" * 3000)
        loud = spawn(repo, env, "story-042", "--dry-run")
        assert "predecessor handoff" in loud.stdout, loud.stdout
        assert "predecessor handoff" in loud.stderr and "over the" in loud.stderr, loud.stderr

    def test_project_owned_absences_stay_tolerant_at_each_consumer(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        (repo / ".xp" / "constraints.md").unlink()
        r = spawn(repo, env, "story-042", "--dry-run")
        missing_constraints = "(missing: .xp/constraints.md)"
        missing_claude = "(missing: CLAUDE.md)"
        assert r.returncode == 0
        expected = [
            missing_constraints,
            f"constraints.md {len(missing_constraints) // 4}",
            f"CLAUDE.md {len(missing_claude) // 4}",
        ]
        assert not [item for item in expected if item not in r.stdout]
