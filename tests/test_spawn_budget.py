"""The teammate profile report. Extracted from test_spawn_run.py at
story-021, which needed the room under constraint 8's 500-line cap for the
codex leg's tee ACs — the card's Verify names test_spawn_run.py."""

import shutil
from pathlib import Path

import pytest
from spawn_helpers import _total, make_repo, seed_refresh_receipt, spawn, stub_claude


class TestProfile:
    def test_new_agent_frontmatter_is_included_in_component_metadata(self, tmp_path, monkeypatch):
        import spawn as spawn_module

        root = tmp_path / "plugin"
        shutil.copytree(spawn_module.PLUGIN_ROOT, root)
        monkeypatch.setattr(spawn_module, "PLUGIN_ROOT", root)
        before = spawn_module.component_metadata_chars()
        charter = root / "agents" / "new-role.md"
        charter.write_text("---\nname: new-role\ntools: Read\n---\n# New role\n")
        frontmatter = charter.read_text().split("---", 2)[1]
        assert spawn_module.component_metadata_chars() == before + len(frontmatter)

    def test_JUDGMENT_is_injected_counted_and_required(self, tmp_path, monkeypatch):
        import spawn as spawn_module

        monkeypatch.setenv("XP_DATA", str(tmp_path))  # so the only SystemExit below is the read
        root = tmp_path / "plugin"
        shutil.copytree(spawn_module.PLUGIN_ROOT, root)
        monkeypatch.setattr(spawn_module, "PLUGIN_ROOT", root)
        judgment = root / "JUDGMENT.md"
        assert judgment.exists(), "the universal document is absent"
        prompt = spawn_module.build_prompt(
            spawn_module.teammate_sections("card", "story-042", "", root)
        )
        assert "## JUDGMENT\n\n" in prompt and "Polarity" in prompt
        before = spawn_module.plugin_shipped_chars()
        judgment.write_text(judgment.read_text() + "four")
        assert spawn_module.plugin_shipped_chars() == before + 4
        judgment.unlink()
        with pytest.raises(SystemExit):
            spawn_module.teammate_sections("card", "story-042", "", root)

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
        seed_refresh_receipt(repo, env, "story-042")
        assert spawn(repo, env, "ready", "story-042").returncode == 0
        after = spawn(repo, env, "story-042", "--dry-run").stdout
        assert _total(before) != _total(after)
        assert _total(after) > _total(before)

    def test_printed_plugin_shipped_is_the_computed_quantity(self, tmp_path):
        """Two computations shipped under one name: the printed figure omitted
        templates/constraints.md, so a lead read ~300 tokens of headroom where
        the ratchet had 52 — the story-009 note's failure, in the instrument."""
        from spawn import plugin_shipped_chars

        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        out = spawn(repo, env, "story-042", "--dry-run").stdout
        assert f"plugin-shipped {plugin_shipped_chars() // 4}" in out
        assert f"plugin-shipped {plugin_shipped_chars() // 4}/" not in out

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
        """Listed only when there IS one, and named as the largest when it is:
        an overage the breakdown cannot attribute blames a 34-token card, and the
        lead goes looking for tokens that are not in any file it lists."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert "predecessor handoff" not in spawn(repo, env, "story-042", "--dry-run").stdout

        plans = Path(env["XP_DATA"]) / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        why = "bloat\\n" * 3000
        (plans / "story-042.handoff.json").write_text(f'{{"why": "{why}", "records": []}}')
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
