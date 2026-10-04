"""Installed-shape review children with real Git commits and hooks."""

import json
from pathlib import Path

from close_helpers import make_repo


def flow_repo(
    tmp_path,
    harness="claude",
    scope="story",
    scenario="clean",
    verify="true",
    files="src/thing.py, .xp/config.yml",
):
    repo, env, git = make_repo(tmp_path, verify=verify, files=files)
    config = repo / ".xp/config.yml"
    config.write_text(
        f"roles:\n  executor: {harness}/model\n  reviewer: {harness}/model\n"
        f"  fixer: {harness}/model\n  closer: {harness}/model\ntests:\n  story: true\n"
    )
    git("add", ".xp/config.yml")
    git("commit", "-qm", "roles")
    key = "story-042"
    if scope == "free":
        key = "free-2026-10-03-demo"
        git("branch", "-m", "test/" + key)
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().replace("story-042", key))
        from close_helpers import mint_ready

        mint_ready(repo, env, key)
        from handoff import _write

        _write(Path(env["XP_DATA"]), key, {"state": "STOPPED"})
    from handoff import _write

    _write(Path(env["XP_DATA"]), key, {"state": "STOPPED"})
    events = tmp_path / "events"
    hooks = tmp_path / "hooks"
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(
        f"#!/bin/sh\necho hook >> {hooks}\n" + ("exit 1\n" if scenario == "hook-refusal" else "")
    )
    hook.chmod(0o755)
    script = """#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path
if 'plugin' in sys.argv[1:]:
    item={'id':'xp-plugin@xp-plugin','pluginId':'xp-plugin@xp-plugin','version':'fixture','scope':'user'}
    payload={'installed':[item]} if Path(sys.argv[0]).name=='codex' else [item]
    print(json.dumps(payload)); sys.exit()
prompt=sys.stdin.read()
stage=re.search(r'^STAGE: (.+)$',prompt,re.M)
stage=stage.group(1) if stage else 'solution'
Path(EVENTS+'.'+stage+'.prompt').write_text(prompt)
with open(EVENTS,'a') as f: f.write(stage+'\\n')
report={'blocking':[]}
if stage=='solution': report['actionable']=[] if SCENARIO=='clean' else ['A must equal 3']
if stage=='fixer':
    Path('src/thing.py').write_text('A = 3\\n')
    subprocess.run(['git','add','src/thing.py'],check=True)
    rc=subprocess.run(['git','commit','-qm','fix finding']).returncode
    if rc: sys.exit(rc)
if stage=='closer':
    assert Path('src/thing.py').read_text()=='A = 3\\n'
    assert 'A must equal 3' in prompt
    if SCENARIO=='closer-blocked': report['blocking']=['fixed value breaks concrete regression']
if SCENARIO=='malformed-'+stage: report.pop('blocking')
path=re.search(r'^REPORT_PATH: (.+)$',prompt,re.M).group(1)
Path(path).write_text(json.dumps(report))
if HARNESS=='claude':
    print(json.dumps({'type':'system','subtype':'init','session_id':'fixture'}))
    print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'complete'}))
else:
    print(json.dumps({'type':'thread.started','thread_id':'fixture'}))
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'complete'}}))
    print(json.dumps({'type':'turn.completed','usage':{}}))
"""
    script = (
        script.replace("EVENTS", repr(str(events)))
        .replace("SCENARIO", repr(scenario))
        .replace("HARNESS", repr(harness))
    )
    for name in ("claude", "codex"):
        executable = tmp_path / "bin" / name
        executable.write_text(script)
        executable.chmod(0o755)
    return repo, env, git, key, events, hooks


def invoke(repo, env, key, action="review", *extra):
    import os
    import subprocess
    import sys

    from close_helpers import CLOSE

    CLOSE = Path(os.environ.get("XP_FLOW_TEST_CLOSE", str(CLOSE)))

    args = ["free", "demo"] if key.startswith("free-") else ["story", key]
    return subprocess.run(
        [sys.executable, str(CLOSE), *args, action, *extra],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def checkpoint(env, key):
    return json.loads((Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json").read_text())[
        "checkpoint"
    ]["review_sequence"]


def measured_flow(root, plugin, scenario="fixed", extra=0):
    import json
    from pathlib import Path

    root.mkdir()
    repo, env, git, key, events, hooks = flow_repo(root, scenario=scenario)
    seed_clean_files(repo, git, hooks, extra)
    import pytest

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XP_FLOW_TEST_CLOSE", str(plugin / "scripts/close.py"))
        result = invoke(repo, env, key)
        assert result.returncode == (2 if scenario.startswith("malformed") else 0), result.stderr
        if scenario.startswith("malformed"):
            prior = checkpoint(env, key)
            report = Path(prior["stages"]["fixer"]["path"])
            saved = report.read_bytes()
            binary = root / "bin/claude"
            binary.write_text(
                binary.read_text()
                .replace("'malformed-fixer'", "'fixed'")
                .replace(
                    "if stage=='fixer':",
                    "if stage=='fixer' and 'Correct only the incomplete report' not in prompt:",
                )
            )
            assert invoke(repo, env, key).returncode == 0
            assert report.read_bytes() == saved
        sequence = checkpoint(env, key)
    assert (repo / "src/thing.py").read_text() == "A = 3\n"
    assert hooks.read_text().splitlines() == ["hook"]
    handoff = Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json"
    sizes = {
        "handoff": len(handoff.read_bytes()),
        "checkpoint": len(json.dumps(json.loads(handoff.read_text())["checkpoint"]).encode()),
        "sequence": len(json.dumps(sequence).encode()),
    }
    for stage in ("solution", "fixer", "closer"):
        sizes[stage] = len(Path(str(events) + "." + stage + ".prompt").read_bytes())
    return sizes


def seed_clean_files(repo, git, hooks, extra):
    branch = git("branch", "--show-current").stdout.strip()
    assert git("checkout", "-q", "main").returncode == 0
    for index in range(extra):
        (repo / f"unrelated-{index:03}.bin").write_bytes(bytes(range(256)) * 10)
    (repo / "asset.bin").write_bytes(bytes(range(256)))
    assert git("add", ".").returncode == 0
    assert git("commit", "-qm", "tracked fixture base").returncode == 0
    assert git("checkout", "-q", branch).returncode == 0
    assert git("merge", "-qm", "fixture base", "main").returncode == 0
    (repo / "asset.bin").write_bytes(bytes(reversed(range(256))))
    assert git("commit", "-qam", "binary story change").returncode == 0
    hooks.unlink()


def installed_pair(tmp_path):
    import io
    import shutil
    import subprocess
    import tarfile

    from plan_review_install import PLUGIN

    archive = subprocess.check_output(["git", "archive", "62d4034", "plugins/xp-plugin"])
    old = tmp_path / "old-copy"
    with tarfile.open(fileobj=io.BytesIO(archive)) as exported:
        exported.extractall(old, filter="data")
    old = old / "plugins/xp-plugin"
    new = tmp_path / "new-copy/plugins/xp-plugin"
    shutil.copytree(PLUGIN, new)
    return old, new


def terminal_validation_interruption(tmp_path, monkeypatch, outcome="red", adjusted=False):
    from contextlib import chdir

    import close
    import pytest
    import review_validation
    import verify_receipt

    gate = tmp_path / "gate"
    calls = tmp_path / "validation-calls"
    gate.write_text(f"#!/bin/sh\necho checked >> {calls}\nexit {9 if outcome == 'red' else 0}\n")
    gate.chmod(0o755)
    repo, env, _git, key, events, _hooks = flow_repo(tmp_path, verify=str(gate))
    original = verify_receipt.record

    def interrupted(*args):
        result = original(*args)
        assert bool(result) == (outcome == "red")
        raise KeyboardInterrupt

    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with chdir(repo), monkeypatch.context() as patch:
        patch.setattr(review_validation.verify_receipt, "record", interrupted)
        with pytest.raises(KeyboardInterrupt):
            close.cmd_review(key)
    state = checkpoint(env, key)
    assert state["status"] == "validation" and not state["validation"]
    gate.write_text(f"#!/bin/sh\necho checked >> {calls}\necho GREEN\n")
    if adjusted:
        from card_adjustment_support import adjust

        adjust(
            repo,
            env,
            [
                (f"Verify: {gate}", "Verify: true"),
                ("Context: demo.", "Context: corrected context."),
            ],
            "card-edit",
        )
    result = invoke(repo, env, key)
    assert result.returncode == (2 if outcome == "red" else 0), result.stderr
    assert checkpoint(env, key)["status"] == (
        "awaiting-disposition" if outcome == "red" else "completed"
    )
    assert calls.read_text().splitlines() == ["checked"] * (
        1 if adjusted else 2 if outcome == "red" else 1
    )
    assert events.read_text().splitlines() == ["solution"] * (2 if adjusted else 1)
    if adjusted:
        attempts = checkpoint(env, key)["validation"]
        assert len(attempts) == 2 and attempts[0]["error"] and not attempts[1]["error"]
        disposition = invoke(
            repo,
            env,
            key,
            "acknowledge-validation",
            "--reason",
            "corrected the Verify command after inspecting the retained red",
        )
        assert disposition.returncode == 0, disposition.stderr
        assert checkpoint(env, key)["disposition"]["attempts"] == attempts
