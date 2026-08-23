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
        old_line = (
            "  plan-reviewer: claude/opus   # scripts/plan_review.py; a teammate runs it itself\n"
        )
        stale = current.replace(old_line, "")
        (repo / ".xp" / "config.yml").write_text(stale)

        out = run_hook(repo, tmp_path).stdout

        assert out.count("roles.plan-reviewer") == 1
        assert ".xp/config.yml" in out and "`  plan-reviewer: claude/opus`" in out

    def test_lead_profile_is_silent_for_the_complete_shipped_config(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(TEMPLATE.read_text())

        assert "config.yml is missing shipped keys" not in run_hook(repo, tmp_path).stdout

    def test_lead_profile_is_silent_when_config_is_absent(self, tmp_path):
        repo, _g = xp_repo(tmp_path)

        assert "config.yml is missing shipped keys" not in run_hook(repo, tmp_path).stdout
