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
