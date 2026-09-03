"""SessionStart diagnoses consumer configs that predate the shipped template."""

from session_start_helpers import HOOK, run_hook, xp_repo

TEMPLATE = HOOK.parent.parent / "templates" / "config.yml"


class TestConfigAge:
    def test_comparison_discovers_a_novel_nested_template_key_and_its_parent(self):
        from session_start import missing_template_keys

        missing = missing_template_keys(
            "roles:\n  future-reviewer: codex/future\n", "release: sprint\n"
        )
        assert missing == [
            ("roles", "roles:"),
            ("roles.future-reviewer", "  future-reviewer: codex/future"),
        ]

    def test_lead_profile_names_one_missing_key_once_with_its_line(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        current = TEMPLATE.read_text()
        # Found rather than spelled: the pin was the whole line INCLUDING its comment,
        # so an edit to that comment redded here as a missing key nobody had removed.
        (old_line,) = [ln for ln in current.splitlines(True) if ln.startswith("  plan-reviewer:")]
        stale = current.replace(old_line, "")
        (repo / ".xp" / "config.yml").write_text(stale)

        out = run_hook(repo, tmp_path).stdout

        assert out.count("roles.plan-reviewer") == 1
        # Comment-STRIPPED, which is what the lead is told to paste back.
        assert ".xp/config.yml" in out and f"`{old_line.split('#')[0].rstrip()}`" in out

    def test_lead_profile_is_silent_for_the_complete_shipped_config(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(TEMPLATE.read_text())

        assert "config.yml is missing shipped keys" not in run_hook(repo, tmp_path).stdout

    def test_lead_profile_is_silent_when_config_is_absent(self, tmp_path):
        repo, _g = xp_repo(tmp_path)

        assert "config.yml is missing shipped keys" not in run_hook(repo, tmp_path).stdout
