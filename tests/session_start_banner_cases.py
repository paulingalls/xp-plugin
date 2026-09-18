"""The SessionStart banner and the commands and paths it publishes."""

import ast
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from session_start import OUTPUT_CAP
from session_start_helpers import HOOK, run_hook, run_recovery, xp_repo


def banner_line(output):
    return next(line for line in output.splitlines() if " · recover: " in line)


def banner_recovery_executable(output):
    command = banner_line(output).partition(" · recover: ")[2].partition(" · scripts: ")[0]
    return Path(shlex.split(command)[1]).expanduser()


def banner_scripts_directory(output):
    first = output.splitlines()[0]
    if " · recover: " in first:
        return banner_recovery_executable(output).parent
    notice = next(line for line in output.splitlines() if "plugin root moved from" in line)
    return Path(ast.literal_eval(notice.rpartition(" to ")[2])).expanduser() / "scripts"


def run_banner_script(output, cwd, data_dir, script="work.py env"):
    requested = shlex.split(script)
    executable = banner_scripts_directory(output) / requested[0]
    return subprocess.run(
        [sys.executable, str(executable), *requested[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            "PATH": f"{Path(sys.executable).resolve().parent}:/usr/bin:/bin",
            "HOME": str(data_dir),
            "XP_DATA": str(data_dir / "xp"),
        },
    )


class BannerCases:
    def test_healthy_lead_banner_names_version_gates_and_data_root(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [ready]\nVerify: true\n"
        )
        r = run_hook(repo, tmp_path)
        manifest = HOOK.parent.parent / ".claude-plugin" / "plugin.json"
        version = json.loads(manifest.read_text())["version"]
        assert "NEXT: story-042 is [ready]" in run_recovery(repo, tmp_path).stdout
        assert "NEXT:" not in r.stdout
        assert "xp-plugin" in r.stdout and version in r.stdout
        assert "git hooks: none detected" in r.stdout
        assert " · data: ~/xp" in r.stdout.splitlines()[0]
        invoked = run_banner_script(r.stdout, repo, tmp_path)
        assert invoked.returncode == 0 and invoked.stdout.strip() == str(HOOK.parent.parent)

    def test_cut_profile_keeps_plugin_and_data_roots_in_the_first_line(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text("x" * (OUTPUT_CAP * 2))
        output = run_hook(repo, tmp_path).stdout
        assert "[truncated at" in output
        assert len(output.encode()) <= OUTPUT_CAP
        line = output.splitlines()[0]
        assert line.count(str(HOOK.parent.parent)) == 1
        assert " · data: ~/xp" in line

    def test_banner_locates_spawn_and_close(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        output = run_hook(repo, tmp_path).stdout
        line = banner_line(output)
        scripts = banner_recovery_executable(output).parent
        assert scripts == HOOK.parent
        for name in ("spawn.py", "close.py"):
            assert name in line
            assert (scripts / name).is_file()

    def test_a_failed_env_refresh_keeps_the_root_the_banner_trim_would_take(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "env.json").mkdir(parents=True)
        output = run_hook(repo, tmp_path).stdout
        notice = next(line for line in output.splitlines() if "refresh FAILED" in line)
        assert str(HOOK.parent.parent) not in notice, "the notice republished the root after all"
        assert banner_line(output).count(str(HOOK.parent.parent)) == 1
        # Both trim branches must carry the field; the case below covers the other tail.
        assert " · data: ~/xp" in output.splitlines()[0]
        ran = run_banner_script(output, repo, tmp_path, "session_start.py recover")
        assert ran.returncode == 0 and "branch: main" in ran.stdout, ran.stderr

    def test_banner_invocation_follows_a_moved_plugin_root(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        banners = []
        with tempfile.TemporaryDirectory(prefix="xp-banner-", dir="/tmp") as installs:
            for name in ("first", "moved"):
                plugin = Path(installs) / name
                shutil.copytree(HOOK.parent.parent, plugin)
                probe = plugin / "scripts" / "banner_probe.py"
                probe.write_text("print(__file__)\n")
                result = subprocess.run(
                    [sys.executable, str(plugin / "scripts" / "session_start.py")],
                    input=json.dumps({"session_id": name}),
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "HOME": str(tmp_path),
                        "XP_DATA": str(tmp_path / "xp"),
                    },
                )
                assert str(plugin) in result.stdout, "the moved root is published nowhere"
                assert " · data: ~/xp" in result.stdout.splitlines()[0]
                invoked = run_banner_script(result.stdout, repo, tmp_path, "banner_probe.py")
                assert invoked.returncode == 0 and invoked.stdout.strip() == str(probe)
                banners.append(result.stdout.splitlines()[0])
        assert banners[0] != banners[1]

    def test_home_paths_are_collapsed_and_both_banner_arms_execute(self, tmp_path, monkeypatch):
        repo, _g = xp_repo(tmp_path)
        home = tmp_path / "home with spaces"
        data = home / "xp"
        data.mkdir(parents=True)
        (data / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — demo   [ready]\n")
        monkeypatch.setenv("HOME", str(home))
        outputs = []
        for name in ("plugin one", "plugin moved"):
            plugin = home / name
            shutil.copytree(HOOK.parent.parent, plugin)
            probe = plugin / "scripts" / "banner_probe.py"
            probe.write_text("print(__file__)\n")
            result = subprocess.run(
                [sys.executable, str(plugin / "scripts" / "session_start.py")],
                input=json.dumps({"session_id": name}),
                cwd=repo,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "HOME": str(home), "XP_DATA": str(data)},
            )
            assert str(home) not in result.stdout
            assert " · data: ~/xp" in result.stdout.splitlines()[0]
            invoked = run_banner_script(result.stdout, repo, home, "banner_probe.py")
            assert invoked.returncode == 0 and invoked.stdout.strip() == str(probe)
            outputs.append(result.stdout)
        assert " · recover: python3 ~/" in outputs[0]
        assert " · recover: " not in outputs[1].splitlines()[0]
        assert "plugin root moved from '~/plugin one' to '~/plugin moved'" in outputs[1]
        recorded = json.loads((data / "env.json").read_text())
        assert recorded["plugin_root"] == str(home / "plugin moved")

    def test_paths_outside_home_remain_absolute(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        with tempfile.TemporaryDirectory(prefix="xp-outside-", dir="/tmp") as root:
            root = Path(root)
            home = root / "home"
            outside = root / "home-sibling"
            data = outside / "data"
            home.mkdir()
            data.mkdir(parents=True)
            (data / "plan.md").write_text("# plan\n### Sprint 1\n")
            outputs = []
            for name in ("first", "moved"):
                plugin = outside / name
                shutil.copytree(HOOK.parent.parent, plugin)
                result = subprocess.run(
                    [sys.executable, str(plugin / "scripts" / "session_start.py")],
                    input=json.dumps({"session_id": name}),
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    env={"PATH": "/usr/bin:/bin", "HOME": str(home), "XP_DATA": str(data)},
                )
                outputs.append(result.stdout)
            assert str(outside / "first") in outputs[0]
            assert str(data) in outputs[0].splitlines()[0]
            assert f"plugin root moved from {str(outside / 'first')!r}" in outputs[1]
            assert f"to {str(outside / 'moved')!r}" in outputs[1]

            failed = outside / "failed"
            failed.mkdir()
            (failed / "env.json").mkdir()
            failure = subprocess.run(
                [sys.executable, str(outside / "moved" / "scripts" / "session_start.py")],
                input=json.dumps({"session_id": "failed"}),
                cwd=repo,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "HOME": str(home), "XP_DATA": str(failed)},
            ).stdout
            assert repr(str(failed / "env.json")) in failure

    def test_codex_payload_refreshes_the_plugin_pointer(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        path = tmp_path / "xp" / "env.json"
        path.write_text(json.dumps({"plugin_root": "/gone", "plugin_version": "0.0.1"}))
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(
                {"session_id": "codex", "hook_event_name": "SessionStart", "source": "startup"}
            ),
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
            cwd=repo,
            capture_output=True,
            text=True,
        )
        recorded = json.loads(path.read_text())
        manifest = json.loads((HOOK.parent.parent / ".claude-plugin" / "plugin.json").read_text())
        assert recorded == {
            "plugin_root": str(HOOK.parent.parent),
            "plugin_version": manifest["version"],
        }
        invoked = run_banner_script(result.stdout, repo, tmp_path)
        assert invoked.returncode == 0 and invoked.stdout.strip() == str(HOOK.parent.parent)
