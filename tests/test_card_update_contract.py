"""Reviewer corrections bind the artifacts actually consumed by spawn."""

import json
from pathlib import Path

import pytest
from spawn_helpers import make_repo, spawn
from test_spawn_stages import event_roles, prompt_for, stub_stages

REASON = "Reason: Honesty — correct the declaration against the measured work."
CHANGES = {
    "ac": ("Then Z", "Then REVIEWED-AC"),
    "context": ("Context: demo.", "Context: REVIEWED-CONTEXT."),
    "files": ("src/other.py", "src/other.py, src/new.py (new)"),
    "depth": ("Executor:", "Close review: deep\nExecutor:"),
    "single": ("src/thing.py, src/other.py", "src/thing.py"),
}


def edited_stages(tmp_path, changes, question=None, blocking_diff=False):
    events = stub_stages(tmp_path, blocking_diff=blocking_diff)
    binary = tmp_path / "bin/claude"
    source = binary.read_text()
    action = (
        " from pathlib import Path\n"
        " c = re.search(r'^CARD_CANDIDATE_PATH: (.+)$', prompt, re.M)\n"
        " out = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert out\n"
        " candidate = Path(c.group(1)) if c else Path(out.group(1)).with_suffix('.card.md')\n"
        " text = candidate.read_text() if candidate.exists() else "
        "re.search(r'## Story card\\n\\n(.*?)(?=\\n## |\\Z)', prompt, re.S).group(1)\n"
        f" for old, new in {changes!r}: text = text.replace(old, new)\n"
        " candidate.write_text(text)\n"
        " p = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M); assert p\n"
        f" with open(p.group(1), 'a') as f: f.write({REASON!r} + '\\n')\n"
    )
    source = source.replace(
        "elif role == 'plan-reviewer':\n", "elif role == 'plan-reviewer':\n" + action
    )
    clean = json.dumps({"status": "clean", "human_question": None, "reasons": []})
    edited = json.dumps({"status": "edited", "human_question": question, "reasons": [REASON]})
    source = source.replace(repr(clean), repr(edited))
    binary.write_text(source)
    return events


@pytest.mark.parametrize("kind", [*CHANGES, "together"])
def test_reviewed_edits_flow_through_spawn(tmp_path, kind):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    changes = (
        [CHANGES[kind]]
        if kind != "together"
        else [CHANGES[k] for k in ("ac", "context", "files", "depth")]
    )
    events = edited_stages(tmp_path, changes)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
    executor = prompt_for(events, "teammate")
    for _old, new in changes:
        assert new in executor
    assert REASON in Path(env["XP_DATA"]).joinpath("plans/story-042.plan.md").read_text()
    if kind == "single":
        assert "Files: src/thing.py\n" in executor
    assert "story-042.round-1.md" in executor
    assert "story-042.plan.md" in executor
    state = json.loads(Path(env["XP_DATA"]).joinpath("plans/story-042.handoff.json").read_text())
    assert state["stages"]["story-tier"] == "ran"
    credential = json.loads(
        Path(env["XP_DATA"]).joinpath("markers/story-042.ready.json").read_text()
    )
    assert state["plan_reviewed_card"] == credential["digest"]
    assert (
        state["plan_review_identity"] == credential["review_acceptances"][-1]["findings_identity"]
    )


def test_mixed_review_preserves_edits_and_blocks_executor(tmp_path):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]], "choose a new design")
    first = spawn(repo, env, "story-042")
    assert first.returncode != 0
    assert "REVIEWED-AC" in Path(env["XP_DATA"]).joinpath("plan.md").read_text()
    assert event_roles(events) == ["planner", "plan-reviewer"]
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode != 0
    assert event_roles(events) == ["planner", "plan-reviewer"]


def test_planner_card_motion_has_no_review_authority(tmp_path):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = stub_stages(tmp_path)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "if role == 'planner':\n",
            "if role == 'planner':\n"
            " from pathlib import Path\n"
            " p = Path(os.environ['XP_DATA']) / 'plan.md'\n"
            " p.write_text(p.read_text().replace('Then Z', 'Then unauthorized'))\n",
        )
    )
    result = spawn(repo, env, "story-042")
    assert result.returncode != 0
    assert event_roles(events) == ["planner"]
    assert "planner changed the story card" in result.stderr


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("question", [None, "which new design should the human choose?"])
def test_installed_harness_review_acceptance(tmp_path, harness, question):
    import shutil
    import subprocess
    import sys

    from spawn_helpers import SPAWN

    repo, env, g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"], CHANGES["context"]], question)
    installed = tmp_path / "cache/xp-plugin/fixture"
    shutil.copytree(SPAWN.parent.parent, installed)
    if harness == "codex":
        config = repo / ".xp/config.yml"
        config.write_text(config.read_text().replace("claude/", "codex/"))
        assert g("commit", "-am", "codex roles").returncode == 0
        assert g("branch", "-f", "main", "HEAD").returncode == 0
        binary = tmp_path / "bin/claude"
        text = (
            binary.read_text()
            .replace(
                '[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]',
                '{"installed":[{"pluginId":"xp-plugin@xp-plugin","version":"fixture"}]}',
            )
            .replace(
                "print(json.dumps({'type':'result','subtype':'success','result':'done'}))",
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}))\nprint(json.dumps({'type':'turn.completed','usage':{}}))",
            )
        )
        (tmp_path / "bin/codex").write_text(text)
        (tmp_path / "bin/codex").chmod(0o755)

    def launch(*args, cwd=repo, script="spawn.py"):
        return subprocess.run(
            [sys.executable, str(installed / "scripts" / script), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )

    result = launch("story-042")
    if question:
        assert result.returncode != 0
        assert "REVIEWED-AC" in Path(env["XP_DATA"]).joinpath("plan.md").read_text()
        assert launch("resume", "story-042").returncode != 0
        assert "teammate" not in event_roles(events)
    else:
        assert result.returncode == 0, result.stderr
        assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
        tree = Path(env["XP_DATA"]) / "worktrees/story-042"
        landed = launch(
            "story", "story-042", "land", "--merge-mode", "local", cwd=tree, script="close.py"
        )
        assert landed.returncode == 0, landed.stderr
        assert "card corrected by plan review" in landed.stdout
        assert "story-042.round-1.md" in landed.stdout
        assert "card amended — reason" not in landed.stdout
        reviewed = prompt_for(events, "reviewer")
        assert "Then REVIEWED-AC" in reviewed and "Context: REVIEWED-CONTEXT." in reviewed


def spawn_with_hook(repo, env, code):
    import subprocess
    import sys

    from spawn_helpers import SPAWN

    program = f"""
import os, sys
from pathlib import Path
sys.path[:0] = [{str(SPAWN.parent)!r}, {str(SPAWN.parent / "spawn")!r}]
import plan_review, plan_acceptance
{code}
import spawn
sys.argv = ['spawn.py', 'story-042']
raise SystemExit(spawn.main())
"""
    return subprocess.run(
        [sys.executable, "-c", program], cwd=repo, env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize("target", ["card", "plan", "findings"])
def test_acceptance_binds_exact_artifacts_before_launch(tmp_path, target):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]])
    code = f"""
original = plan_review.run_foreground
def changed_after(*args):
    result = original(*args)
    record = plan_acceptance.latest(args[0])
    if {target!r} == 'card':
        path = Path(os.environ['XP_DATA']) / 'plan.md'
        text = path.read_text().replace('Context: demo.', 'Context: demo.\\nDecision: new choice')
    else:
        path = Path(record[{target!r}])
        text = path.read_text() + 'unreviewed'
    path.write_text(text)
    return result
plan_review.run_foreground = changed_after
"""
    result = spawn_with_hook(repo, env, code)
    assert result.returncode != 0
    assert event_roles(events) == ["planner", "plan-reviewer"]


@pytest.mark.parametrize("boundary", ["credential-write", "after-publication"])
def test_interrupted_spawn_resumes_exact_round_without_another_review(tmp_path, boundary):
    import re
    import shlex
    import subprocess

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]])
    if boundary == "credential-write":
        code = """
original = plan_acceptance.atomic_json
def interrupted(path, value):
    if path.name.endswith('.ready.json'): raise OSError('injected publication failure')
    original(path, value)
plan_acceptance.atomic_json = interrupted
"""
    else:
        code = """
original = plan_review.run_foreground
def interrupted(*args):
    original(*args)
    os._exit(7)
plan_review.run_foreground = interrupted
"""
    first = spawn_with_hook(repo, env, code)
    assert first.returncode != 0
    assert event_roles(events) == ["planner", "plan-reviewer"]
    if boundary == "credential-write":
        refused = spawn(repo, env, "resume", "story-042")
        assert "interrupted review acceptance" in refused.stderr
        command = re.search(r"completed round with `([^`]+)`", refused.stderr).group(1)
        repaired = subprocess.run(
            shlex.split(command), cwd=repo, env=env, capture_output=True, text=True
        )
        assert repaired.returncode == 0, repaired.stderr
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
    assert "REVIEWED-AC" in prompt_for(events, "teammate")


def test_verify_extension_executes_after_review_acceptance(tmp_path):
    import shlex

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    marker = tmp_path / "reviewed-check-ran"
    command = "python3 -c " + shlex.quote(
        f"from pathlib import Path; Path({str(marker)!r}).touch()"
    )
    events = edited_stages(tmp_path, [("Verify: true", "Verify: true && " + command)])
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert marker.is_file()
    assert command in prompt_for(events, "teammate")


def test_later_files_verify_growth_remains_visible_to_diff_review(tmp_path):
    import sys

    from spawn_helpers import SPAWN

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]])
    binary = tmp_path / "bin/claude"
    action = f""" from pathlib import Path
 p = Path(os.environ['XP_DATA']) / 'executor.card.md'
 work = {str(SPAWN.parent / "work.py")!r}
 python = {sys.executable!r}
 read_args = [python, work, 'card-snapshot', 'story-042', str(p)]
 read = subprocess.run(read_args, capture_output=True, text=True, check=True)
 digest = re.search(r'^digest: (.+)$', read.stdout, re.M).group(1)
 status = re.search(r'^status: (.+)$', read.stdout, re.M).group(1)
 text = p.read_text().replace('src/other.py', 'src/other.py, src/new.py (new)')
 p.write_text(text.replace('Verify: true', 'Verify: true && true'))
 write_args = [python, work, 'edit-card', 'story-042', '--context', 'executor',
               '--digest', digest, '--status', status, str(p)]
 subprocess.run(write_args, check=True)
 os.makedirs('src', exist_ok=True)
 open('src/new.py', 'w').write('NEW = True\\n')
"""
    binary.write_text(
        binary.read_text().replace(
            "elif role == 'teammate':\n", "elif role == 'teammate':\n" + action
        )
    )
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert "src/new.py" in prompt_for(events, "reviewer")
    marker = Path(env["XP_DATA"]) / "markers/story-042.ready.json"
    value = json.loads(marker.read_text())
    assert "src/new.py" not in value["review_acceptances"][-1]["after"]
    assert "Verify: true && true" in Path(env["XP_DATA"]).joinpath("plan.md").read_text()


def test_land_separates_review_corrections_from_later_lead_amendment(tmp_path):
    import subprocess
    import sys

    from spawn_helpers import SPAWN

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"], CHANGES["context"]])
    assert spawn(repo, env, "story-042").returncode == 0
    plan = Path(env["XP_DATA"]) / "plan.md"
    original_findings = (plan.parent / "plans/story-042.round-1.md").read_bytes()
    plan.write_text(plan.read_text().replace("REVIEWED-CONTEXT", "LEAD-CONTEXT"))
    assert (
        spawn(
            repo, env, "amend", "story-042", "--reason", "lead supplied measured correction"
        ).returncode
        == 0
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    tree = Path(env["XP_DATA"]) / "worktrees/story-042"
    landed = subprocess.run(
        [
            sys.executable,
            str(SPAWN.parent / "close.py"),
            "story",
            "story-042",
            "land",
            "--merge-mode",
            "local",
        ],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )
    assert landed.returncode == 0, landed.stderr
    assert "card corrected by plan review" in landed.stdout
    preserved = plan.parent / "plans/story-042.round-1.md"
    assert preserved.read_bytes() == original_findings
    assert str(preserved) in landed.stdout
    amendment = landed.stdout.split("card amended — reason: lead supplied measured correction", 1)[
        1
    ]
    assert "LEAD-CONTEXT" in amendment and "REVIEWED-CONTEXT" in amendment
    assert "Then REVIEWED-AC" not in amendment
    assert event_roles(events).count("plan-reviewer") == 2


def test_free_lane_retains_review_source_and_current_card(tmp_path):
    from close_free_card_cases import add_free_card, checkout_free, commit_on_free
    from close_helpers import free, free_repo
    from test_close_free import configure_executor

    repo, env, g = free_repo(tmp_path)
    configure_executor(repo, g)
    config = repo / ".xp/config.yml"
    config.write_text(
        config.read_text().replace(
            "roles:\n", "roles:\n  planner: claude/opus\n  plan-reviewer: claude/opus\n"
        )
    )
    assert g("commit", "-am", "free plan roles").returncode == 0
    assert free(repo, env, "fix-typo", "start").returncode == 0
    _branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(
        plan.read_text()
        .replace("Files: src/free.py", "Files: src/free.py, src/thing.py")
        .replace("Context: small release.", "Context: small release.\nClose review: deep")
    )
    assert g("checkout", "-q", "main").returncode == 0
    assert spawn(repo, env, "ready", key).returncode == 0
    events = edited_stages(
        tmp_path,
        [
            ("Context: small release.", "Context: REVIEWED-FREE."),
            ("Close review: deep", "Close review: standard"),
        ],
    )
    result = spawn(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert "Close review: standard" in prompt_for(events, "reviewer")
    tree = Path(env["XP_DATA"]) / "worktrees" / key
    landed = free(tree, env, "fix-typo", "land")
    assert landed.returncode == 0, landed.stderr
    assert "card corrected by plan review" in landed.stdout
    assert f"{key}.round-1.md" in landed.stdout


def test_legacy_amendment_does_not_claim_a_later_review_correction(tmp_path):
    import subprocess
    import sys

    from spawn_helpers import SPAWN

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text().replace("Context: demo.", "Context: human measured."))
    assert (
        spawn(repo, env, "amend", "story-042", "--reason", "prior human correction").returncode == 0
    )
    marker = plan.parent / "markers/story-042.ready.json"
    old = json.loads(marker.read_text())
    del old["amendments"][0]["after"]
    old.pop("minted_card")
    marker.write_text(json.dumps(old))
    edited_stages(tmp_path, [CHANGES["ac"]])
    assert spawn(repo, env, "story-042").returncode == 0
    landed = subprocess.run(
        [
            sys.executable,
            str(SPAWN.parent / "close.py"),
            "story",
            "story-042",
            "land",
            "--merge-mode",
            "local",
        ],
        cwd=plan.parent / "worktrees/story-042",
        env=env,
        capture_output=True,
        text=True,
    )
    assert landed.returncode == 0, landed.stderr
    amendment = landed.stdout.split("card amended — reason: prior human correction", 1)[1]
    assert "Context: human measured." in amendment
    assert "Then REVIEWED-AC" not in amendment


def test_approved_behavior_change_requires_lead_decision(tmp_path):
    repo, env, _ = make_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
    card = Path(env["XP_DATA"]) / "plan.md"
    card.write_text(
        card.read_text().replace("Context: demo.", "Context: demo.\nDecision: approved")
    )
    events = edited_stages(
        tmp_path, [CHANGES["ac"], ("Decision: approved", "Decision: new behavior")]
    )
    result = spawn(repo, env, "story-042")
    assert result.returncode != 0 and "reserved" in result.stderr
    assert "Decision: approved" in card.read_text()
    assert "teammate" not in event_roles(events)
    card.write_text(card.read_text().replace("Decision: approved", "Decision: new behavior"))
    assert (
        spawn(repo, env, "amend", "story-042", "--reason", "lead approved new behavior").returncode
        == 0
    )
    edited_stages(tmp_path, [CHANGES["ac"]])
    allowed = spawn(repo, env, "resume", "story-042")
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert "Decision: new behavior" in prompt_for(events, "teammate")
