"""Role install preflight cases collected through test_review.py."""

import json

import pytest
from spawn_helpers import stub_codex
from sprint_helpers import bundles, make_repo, sprint, staged_stub

ROLES = """release: sprint
roles:
  reviewer: claude/opus
  finder: claude/opus
  verifier: claude/opus
  fixer: codex/gpt-5.6-sol
  closer: codex/gpt-5.6-sol
tests:
  full: true
"""


def plugin_list(tmp_path, harness, records):
    path = tmp_path / "bin" / harness
    count = tmp_path / f"{harness}-plugin-list"
    payload = {"installed": records} if harness == "codex" else records
    probe = (
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        f"    open({str(count)!r}, 'a').write('1\\n')\n"
        f"    print({json.dumps(json.dumps(payload))}); sys.exit()\n"
    )
    needle = (
        "if sys.argv[1:] == ['plugin', 'list', '--json']: sys.exit(1)"
        if harness == "claude"
        else "argv = sys.argv[1:]"
    )
    path.write_text(path.read_text().replace(needle, probe + needle))
    return count


def installed(harness, version="0.14.1"):
    key = "pluginId" if harness == "codex" else "id"
    item = {key: "xp-plugin@xp-plugin", "version": version}
    return item if harness == "codex" else item | {"scope": "user"}


class HarnessInstallCases:
    def harnesses(self, tmp_path, codex_records):
        staged_stub(tmp_path)
        stub_codex(
            tmp_path,
            commit=False,
            report={"fixed": [], "blocking": [], "noted": []},
            sandbox="danger-full-access",
        )
        claude = plugin_list(tmp_path, "claude", [installed("claude")])
        codex = plugin_list(tmp_path, "codex", codex_records)
        return claude, codex

    @pytest.mark.parametrize("option", [(), ("--dry-run",)])
    def test_a_late_role_without_the_plugin_refuses_before_the_first_launch(self, tmp_path, option):
        repo, env, _g = make_repo(tmp_path, config=ROLES)
        self.harnesses(tmp_path, [])
        r = sprint(repo, env, "review", *option)
        assert r.returncode == 2 and "codex plugin add xp-plugin@xp-plugin" in r.stderr
        assert bundles(tmp_path) == [], "a finder spent before the closer's refusal"

    def test_clean_roles_query_each_harness_once_and_stale_is_allowed(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, config=ROLES)
        counts = self.harnesses(tmp_path, [installed("codex", "99.0.0")])
        r = sprint(repo, env, "review")
        assert r.returncode == 0, r.stdout + r.stderr
        assert all(path.read_text().splitlines() == ["1"] for path in counts)
        assert "install xp-plugin" not in r.stdout + r.stderr
