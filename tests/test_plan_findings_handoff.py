"""A staged plan review reaches the executor that actually launches."""

import json
import re
import subprocess
import sys

import pytest
from resume_preview_support import (
    assert_refusal,
    compare_prompt,
    damage_findings,
    preview_fixture,
    restorable,
    snapshot,
)
from spawn_helpers import SPAWN, make_repo, spawn


def staged_harness(tmp_path, fail_first=False, block_first=False):
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
        " open(p.group(1), 'a').write('# plan\\nrun diagnostic check\\n')\n"
        "elif role == 'plan-reviewer':\n"
        " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
        f" if {fail_first!r} and not os.path.exists({str(attempt)!r}):\n"
        f"  open({str(attempt)!r}, 'w').write('failed')\n"
        "  open(p.group(1), 'w').write('incomplete')\n"
        "  sys.exit(1)\n"
        f" if {block_first!r} and not os.path.exists({str(attempt)!r}):\n"
        f"  open({str(attempt)!r}, 'w').write('blocked')\n"
        '  open(p.group(1), \'w\').write(\'```json\\n{"status":"blocked","reasons":[],"human_question":"STALE BLOCKED ROUND?"}\\n```\')\n'  # noqa: E501
        " else:\n"
        '  open(p.group(1), \'w\').write(\'```json\\n{"status":"clean","human_question":null,"reasons":[],"summary":"LOUD: run diagnostic check"}\\n```\')\n'  # noqa: E501
        " if '.confirmation-' in p.group(1):\n"
        "  raw = open(p.group(1)).read().replace('```json', '').replace('```', '').strip()\n"
        "  verdict = json.loads(raw); verdict['decision'] = 'confirm'\n"
        "  open(p.group(1), 'w').write(json.dumps(verdict))\n"
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
        ' open(p.group(1), \'w\').write(\'{"schema":2,"fixed":[],'
        '"blocking":[],"dropped":[],"debt":[]}\')\n'
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
    assert (
        "edit-card STORY_ID --context executor --digest DIGEST --status STATUS" in event["prompt"]
    )


def test_resume_uses_current_round_and_profiles_launched_prompt(tmp_path):
    from card_profile import component_metadata_chars

    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path, fail_first=True)
    failed = spawn(repo, env, "story-042")
    assert failed.returncode != 0
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    event = next(json.loads(line) for line in seen.read_text().splitlines() if '"teammate"' in line)
    assert event["findings_path"] == str(tmp_path / "data/plans/story-042.round-1.md")
    assert "LOUD: run diagnostic check" in event["findings"]
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


def test_card_snapshot_refuses_to_overwrite_shared_plan(tmp_path):
    repo, env, _ = make_repo(tmp_path)
    plan = tmp_path / "data/plan.md"
    before = plan.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SPAWN.parent / "work.py"), "card-snapshot", "story-042", str(plan)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "candidate already exists" in result.stderr
    assert plan.read_bytes() == before


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
        "  path = plan_review.findings_path(args[0]).with_name(args[0] + '.round-1.md')\n"
        "  path.with_suffix('.saved').write_bytes(path.read_bytes()); path.unlink()\n"
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
    assert "unreadable review acceptance" in result.stderr
    assert "restore its recorded artifacts" in result.stderr
    assert all(json.loads(line)["role"] != "teammate" for line in seen.read_text().splitlines())
    path = tmp_path / "data/plans/story-042.round-1.md"
    path.write_bytes(path.with_suffix(".saved").read_bytes())
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    events = [json.loads(line) for line in seen.read_text().splitlines()]
    assert [e["role"] for e in events].count("plan-reviewer") == 1
    teammate = next(e for e in events if e["role"] == "teammate")
    assert "LOUD: run diagnostic check" in teammate["findings"]


def test_resume_after_blocked_round_hands_over_the_later_round(tmp_path):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path, block_first=True)
    blocked = spawn(repo, env, "story-042")
    assert blocked.returncode != 0 and "STALE BLOCKED ROUND?" in blocked.stderr
    card = tmp_path / "data/plan.md"
    card.write_text(
        card.read_text().replace(
            "Context: demo.",
            "Context: demo.\nDecision: test operator answered the reserved choice.",
        )
    )
    answered = spawn(repo, env, "amend", "story-042", "--reason", "answer reserved choice")
    assert answered.returncode == 0, answered.stderr
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    event = next(json.loads(line) for line in seen.read_text().splitlines() if '"teammate"' in line)
    assert event["findings_path"] == str(tmp_path / "data/plans/story-042.round-1.md")
    assert "LOUD: run diagnostic check" in event["findings"]


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("restore", [False, True])
def test_resume_preview_matches_live_executor_inputs(tmp_path, harness, restore):
    repo, env, seen, launch = preview_fixture(tmp_path, harness=harness)
    if restore:
        restorable(tmp_path)
    compare_prompt(repo, env, seen, launch)


@pytest.mark.parametrize(
    "damage", ["missing", "unreadable", "empty", "non-utf8", "changed", "plan", "stale"]
)
def test_resume_preview_and_live_refuse_current_findings(tmp_path, damage):
    from plan_confirmation_support import amend, events

    repo, env, seen, launch = preview_fixture(tmp_path)
    if damage == "stale":
        amend(tmp_path, repo, env, launch)
        (tmp_path / "executor-stop").touch()
        assert launch(repo, env, "resume", "story-042").returncode != 0
        (tmp_path / "executor-stop").unlink()
    files = {
        p: (p.read_bytes(), p.stat().st_mode)
        for p in (tmp_path / "data/plans").iterdir()
        if p.is_file()
    }
    before = events(seen)
    if damage == "stale":
        marker = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(marker.read_text())
        state["plan_review_findings"] = str(
            next(marker.parent.glob("story-042.superseded-*.round-*.md"))
        )
        marker.write_text(json.dumps(state))
    else:
        damage_findings(tmp_path, damage)
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    live = launch(repo, env, "resume", "story-042")
    try:
        assert_refusal(preview, live, seen, before)
    finally:
        for p, (contents, mode) in files.items():
            if p.exists():
                p.chmod(mode)
            p.write_bytes(contents)
            p.chmod(mode)
    recovered = launch(repo, env, "resume", "story-042")
    assert recovered.returncode == 0, recovered.stderr


@pytest.mark.parametrize("route", ["confirmation", "fallback", "review", "planner"])
def test_resume_preview_reports_pending_plan_stages(tmp_path, route):
    from plan_confirmation_support import amend, events

    repo, env, seen, launch = preview_fixture(tmp_path)
    if route in ("confirmation", "fallback"):
        amend(tmp_path, repo, env, launch)
        if route == "fallback":
            next((tmp_path / "data/plans").glob("*.evidence.json")).unlink()
    else:
        marker = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(marker.read_text())
        state["stages"]["plan-reviewer"] = "failed"
        if route == "planner":
            from plan_review_install import legacy_credential

            legacy_credential(tmp_path)
            (tmp_path / "data/plans/story-042.plan.md").unlink()
            state["stages"]["planner"] = "failed"
        marker.write_text(json.dumps(state))
    before = events(seen)
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert events(seen) == before
    expected = "planner" if route in ("confirmation", "planner", "fallback") else "plan-reviewer"
    assert expected in preview.stdout
    assert "executor inputs are not yet available" in preview.stdout
    assert "## Current plan review" not in preview.stdout
    live = launch(repo, env, "resume", "story-042")
    assert live.returncode == 0, live.stderr
    roles = [e["role"] for e in events(seen)[len(before) :]]
    assert roles[0] == (
        "planner" if route in ("confirmation", "planner", "fallback") else "plan-reviewer"
    )


@pytest.mark.parametrize(
    "route", ["executable", "restorable", "confirmation", "fallback", "refusal"]
)
def test_resume_preview_preserves_state(tmp_path, route):
    from plan_confirmation_support import amend

    repo, env, _seen, launch = preview_fixture(tmp_path)
    if route == "restorable":
        restorable(tmp_path)
    elif route in ("confirmation", "fallback"):
        amend(tmp_path, repo, env, launch)
        if route == "fallback":
            next((tmp_path / "data/plans").glob("*.evidence.json")).unlink()
    elif route == "refusal":
        damage_findings(tmp_path, "stale")
    import os

    tracked = tmp_path / "data/worktrees/story-042/.xp/system.md"
    measured = tracked.stat()
    os.utime(tracked, ns=(measured.st_atime_ns, measured.st_mtime_ns + 1_000_000_000))
    before = snapshot(tmp_path)
    launch(repo, env, "resume", "story-042", "--dry-run")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "defect", ["divergent", "restore", "binding", "selection", "fallback-selection", "writer"]
)
@pytest.mark.meta
def test_preview_guard_fault_injections(tmp_path, defect):
    from plan_confirmation_support import amend, events

    repo, env, seen, launch = preview_fixture(tmp_path)
    scripts = tmp_path / "cache/xp-plugin/fixture/scripts"
    target = scripts / "spawn/execution.py"
    source = target.read_text()
    if defect == "divergent":
        old = "            report, warning = api.profile_report(card, prompt, handoff)"
        new = (
            '            prompt = prompt.replace("## Current plan review", "## Obsolete review")\n'
            + old
        )
    elif defect == "restore":
        restorable(tmp_path)
        old = "prior = api.handoff_io.effective_review(api.data_root(), story_id, prior or {})"
        new = "prior = prior or {}"
    elif defect == "binding":
        damage_findings(tmp_path, "stale")
        old = "        findings\n        and accepted"
        new = "        False\n        and accepted"
    elif defect in ("selection", "fallback-selection"):
        amend(tmp_path, repo, env, launch)
        if defect == "fallback-selection":
            next((tmp_path / "data/plans").glob("*.evidence.json")).unlink()
        old = "stage = planning_stage(api, story_id, prior, multifile or bool(latest(story_id)))"
        new = 'stage = "executor"'
    else:
        old = "    try:\n        prior = api.handoff_io.effective_review"
        new = '    api.mark_stage(api.data_root(), story_id, "executor", "ran")\n' + old
    assert old in source
    target.write_text(source.replace(old, new))
    if defect in ("divergent", "restore"):
        with pytest.raises(AssertionError, match="Current plan review"):
            compare_prompt(repo, env, seen, launch)
    elif defect == "binding":
        before = events(seen)
        preview = launch(repo, env, "resume", "story-042", "--dry-run")
        live = launch(repo, env, "resume", "story-042")
        assert preview.returncode == 0 and live.returncode == 0, (preview.stderr, live.stderr)
        with pytest.raises(AssertionError):
            assert_refusal(preview, live, seen, before)
    elif defect in ("selection", "fallback-selection"):
        preview = launch(repo, env, "resume", "story-042", "--dry-run")
        assert "declaration amended after review" in preview.stderr, preview.stderr
        with pytest.raises(AssertionError):
            assert preview.returncode == 0
        live = launch(repo, env, "resume", "story-042")
        assert live.returncode == 0, live.stderr
        assert any(e["role"] == "planner" for e in events(seen))
    else:
        before = snapshot(tmp_path)
        preview = launch(repo, env, "resume", "story-042", "--dry-run")
        assert preview.returncode == 0, preview.stderr
        with pytest.raises(AssertionError):
            assert snapshot(tmp_path) == before


@pytest.mark.parametrize("guard", ["readability", "disposition"])
@pytest.mark.meta
def test_preview_findings_validation_faults(tmp_path, guard):
    from plan_review_install import legacy_credential

    repo, env, _seen, launch = preview_fixture(tmp_path)
    target = tmp_path / "cache/xp-plugin/fixture/scripts/spawn/execution.py"
    source = target.read_text()
    findings = tmp_path / "data/plans/story-042.round-1.md"
    contents = findings.read_bytes()
    if guard == "readability":
        anchor = "\n        findings, problem = api.handoff_io.current_findings"
        legacy_credential(tmp_path)
        injection = f"\n        __import__('pathlib').Path({str(findings)!r}).unlink()"
        assert anchor in source
        source = source.replace(anchor, injection + anchor)
        old = "api.handoff_io.current_findings(api.data_root(), story_id, True, prior)"
        new = '(None, "")'
        reason = "cannot read current plan-review findings"
    else:
        legacy_credential(tmp_path)
        findings.write_text("readable but no verdict")
        old = "api.handoff_io.current_disposition(findings)"
        new = '("ran", "")'
        reason = "disposition"
    target.write_text(source)
    control = launch(repo, env, "resume", "story-042", "--dry-run")
    assert control.returncode != 0 and reason in control.stderr, control.stderr
    if guard == "readability":
        findings.write_bytes(contents)
    assert old in source
    target.write_text(source.replace(old, new))
    mutant = launch(repo, env, "resume", "story-042", "--dry-run")
    assert mutant.returncode == 0, mutant.stderr
    with pytest.raises(AssertionError):
        assert mutant.returncode != 0 and reason in mutant.stderr


def test_resume_preview_and_live_refuse_restoration(tmp_path):
    from plan_confirmation_support import events

    repo, env, seen, launch = preview_fixture(tmp_path)
    restorable(tmp_path)
    scripts = tmp_path / "cache/xp-plugin/fixture/scripts"
    target = scripts / "spawn.py"
    source = target.read_text()
    anchor = "    inherited_state = handoff_state(data_root(), story_id)"
    injection = (
        "    draft = draft_path(data_root(), story_id)\n"
        '    draft.write_text(draft.read_text() + "late motion")\n'
    )
    assert anchor in source
    target.write_text(source.replace(anchor, injection + anchor))
    draft = tmp_path / "data/plans/story-042.plan.md"
    before_bytes, before_events = draft.read_bytes(), events(seen)
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    draft.write_bytes(before_bytes)
    live = launch(repo, env, "resume", "story-042")
    assert "Traceback" not in preview.stderr, preview.stderr
    assert_refusal(preview, live, seen, before_events)


def test_live_findings_refusal_retains_review_failure(tmp_path):
    from plan_review_install import legacy_credential

    repo, env, _seen, launch = preview_fixture(tmp_path)
    legacy_credential(tmp_path)
    findings = tmp_path / "data/plans/story-042.round-1.md"
    findings.write_text("readable but no verdict")
    refused = launch(repo, env, "resume", "story-042")
    assert refused.returncode != 0 and "disposition" in refused.stderr
    state = json.loads(findings.with_name("story-042.handoff.json").read_text())
    assert state["stages"]["plan-reviewer"] == "failed"


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_resume_preview_and_live_refuse_stale_identity(tmp_path, mutant):
    from resume_preview_support import stale_identity_check

    stale_identity_check(tmp_path, mutant)


@pytest.mark.meta
def test_preview_snapshot_ignores_read_only_code_mutation(tmp_path):
    from resume_preview_support import read_only_preview_check

    read_only_preview_check(tmp_path)
