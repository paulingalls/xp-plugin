"""The teammate profile report. Extracted from test_spawn_run.py at
story-021, which needed the room under constraint 8's 500-line cap for the
codex leg's tee ACs — the card's Verify names test_spawn_run.py."""

import shutil
from pathlib import Path

import pytest
from spawn_helpers import _total, make_repo, seed_refresh_receipt, spawn, stub_claude


def set_card(repo, env, text):
    plan = Path(env["XP_DATA"]) / "plan.md"
    changed = plan.read_text().replace("Context: demo.", f"Context: {text}")
    plan.write_text(changed.replace("[ready]", "[planned]"))
    seed_refresh_receipt(repo, env, "story-042")
    assert spawn(repo, env, "ready", "story-042").returncode == 0


def set_target(repo, value):
    config = repo / ".xp" / "config.yml"
    config.write_text(config.read_text() + f"profile_target: {value}\n")


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

    def test_a_configured_profile_target_controls_the_card_note(self, tmp_path):
        low, low_env, _g = make_repo(tmp_path / "low")
        high, high_env, _g = make_repo(tmp_path / "high")
        stub_claude(tmp_path / "low")
        stub_claude(tmp_path / "high")
        set_card(low, low_env, "evidence " * 600)
        set_card(high, high_env, "evidence " * 600)
        set_target(low, 100)
        set_target(high, 2000)

        loud = spawn(low, low_env, "story-042", "--dry-run")
        quiet = spawn(high, high_env, "story-042", "--dry-run")
        assert loud.returncode == quiet.returncode == 0
        assert "100 story-card token allowance" in loud.stderr
        assert "profile_target" not in quiet.stderr

    def test_a_missing_profile_target_uses_the_documented_default(self, tmp_path):
        from spawn import DEFAULT_PROFILE_TARGET, PLUGIN_ROOT

        repo, env, _g = make_repo(tmp_path / "loud")
        quiet_repo, quiet_env, _g = make_repo(tmp_path / "quiet")
        stub_claude(tmp_path / "loud")
        stub_claude(tmp_path / "quiet")
        set_card(repo, env, "evidence " * 450)
        result = spawn(repo, env, "story-042", "--dry-run")
        quiet = spawn(quiet_repo, quiet_env, "story-042", "--dry-run")
        scaffold = next(
            line
            for line in (PLUGIN_ROOT / "templates/config.yml").read_text().splitlines()
            if line.startswith("profile_target:")
        )
        assert int(scaffold.split("#", 1)[0].split(":", 1)[1]) == DEFAULT_PROFILE_TARGET
        assert f"{DEFAULT_PROFILE_TARGET} story-card token allowance" in result.stderr
        assert "profile_target" not in quiet.stderr
        assert result.returncode == quiet.returncode == 0

    @pytest.mark.parametrize("value, received", [("many", "'many'"), ("", "empty")])
    def test_a_declared_malformed_profile_target_refuses(self, tmp_path, value, received):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_target(repo, value)
        result = spawn(repo, env, "story-042", "--dry-run")
        assert result.returncode == 2
        assert ".xp/config.yml" in result.stderr
        assert received in result.stderr
        assert "non-negative integer" in result.stderr
        assert "story-card tokens" in result.stderr
        assert "profile:" not in result.stdout

    def test_printed_plugin_share_is_of_the_composed_total(self, tmp_path, monkeypatch):
        import spawn as spawn_module

        repo, env, _g = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        card = (Path(env["XP_DATA"]) / "plan.md").read_text().split("#### story-042", 1)[1]
        card = "#### story-042" + card
        prompt = spawn_module.build_prompt(
            spawn_module.teammate_sections(card, "story-042", "", spawn_module.PLUGIN_ROOT)
        )
        constraints_chars = len(spawn_module._read(Path(".xp/constraints.md")))
        claude_chars = len(spawn_module._read(Path("CLAUDE.md")))
        project_chars = len(card) + constraints_chars + claude_chars
        total_chars = len(prompt) + claude_chars + spawn_module.component_metadata_chars()
        plugin_tokens = (total_chars - project_chars) // 4
        total_tokens = total_chars // 4
        before, _warning = spawn_module.profile_report(card, prompt, "")
        assert f"plugin share {plugin_tokens}/{total_tokens}" in before

        root = tmp_path / "plugin"
        shutil.copytree(spawn_module.PLUGIN_ROOT, root)
        monkeypatch.setattr(spawn_module, "PLUGIN_ROOT", root)
        shipped_before = spawn_module.plugin_shipped_chars()
        constraints = root / "templates/constraints.md"
        constraints.write_text(constraints.read_text() + "package only")
        after, _warning = spawn_module.profile_report(card, prompt, "")
        assert spawn_module.plugin_shipped_chars() > shipped_before
        assert after == before

    def test_the_note_names_the_plugin_when_its_actual_share_is_largest(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_target(repo, 0)
        (repo / ".xp/constraints.md").unlink()
        (repo / "CLAUDE.md").unlink(missing_ok=True)
        result = spawn(repo, env, "story-042", "--dry-run")
        assert result.returncode == 0
        assert "plugin" in result.stderr.lower()
        assert "largest contributor" in result.stderr.lower()
        assert "yours" not in result.stderr
        assert "retire" not in result.stderr

    def test_a_checked_long_card_is_reported_without_being_called_waste(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_card(repo, env, "checked evidence " * 800)
        set_target(repo, 100)
        result = spawn(repo, env, "story-042", "--dry-run")
        note = result.stderr.lower()
        assert result.returncode == 0
        assert "the story card" in note and "largest contributor" in note
        assert "reconsider" in note and "allowance" in note
        assert all(word not in note for word in ("retire", "waste", "yours to"))

    def test_warning_names_the_largest_project_owned_contributor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        quiet = spawn(repo, env, "story-042", "--dry-run")
        assert "over the" not in quiet.stderr

        set_target(repo, 0)
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
        set_target(repo, 0)
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
