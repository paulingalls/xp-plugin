"""Role install preflight cases collected through test_review.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from close_helpers import CONFIG as STORY_CONFIG
from close_helpers import close
from close_helpers import make_repo as story_repo
from spawn_helpers import make_repo as plan_repo
from spawn_helpers import stub_codex
from sprint_helpers import bundles, make_repo, sprint, staged_stub

PLAN_REVIEW = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "plan_review.py"

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


def plugin_list(tmp_path, harness, records, response=""):
    path = tmp_path / "bin" / harness
    count = tmp_path / f"{harness}-plugin-list"
    payload = {"installed": records} if harness == "codex" else records
    answer = response or f"print({json.dumps(json.dumps(payload))}); sys.exit()"
    probe = (
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        f"    open({str(count)!r}, 'a').write('1\\n')\n"
        f"    {answer}\n"
    )
    needle = (
        "if sys.argv[1:] == ['plugin', 'list', '--json']: print("
        '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()'
        if harness == "claude"
        else "if argv == ['plugin', 'list', '--json']: print("
        '\'{"installed":[{"pluginId":"xp-plugin@xp-plugin",'
        '"version":"fixture"}]}\'); sys.exit()'
    )
    path.write_text(path.read_text().replace(needle, probe))
    return count


def installed(harness, version="0.14.1"):
    key = "pluginId" if harness == "codex" else "id"
    item = {key: "xp-plugin@xp-plugin", "version": version}
    return item if harness == "codex" else item | {"scope": "user"}


class HarnessInstallCases:
    def harnesses(self, tmp_path, codex_records, response=""):
        staged_stub(tmp_path)
        stub_codex(
            tmp_path,
            commit=False,
            report={"fixed": [], "blocking": [], "noted": []},
            sandbox="danger-full-access",
        )
        claude = plugin_list(tmp_path, "claude", [installed("claude")])
        codex = plugin_list(tmp_path, "codex", codex_records, response)
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

    @pytest.mark.parametrize(
        "response",
        ["sys.exit(7)", "print('not json'); sys.exit()", "print('[1]'); sys.exit()"],
    )
    def test_an_unreadable_install_probe_refuses_before_any_launch(self, tmp_path, response):
        repo, env, _g = make_repo(tmp_path, config=ROLES)
        self.harnesses(tmp_path, [], response)
        r = sprint(repo, env, "review", "--dry-run")
        assert r.returncode == 2 and "plugin state is unreadable" in r.stderr
        assert "codex plugin list --json" in r.stderr
        assert bundles(tmp_path) == []

    def test_a_timed_out_install_probe_is_not_proof_of_installation(self, monkeypatch):
        import harness
        import session_start

        def expired(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(["codex", "plugin", "list", "--json"], 8)

        monkeypatch.setattr(harness.shutil, "which", lambda _name: "/fixture/codex")
        monkeypatch.setattr(session_start.subprocess, "run", expired)
        refusal = harness.missing_harness("codex")
        assert "plugin state is unreadable" in refusal
        assert "codex plugin list --json" in refusal

    def test_a_story_review_dry_run_refuses_where_it_used_to_preview(self, tmp_path):
        """The hoist reaches close.py's dry-run branch, which returns 0 without
        reading review.run's error: the refusal arrived as silence under exit 0."""
        repo, env, g = story_repo(tmp_path)
        spec = STORY_CONFIG.replace("claude/opus", "codex/gpt-5.6-sol")
        (repo / ".xp" / "config.yml").write_text(spec)
        g("add", "-A")
        g("commit", "-qm", "point the reviewer at a harness this machine lacks")
        r = close(repo, env, "review", "--dry-run")
        assert r.returncode == 2, f"{r.returncode}: {r.stdout!r} {r.stderr!r}"
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr

    def test_a_plan_review_dry_run_refuses_where_it_used_to_preview(self, tmp_path):
        """The same swallow, in the leg an EXECUTOR runs — and the copy that would
        have kept previewing after close.py stopped."""
        repo, env, _g = plan_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\nroles:\n  plan-reviewer: codex/gpt-5.6-sol\ntests:\n  story: true\n"
        )
        (draft := tmp_path / "draft.md").write_text("PLAN-SENTINEL\n")
        r = subprocess.run(
            [sys.executable, str(PLAN_REVIEW), "story-042", str(draft), "--dry-run"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2, f"{r.returncode}: {r.stdout!r} {r.stderr!r}"
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr
