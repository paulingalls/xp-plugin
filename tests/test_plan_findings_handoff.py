"""A staged plan review reaches the executor that actually launches."""

import json
import re
import subprocess
import sys

from spawn_helpers import SPAWN, make_repo, spawn


def staged_harness(tmp_path, fail_first=False):
    binary = tmp_path / "bin/claude"
    binary.parent.mkdir(exist_ok=True)
    seen = tmp_path / "seen.jsonl"
    attempt = tmp_path / "first-review-attempt"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, subprocess, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]\'); sys.exit()\n'  # noqa: E501
        "prompt = sys.stdin.read(); role = os.environ['XP_ROLE']\n"
        f"seen = {str(seen)!r}\n"
        "event = {'role': role, 'prompt': prompt}\n"
        "if role == 'planner':\n"
        " p = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M); assert p\n"
        " open(p.group(1), 'w').write('# plan\\nrun diagnostic check\\n')\n"
        "elif role == 'plan-reviewer':\n"
        " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
        f" if {fail_first!r} and not os.path.exists({str(attempt)!r}):\n"
        f"  open({str(attempt)!r}, 'w').write('failed')\n"
        "  open(p.group(1), 'w').write('incomplete')\n"
        "  sys.exit(1)\n"
        ' open(p.group(1), \'w\').write(\'```json\\n{"status":"clean","reasons":[],"summary":"LOUD: run diagnostic check"}\\n```\')\n'  # noqa: E501
        "elif role == 'teammate':\n"
        " p = re.search(r'^Plan-review findings: (.+)$', prompt, re.M)\n"
        " event['findings_path'] = p.group(1) if p else None\n"
        " event['findings'] = open(p.group(1)).read() if p else None\n"
        " os.makedirs('src', exist_ok=True)\n"
        " open('src/thing.py', 'a').write('\\nDONE = True\\n')\n"
        " subprocess.run(['git', 'add', '-A'], check=True)\n"
        " subprocess.run(['git', 'commit', '-qm', 'executor work'], check=True)\n"
        "elif role == 'reviewer':\n"
        " p = re.search(r'^REPORT_PATH: (.+)$', prompt, re.M); assert p\n"
        ' open(p.group(1), \'w\').write(\'{"fixed":[],"blocking":[],"noted":[]}\')\n'
        "with open(seen, 'a') as f: f.write(json.dumps(event) + '\\n')\n"
        "print(json.dumps({'type':'result','subtype':'success','result':'done'}))\n"
    )
    binary.chmod(0o755)
    return seen


def test_first_executor_reads_current_plan_findings(tmp_path):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    event = next(json.loads(line) for line in seen.read_text().splitlines() if '"teammate"' in line)
    path = tmp_path / "data/plans/story-042.round-1.md"
    assert event["findings_path"] == str(path)
    assert "LOUD: run diagnostic check" in event["findings"]
    assert not path.is_relative_to(tmp_path / "data/worktrees/story-042")
    assert str(tmp_path / "data/plan.md") in event["prompt"]
    assert f"python3 {SPAWN.parent / 'work.py'} card-snapshot" in event["prompt"]
    assert "edit-card STORY_ID --digest DIGEST --status STATUS" in event["prompt"]


def test_resume_uses_current_round_and_profiles_launched_prompt(tmp_path):
    from card_profile import component_metadata_chars

    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path, fail_first=True)
    failed = spawn(repo, env, "story-042")
    assert failed.returncode != 0
    archived = tmp_path / "data/plans/story-042.superseded-1.round-99.md"
    archived.write_text("STALE ARCHIVED FINDING")
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    event = next(json.loads(line) for line in seen.read_text().splitlines() if '"teammate"' in line)
    assert event["findings_path"] == str(tmp_path / "data/plans/story-042.round-1.md")
    assert "LOUD: run diagnostic check" in event["findings"]
    assert "STALE ARCHIVED FINDING" not in event["prompt"]
    shipped = SPAWN.parent.parent
    claude = (
        len((repo / "CLAUDE.md").read_text())
        if (repo / "CLAUDE.md").exists()
        else len("(missing: CLAUDE.md)")
    )
    expected = (len(event["prompt"]) + claude + component_metadata_chars(shipped)) // 4
    assert f"profile: total {expected} tokens" in resumed.stdout


def test_card_snapshot_route_is_locked_and_rejects_stale_candidate(tmp_path):
    repo, env, _ = make_repo(tmp_path)
    work = SPAWN.parent / "work.py"
    snapshot = subprocess.run(
        [sys.executable, str(work), "card-snapshot", "story-042", str(tmp_path / "candidate.md")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert snapshot.returncode == 0, snapshot.stderr
    digest = re.search(r"^digest: ([0-9a-f]{16})$", snapshot.stdout, re.M).group(1)
    candidate = tmp_path / "candidate.md"
    candidate.write_text(
        candidate.read_text()
        .replace("Files: src/thing.py", "Files: src/thing.py, src/other.py")
        .replace("Verify: true", "Verify: true && true")
    )
    command = [
        sys.executable,
        str(work),
        "edit-card",
        "story-042",
        "--digest",
        digest,
        "--status",
        "ready",
        str(candidate),
    ]
    edited = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    assert edited.returncode == 0, edited.stderr
    plan = tmp_path / "data/plan.md"
    assert "Files: src/thing.py, src/other.py" in plan.read_text()
    assert "Verify: true && true" in plan.read_text()
    stale = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    assert stale.returncode == 2 and "changed after" in stale.stderr
    assert "Verify: true && true" in plan.read_text()


def test_missing_review_findings_refuses_before_executor_launch(tmp_path):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path)
    script = (
        "import sys\n"
        f"sys.path[:0] = [{str(SPAWN.parent)!r}, {str(SPAWN.parent / 'spawn')!r}]\n"
        "import plan_review\n"
        "original = plan_review.run_foreground\n"
        "def remove_findings(*args):\n"
        " result = original(*args)\n"
        " if result[0] == 0:\n"
        "  plan_review.findings_path(args[0]).with_name(args[0] + '.round-1.md').unlink()\n"
        " return result\n"
        "plan_review.run_foreground = remove_findings\n"
        "import spawn\n"
        "sys.argv = ['spawn.py', 'story-042']\n"
        "raise SystemExit(spawn.main())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env | {"XP_SPAWN_TEST": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "cannot read current plan-review findings" in result.stderr
    assert "resume the story" in result.stderr
    assert all(json.loads(line)["role"] != "teammate" for line in seen.read_text().splitlines())
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode != 0
    assert "cannot read current plan-review findings" in resumed.stderr
    assert all(json.loads(line)["role"] != "teammate" for line in seen.read_text().splitlines())
