"""The teammate profile budget. Extracted from test_spawn_run.py at
story-021, which needed the room under constraint 8's 500-line cap for the
codex leg's tee ACs — the card's Verify names test_spawn_run.py."""

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
