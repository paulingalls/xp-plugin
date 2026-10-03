"""Instrumented stage harness shared by spawn and disposition checks."""

import json
import shlex
import sys

CLEAN = {"actionable": [], "fixed": [], "blocking": [], "schema": 2, "dropped": [], "debt": []}


def stub_stages(
    tmp_path,
    blocking_plan=False,
    blocking_diff=False,
    unreadable_plan=False,
    review_failure=False,
    executor_failure=False,
):
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    events = tmp_path / "events.jsonl"
    if unreadable_plan:
        findings = '```json\n{"status":\n```'  # a verdict the harness cannot READ
    elif blocking_plan:
        findings = json.dumps({"status": "blocked", "reasons": [], "human_question": "choose"})
    else:
        findings = json.dumps({"status": "clean", "human_question": None, "reasons": []})
    report = (
        {
            "actionable": [],
            "fixed": [],
            "blocking": ["cannot land"],
            "schema": 2,
            "dropped": [],
            "debt": [],
        }
        if blocking_diff
        else CLEAN
    )
    repair = tmp_path / "review-repaired"
    repair_action = shlex.join(
        [sys.executable, "-c", f"from pathlib import Path; Path({str(repair)!r}).touch()"]
    )
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, subprocess, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read(); role = os.environ['XP_ROLE']\n"
        f"events = {str(events)!r}\n"
        "with open(events, 'a') as f:\n"
        " f.write(json.dumps({'role': role, 'argv': sys.argv[1:], 'prompt': prompt}) + '\\n')\n"
        "if role == 'planner':\n"
        " p = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M); assert p\n"
        " open(p.group(1).strip(), 'a').write('# execution plan\\nred then green\\n')\n"
        "elif role == 'plan-reviewer':\n"
        " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
        f" open(p.group(1).strip(), 'w').write({findings!r})\n"
        " if '.confirmation-' in p.group(1):\n"
        "  verdict = json.loads(open(p.group(1)).read()); verdict['decision'] = 'confirm'\n"
        "  open(p.group(1), 'w').write(json.dumps(verdict))\n"
        "elif role == 'teammate':\n"
        " os.makedirs('src', exist_ok=True)\n"
        " open('src/thing.py', 'a').write('\\nDONE = True\\n')\n"
        " subprocess.run(['git', 'add', '-A'], check=True)\n"
        " subprocess.run(['git', 'commit', '-qm', 'executor work'], check=True)\n"
        f" if {executor_failure!r}: sys.exit(9)\n"
        "elif role == 'reviewer':\n"
        f" if {review_failure!r} and not os.path.exists({str(repair)!r}):\n"
        f"  action = {repair_action!r}\n"
        "  print('reviewer log noise ' * 200, file=sys.stderr)\n"
        "  print(f'refused: generated reviewer cause; run `{action}`', file=sys.stderr)\n"
        "  sys.exit(2)\n"
        " p = re.search(r'^REPORT_PATH: (.+)$', prompt, re.M); assert p\n"
        f" report = {report!r}\n"
        " open(p.group(1).strip(), 'w').write(json.dumps(report))\n"
        "print(json.dumps({'type':'result','subtype':'success','result':'done'}))\n"
    )
    binary.chmod(0o755)
    return events
