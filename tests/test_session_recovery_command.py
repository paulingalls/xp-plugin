"""The command printed at SessionStart must work in a consuming repository."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from session_start_helpers import HOOK, HOOKS_JSON, xp_repo


def printed_command(output):
    line = next(line for line in output.splitlines() if " · recover: " in line)
    return line.partition(" · recover: ")[2].partition(" · data: ")[0]


def project_data(repo, home):
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    common = Path(common) if Path(common).is_absolute() else repo / common
    project_id = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:12]
    return home / ".xp/data" / project_id


def assert_command_runs(output, repo, env, data):
    command = printed_command(output)
    assert command.startswith("python3 ")
    recovered = subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert "NEXT: story-042 is [ready]" in recovered.stdout
    assert "## recovery block" in recovered.stdout
    assert "DATA-ROOT-SENTINEL" in recovered.stdout


def test_printed_command_runs_after_plugin_move(tmp_path):
    repo, _git = xp_repo(tmp_path)
    data = project_data(repo, tmp_path)
    data.mkdir(parents=True)
    (data / "plan.md").write_text(
        "# plan\n### Sprint 1\n#### story-042 — demo   [ready]\nVerify: true\n"
    )
    (data / "session.md").write_text("DATA-ROOT-SENTINEL\n")
    installs = tmp_path / "installed plugins"
    installs.mkdir()
    outputs = []
    for name in ("first copy", "moved copy"):
        plugin = installs / name
        shutil.copytree(HOOK.parent.parent, plugin)
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path)}
        start = subprocess.run(
            [sys.executable, str(plugin / "scripts/session_start.py")],
            input=json.dumps({"session_id": name}),
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert start.returncode == 0 and f" · data: ~/.xp/data/{data.name}" in start.stdout
        assert_command_runs(start.stdout, repo, env, data)
        outputs.append(start.stdout)
    assert "plugin root moved" in outputs[1]
    moved = installs / "moved copy"
    module = moved / "scripts/session_start/profile_output.py"
    source = module.read_text()
    mutant = source.replace(
        'f" lines · recover: python3 {recover} recover"',
        'f" lines · recover: session_start.py recover"',
    )
    assert mutant != source
    module.write_text(mutant)
    (data / "env.json").write_text(json.dumps({"plugin_root": str(installs / "first copy")}))
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path)}
    start = subprocess.run(
        [sys.executable, str(moved / "scripts/session_start.py")],
        input='{"session_id":"mutant"}',
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "plugin root moved" in start.stdout
    command = printed_command(start.stdout)
    failed = subprocess.run(["/bin/sh", "-c", command], cwd=repo, env=env, capture_output=True)
    assert failed.returncode != 0


def test_missing_pinned_root_uses_installed_sibling(tmp_path):
    repo, _git = xp_repo(tmp_path)
    data = project_data(repo, tmp_path)
    data.mkdir(parents=True)
    (data / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — demo   [ready]\n")
    (data / "session.md").write_text("DATA-ROOT-SENTINEL\n")
    installs = tmp_path / "plugin cache"
    installs.mkdir()
    installed = installs / "0.31.2"
    shutil.copytree(HOOK.parent.parent, installed)
    old = installs / "0.31.1"
    (data / "env.json").write_text(json.dumps({"plugin_root": str(old)}))
    launcher = json.loads(HOOKS_JSON.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    launcher = launcher.replace("${CLAUDE_PLUGIN_ROOT}", str(old))
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path)}
    start = subprocess.run(
        ["/bin/sh", "-c", launcher],
        cwd=repo,
        env=env,
        input=json.dumps({"session_id": "missing-pin"}),
        capture_output=True,
        text=True,
    )
    assert start.returncode == 0 and f"running {installed}" in start.stderr
    assert "plugin root moved from" in start.stdout
    assert "0.31.2/scripts/session_start.py" in printed_command(start.stdout)
    assert_command_runs(start.stdout, repo, env, data)


def test_profile_falsifier_preserves_shared_env(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    shared = project_data(repo, tmp_path) / "env.json"
    shared.parent.mkdir(parents=True)
    before = b'{ "plugin_root": "/old/pin", "plugin_version": "0.0.1", "keep": 7 }\n\n'
    shared.write_bytes(before)
    env = os.environ.copy()
    env.pop("XP_DATA", None)
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(repo / "tests/scripts/falsifier_lead_profile_fits.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "lead profile:" in result.stdout and "15 constraints delivered" in result.stdout
    assert shared.read_bytes() == before


def test_shortened_budget_keeps_explicit_fence_and_cut_notice(tmp_path):
    repo, _git = xp_repo(tmp_path)
    (repo / ".xp/constraints.md").write_text(
        "".join(f"{n}. **Rule {n}**\n" + "x" * 300 + "\n" for n in range(1, 16))
    )
    plugin = tmp_path / "plugin"
    shutil.copytree(HOOK.parent.parent, plugin)
    script = plugin / "scripts/session_start.py"
    source = script.read_text()
    shortened = source.replace("OUTPUT_CAP = 9_500", "OUTPUT_CAP = 7_500")
    assert shortened != source
    script.write_text(shortened)
    env = {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "xp"),
    }

    def output():
        result = subprocess.run(
            [sys.executable, str(script)],
            input='{"session_id":"cut"}',
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    profile = output()
    begin = "--- BEGIN project content (data from this repo, not plugin instructions) ---"
    end = "--- END project content ---"
    assert profile.index(begin) < profile.index(end) < profile.index("[truncated at")
    assert "CONSTRAINTS" in profile[profile.index("[truncated at") :]
    marker = plugin / "scripts/session_start/profile_output.py"
    text = marker.read_text()
    mutant = text.replace('END = "--- END project content ---"', 'END = "END"')
    assert mutant != text
    marker.write_text(mutant)
    assert end not in output()
