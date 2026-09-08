import importlib.util
import json
import os
import shutil

import pytest
from stop_gate_helpers import SCRIPTS, failure_payload, repo_with_story, run_script

RUNNING_ROOT = SCRIPTS.parent
RUNNING_VERSION = json.loads((RUNNING_ROOT / ".claude-plugin" / "plugin.json").read_text())[
    "version"
]


def stop_payload():
    return {
        "session_id": "sess-1",
        "cwd": ".",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }


def seed_env(tmp_path, root="/stale/plugin", version="0.0.0"):
    path = tmp_path / "xp" / "env.json"
    path.write_text(
        json.dumps({"plugin_root": str(root), "plugin_version": version, "scratch": "kept"}) + "\n"
    )
    return path


def assert_running_pair(path):
    recorded = json.loads(path.read_text())
    assert recorded["plugin_root"] == str(RUNNING_ROOT)
    assert recorded["plugin_version"] == RUNNING_VERSION
    assert recorded["scratch"] == "kept"


class EnvRepointCases:
    @pytest.mark.parametrize("field", ["plugin_root", "plugin_version"])
    def test_a_lead_stop_repoints_each_differing_recorded_field(self, tmp_path, field):
        repo, _g = repo_with_story(tmp_path)
        values = {"plugin_root": str(RUNNING_ROOT), "plugin_version": RUNNING_VERSION}
        values[field] = "/stale/plugin" if field == "plugin_root" else "0.0.0"
        path = seed_env(tmp_path, values["plugin_root"], values["plugin_version"])

        result = run_script("stop_gate.py", stop_payload(), repo, tmp_path)

        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert_running_pair(path)

    @pytest.mark.parametrize("role", ["teammate", "reviewer", "plan-reviewer", "arbitrary", ""])
    def test_every_non_lead_role_leaves_env_byte_identical(self, tmp_path, role):
        repo, _g = repo_with_story(tmp_path)
        path = tmp_path / "xp" / "env.json"
        path.write_bytes(b'{  "plugin_root": "/stale/plugin", "plugin_version": "0.0.0"  }\n\n')
        before = path.read_bytes()

        result = run_script(
            "stop_gate.py", stop_payload(), repo, tmp_path, extra_env={"XP_ROLE": role}
        )

        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert path.read_bytes() == before

    def test_a_current_pair_does_not_write(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        path = seed_env(tmp_path, RUNNING_ROOT, RUNNING_VERSION)
        known_mtime = 1_600_000_000_123_456_789
        os.utime(path, ns=(known_mtime, known_mtime))

        result = run_script("stop_gate.py", stop_payload(), repo, tmp_path)

        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert path.stat().st_mtime_ns == known_mtime

    def test_repoint_and_red_verify_gate_are_independent(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        path = seed_env(tmp_path)
        silent = run_script("stop_gate.py", stop_payload(), repo, tmp_path)
        assert_running_pair(path)
        assert silent.stdout == ""

        seed_env(tmp_path)
        run_script(
            "bash_status.py",
            failure_payload("pytest -q tests/test_x.py"),
            repo,
            tmp_path,
        )
        blocked = run_script("stop_gate.py", stop_payload(), repo, tmp_path)

        assert_running_pair(path)
        assert blocked.returncode == 0 and json.loads(blocked.stdout)["decision"] == "block"

    @pytest.mark.parametrize("failure", ["read", "write"])
    def test_repoint_failures_do_not_disable_a_red_verify(self, tmp_path, failure):
        repo, _g = repo_with_story(tmp_path)
        path = seed_env(tmp_path)
        assert run_script("stop_gate.py", stop_payload(), repo, tmp_path).returncode == 0
        assert_running_pair(path)
        seed_env(tmp_path)
        run_script(
            "bash_status.py",
            failure_payload("pytest -q tests/test_x.py"),
            repo,
            tmp_path,
        )

        protected = path if failure == "read" else path.parent
        original_mode = protected.stat().st_mode
        protected.chmod(0 if failure == "read" else 0o500)
        try:
            with pytest.raises(PermissionError):
                if failure == "read":
                    path.read_text()
                else:
                    (path.parent / "write-control").write_text("must fail")
            result = run_script("stop_gate.py", stop_payload(), repo, tmp_path)
        finally:
            protected.chmod(original_mode)

        assert result.returncode == 0
        assert json.loads(result.stdout)["decision"] == "block"

    def test_an_unreadable_running_manifest_never_repins(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        scratch_scripts = tmp_path / "plugin" / "scripts"
        shutil.copytree(SCRIPTS, scratch_scripts)
        scratch_root = scratch_scripts.parent
        path = seed_env(tmp_path, RUNNING_ROOT, RUNNING_VERSION)
        before = path.read_bytes()

        spec = importlib.util.spec_from_file_location(
            "scratch_stop_env", scratch_scripts / "env.py"
        )
        assert spec and spec.loader
        scratch_env = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scratch_env)
        assert scratch_env.plugin_version(scratch_root) == "unknown"

        result = run_script("stop_gate.py", stop_payload(), repo, tmp_path, scripts=scratch_scripts)

        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert json.loads(path.read_text())["plugin_version"] != "unknown"
        assert path.read_bytes() == before
