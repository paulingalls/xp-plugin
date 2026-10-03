import json
import re
import subprocess

import pytest
from plan_human_question_support import (
    AFTER,
    BEFORE,
    QUESTION,
    REASON,
    answer,
    answered_resume,
    consumer,
    guard_faults,
    invalid_cases,
    parser_probe,
    repeated_stop,
    report,
)
from plan_review import durable_disposition, evaluate_disposition
from plan_review_install import installed_launch, legacy_credential
from spawn_helpers import make_repo, spawn
from test_plan_review import PLUGIN
from test_spawn_stages import event_roles


@pytest.mark.parametrize("status", ["clean", "edited", "blocked"])
def test_question_stops_real_spawn(tmp_path, status):
    repo, env, seen = consumer(tmp_path, status)
    result = spawn(repo, env, "story-042")
    assert result.returncode != 0
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["stages"]["plan-reviewer"] == "blocked", result.stderr
    assert "teammate" not in event_roles(seen)
    assert QUESTION in (tmp_path / "data/plans/story-042.round-1.md").read_text()
    draft = (tmp_path / "data/plans/story-042.plan.md").read_text()
    assert "Human storage choice: undecided" in draft
    if status != "clean":
        assert f"Reason: {REASON}" in draft


@pytest.mark.parametrize("status", ["clean", "edited"])
def test_legacy_nominal_success_with_question_refuses(tmp_path, status):
    repo, env, seen = consumer(tmp_path, "blocked")
    assert spawn(repo, env, "story-042").returncode != 0
    legacy_credential(tmp_path)
    marker = tmp_path / "data/plans/story-042.handoff.json"
    state = json.loads(marker.read_text())
    state["stages"]["plan-reviewer"] = "ran"
    marker.write_text(json.dumps(state))
    path = tmp_path / "data/plans/story-042.round-1.md"
    old = json.dumps(dict(status=status, reasons=[], question=QUESTION))
    path.write_text(old)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert QUESTION in result.stderr
    assert str(path) in result.stderr
    assert "amend" in result.stderr
    assert path.read_text() == old
    assert "teammate" not in event_roles(seen)


def test_charter_examples_execute_parser():
    charter = (PLUGIN / "agents" / "plan-reviewer.md").read_text()
    output = charter.split("## Output", 1)[1]
    examples = re.findall(r"(```json\n(.*?)```)", output, flags=re.S)
    assert len(examples) == 4
    assert [json.loads(body)["status"] for _fence, body in examples] == [
        "clean",
        "edited",
        "blocked",
        "edited",
    ]
    changed = b"# plan\n\nReason: exact reason text present in the plan\n"
    evaluations = [
        evaluate_disposition(examples[0][0], b"# plan\n", b"# plan\n"),
        evaluate_disposition(examples[1][0], b"# plan\n", changed),
        evaluate_disposition(examples[2][0], b"# plan\n", b"# plan\n"),
        evaluate_disposition(examples[3][0], b"# plan\n", changed),
    ]
    assert [outcome for outcome, _problem in evaluations] == ["ran", "ran", "blocked", "blocked"]
    outside_fences = re.sub(r"```json\n.*?```", "", output, flags=re.S)
    assert not re.search(r'\{[^{}]*"status"', outside_fences)
    assert ".round-1.md" in charter
    assert "legacy logical round one" in charter


@pytest.mark.parametrize(
    "name,text,before,after", invalid_cases(), ids=[c[0] for c in invalid_cases()]
)
def test_invalid_disposition_refuses_with_action(tmp_path, name, text, before, after):
    outcome, problem = evaluate_disposition(text, before, after)
    assert outcome == "failed", (name, problem)
    if name.startswith("duplicate-question"):
        assert durable_disposition(text)[0] == "failed"
    assert "repair" in problem or "write" in problem
    status = "edited" if before != after else "clean"
    repo, env, seen = consumer(tmp_path, status)
    binary = tmp_path / "bin/claude"
    payload = report(status, QUESTION, [REASON] if status == "edited" else [])
    binary.write_text(binary.read_text().replace(repr(payload), repr(text)))
    result = spawn(repo, env, "story-042")
    assert result.returncode != 0
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["stages"]["plan-reviewer"] == "failed", result.stderr
    assert "teammate" not in event_roles(seen)
    assert (tmp_path / "data/plans/story-042.round-1.failed-1.md").read_text() == text
    assert not (tmp_path / "data/plans/story-042.round-1.md").exists()


@pytest.mark.parametrize("filename", ["story-042.md", "story-042.round-1.md"])
@pytest.mark.parametrize("state_kind", ["blocked", "ran"])
def test_legacy_question_survives_recovery(tmp_path, filename, state_kind):
    repo, env, seen = consumer(tmp_path, "blocked")
    assert spawn(repo, env, "story-042").returncode != 0
    legacy_credential(tmp_path)
    plans = tmp_path / "data/plans"
    numbered = plans / "story-042.round-1.md"
    old = json.dumps({"status": "blocked", "question": QUESTION})
    numbered.unlink()
    path = plans / filename
    path.write_text(old)
    marker = plans / "story-042.handoff.json"
    state = json.loads(marker.read_text())
    state["stages"]["plan-reviewer"] = state_kind
    state.pop("plan_reviewed_card", None)
    state["plan_review_findings"] = str(path)
    marker.write_text(json.dumps(state))
    if state_kind == "blocked":
        (plans / "story-042.round-1.md").write_text(old)
        assert spawn(repo, env, "resume", "story-042").returncode != 0
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert QUESTION in result.stderr
    assert path.read_text() == old
    assert "teammate" not in event_roles(seen)


def test_unanswered_question_does_not_authorize_execution(tmp_path):
    repo, env, seen = consumer(tmp_path, "blocked")
    repeated_stop(tmp_path, repo, env, seen)


def test_answered_resume_uses_current_findings(tmp_path):
    repo, env, seen = consumer(tmp_path)
    assert spawn(repo, env, "story-042").returncode != 0
    answered_resume(tmp_path, repo, env, seen)


def test_answered_resume_after_repeated_stops_uses_current_findings(tmp_path):
    repo, env, seen = consumer(tmp_path, "blocked")
    repeated_stop(tmp_path, repo, env, seen)
    answered_resume(tmp_path, repo, env, seen)


def test_answered_legacy_rounds_use_current_findings(tmp_path):
    repo, env, seen = consumer(tmp_path, "blocked")
    assert spawn(repo, env, "story-042").returncode != 0
    legacy_credential(tmp_path)
    plans = tmp_path / "data/plans"
    old = json.dumps({"status": "blocked", "question": QUESTION})
    for number in (1, 2):
        (plans / f"story-042.round-{number}.md").write_text(old)
    marker = plans / "story-042.handoff.json"
    state = json.loads(marker.read_text())
    state.pop("plan_reviewed_card")
    marker.write_text(json.dumps(state))
    answered_resume(tmp_path, repo, env, seen)
    assert (plans / "story-042.superseded-1.round-1.md").read_text() == old
    assert (plans / "story-042.superseded-1.round-2.md").read_text() == old


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_installed_harness_stop_and_answered_resume(tmp_path, harness):
    repo, env, seen = consumer(tmp_path)
    launch = installed_launch(tmp_path)
    if harness == "codex":
        config = repo / ".xp/config.yml"
        config.write_text(config.read_text().replace("claude/", "codex/"))
        subprocess.run(
            ["git", "commit", "-am", "codex roles"],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
        binary = tmp_path / "bin/claude"
        text = (
            binary.read_text()
            .replace(
                '[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]',
                '{"installed":[{"pluginId":"xp-plugin@xp-plugin","version":"fixture"}]}',
            )
            .replace(
                "print(json.dumps({'type':'result','subtype':'success','result':'done'}))",
                "print(json.dumps({'type':'item.completed','item':"
                "{'type':'agent_message','text':'done'}}))\n"
                "print(json.dumps({'type':'turn.completed','usage':{}}))",
            )
        )
        (tmp_path / "bin/codex").write_text(text)
        (tmp_path / "bin/codex").chmod(0o755)
    stopped = launch(repo, env, "story-042")
    assert stopped.returncode != 0
    assert QUESTION in stopped.stderr
    assert event_roles(seen) == ["planner", "plan-reviewer"]
    assert (tmp_path / "data/plans/story-042.round-1.md").exists()
    answered_resume(tmp_path, repo, env, seen, launch)


@pytest.mark.parametrize(
    "name,text,before,after,mutation", guard_faults(), ids=[c[0] for c in guard_faults()]
)
@pytest.mark.meta
def test_each_disposition_guard_detects_its_fault(tmp_path, name, text, before, after, mutation):
    path = tmp_path / "parser.py"
    source = (PLUGIN / "scripts/plan_disposition.py").read_text()
    path.write_text(source)
    assert parser_probe(path, text, before, after).startswith("('failed',")
    old, new = mutation
    assert old in source
    path.write_text(source.replace(old, new))
    observed = parser_probe(path, text, before, after)
    assert not observed.startswith("('failed',"), (name, observed)


@pytest.mark.meta
def test_ignoring_question_detects_executor_launch(tmp_path):
    repo, env, seen = consumer(tmp_path)
    launch = installed_launch(tmp_path, ("if question is not None:", "if False:"))
    result = launch(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert "teammate" in event_roles(seen)


@pytest.mark.parametrize("status", ["clean", "edited"])
def test_legacy_success_without_acceptance_requires_review(tmp_path, status):
    repo, env, seen = consumer(tmp_path, "blocked")
    assert spawn(repo, env, "story-042").returncode != 0
    legacy_credential(tmp_path)
    marker = tmp_path / "data/plans/story-042.handoff.json"
    state = json.loads(marker.read_text())
    state["stages"]["plan-reviewer"] = "ran"
    marker.write_text(json.dumps(state))
    path = tmp_path / "data/plans/story-042.round-1.md"
    path.write_text(json.dumps(dict(status=status, reasons=[])))
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 2 and QUESTION in result.stderr
    assert event_roles(seen) == ["planner", "plan-reviewer", "plan-reviewer"]


@pytest.mark.parametrize("kind", ["failed-archive", "blocked-retain"])
@pytest.mark.meta
def test_artifact_lifecycle_detects_its_fault(tmp_path, kind):
    status = "clean" if kind == "failed-archive" else "blocked"
    repo, env, seen = consumer(tmp_path, status)
    if kind == "failed-archive":
        binary = tmp_path / "bin/claude"
        binary.write_text(binary.read_text().replace(repr(report("clean", QUESTION)), repr("[]")))
    mutation = (
        'archive_failed_findings(out) if outcome == "failed" else ""',
        '""' if kind == "failed-archive" else "archive_failed_findings(out)",
    )
    launch = installed_launch(tmp_path, mutation, relative="scripts/plan_review.py")
    assert launch(repo, env, "story-042").returncode != 0
    plans = tmp_path / "data/plans"
    if kind == "failed-archive":
        with pytest.raises(AssertionError):
            assert (plans / "story-042.round-1.failed-1.md").exists()
    else:
        with pytest.raises(AssertionError):
            assert (plans / "story-042.round-1.md").exists()
    assert "teammate" not in event_roles(seen)


@pytest.mark.meta
def test_stale_question_selection_detects_its_fault(tmp_path):
    repo, env, seen = consumer(tmp_path)
    assert spawn(repo, env, "story-042").returncode != 0
    launch = installed_launch(
        tmp_path,
        (
            "outcome, problem = durable_disposition(path.read_text())",
            "outcome, problem = durable_disposition(path.read_text())\n"
            '    for old in path.parent.glob("story-042.*round-*.md"):\n'
            "        old_outcome, old_problem = durable_disposition(old.read_text())\n"
            '        if old_outcome == "blocked":\n'
            "            outcome, problem = old_outcome, old_problem",
        ),
        relative="scripts/spawn/handoff.py",
    )
    with pytest.raises(AssertionError):
        answered_resume(tmp_path, repo, env, seen, launch)
    assert "teammate" not in event_roles(seen)


@pytest.mark.parametrize("guard", ["legacy-extraction", "durable-question"])
@pytest.mark.meta
def test_recovery_guards_detect_their_fault(tmp_path, guard):
    repo, env, seen = consumer(tmp_path, "blocked")
    if guard == "legacy-extraction":
        assert spawn(repo, env, "story-042").returncode != 0
        path = tmp_path / "data/plans/story-042.round-1.md"
        path.write_text(json.dumps({"status": "blocked", "question": QUESTION}))
        legacy_credential(tmp_path)
        marker = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(marker.read_text())
        state["stages"]["plan-reviewer"] = "ran"
        marker.write_text(json.dumps(state))
        launch = installed_launch(
            tmp_path,
            (
                'return "blocked", f"blocked for the human: {question}"',
                'return "blocked", "blocked for the human"',
            ),
        )
        saved = marker.read_bytes()
        control = spawn(repo, env, "resume", "story-042")
        assert control.returncode != 0 and QUESTION in control.stderr, control.stderr
        marker.write_bytes(saved)
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode != 0
        with pytest.raises(AssertionError):
            assert QUESTION in result.stderr
        assert "teammate" not in event_roles(seen)
    else:
        source = (PLUGIN / "scripts/plan_disposition.py").read_text()
        scope = {}
        exec(compile(source, "plan_disposition.py", "exec"), scope)
        text = report("blocked", QUESTION)
        assert scope["durable_disposition"](text)[0] == "blocked"
        mutated = source.replace(
            'if question is not None:\n        return "blocked",',
            'if False:\n        return "blocked",',
        )
        exec(compile(mutated, "plan_disposition.py", "exec"), scope)
        assert scope["durable_disposition"](text) == ("ran", "")


@pytest.mark.meta
def test_old_current_round_selection_detects_its_fault(tmp_path):
    for mutant in (False, True):
        case = tmp_path / str(mutant)
        case.mkdir()
        assert_current_round_selection(case, mutant)


def assert_current_round_selection(tmp_path, mutant):
    from plan_confirmation_support import amend, events
    from test_plan_findings_handoff import staged_harness

    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path, block_first=True)
    mutation = (
        'state["plan_review_findings"] = accepted["findings"]',
        'state["plan_review_findings"] = str(next((root / "plans").glob('
        'f"{story_id}.superseded-*.round-*.md")).resolve())',
    )
    launch = installed_launch(
        tmp_path, mutation if mutant else None, relative="scripts/spawn/handoff.py"
    )
    assert launch(repo, env, "story-042").returncode != 0
    amend(tmp_path, repo, env, launch)
    result = launch(repo, env, "resume", "story-042")
    current = tmp_path / "data/plans/story-042.round-1.md"
    assert "LOUD: run diagnostic check" in current.read_text()
    assert "STALE BLOCKED ROUND?" not in current.read_text()

    def guarantee():
        assert result.returncode == 0, result.stderr
        executor = next(event for event in events(seen) if event["role"] == "teammate")
        assert executor["findings_path"].endswith("story-042.round-1.md")
        assert "LOUD: run diagnostic check" in executor["findings"]
        assert "STALE BLOCKED ROUND?" not in executor["findings"]

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
        assert result.returncode != 0
        assert "teammate" not in event_roles(seen)
    else:
        guarantee()


@pytest.mark.parametrize(
    "old",
    [
        {"status": "clean"},
        {"status": "clean", "reasons": []},
        {"status": "edited", "reasons": [REASON]},
    ],
)
def test_legacy_success_compatibility_is_recovery_only(old):
    from plan_review import durable_disposition

    text = json.dumps(old)
    assert durable_disposition(text) == ("ran", "")
    assert (
        evaluate_disposition(text, BEFORE, AFTER if old["status"] == "edited" else BEFORE)[0]
        == "failed"
    )


def test_mixed_corrections_wait_for_explicit_answer(tmp_path):
    from test_card_update_contract import CHANGES, edited_stages

    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]], QUESTION)
    first = spawn(repo, env, "story-042")
    assert first.returncode != 0 and QUESTION in first.stderr
    plan = tmp_path / "data/plan.md"
    draft = tmp_path / "data/plans/story-042.plan.md"
    preserved = draft.read_bytes()
    assert "REVIEWED-AC" in plan.read_text()
    for _ in range(4):
        result = spawn(repo, env, "resume", "story-042")
        assert result.returncode != 0 and QUESTION in result.stderr
        assert draft.read_bytes() == preserved
    assert event_roles(events) == ["planner", "plan-reviewer"]
    assert (
        spawn(repo, env, "amend", "story-042", "--reason", "unrelated observation").returncode == 0
    )
    unrelated = spawn(repo, env, "resume", "story-042")
    assert unrelated.returncode != 0 and QUESTION in unrelated.stderr
    assert "teammate" not in event_roles(events)
    assert "REVIEWED-AC" in plan.read_text()


@pytest.mark.parametrize("new_question", [False, True], ids=["resolved", "new-question"])
def test_explicit_answer_continues_preserved_plan(tmp_path, new_question):
    repo, env, events = consumer(tmp_path)
    assert spawn(repo, env, "story-042").returncode != 0
    plan = tmp_path / "data/plans/story-042.plan.md"
    before = plan.read_bytes()
    if new_question:
        answer(tmp_path, repo, env)
        binary = tmp_path / "bin/claude"
        binary.write_text(
            binary.read_text().replace(
                repr(report("edited", None, [REASON])),
                repr(report("edited", "A new reserved choice?", [REASON])),
            )
        )
        result = spawn(repo, env, "resume", "story-042")
        assert result.returncode != 0 and "A new reserved choice?" in result.stderr
        assert "teammate" not in event_roles(events)
        assert plan.read_bytes().startswith(before)
        return
    answered_resume(tmp_path, repo, env, events)
    assert plan.read_bytes().startswith(before)
    assert event_roles(events) == [
        "planner",
        "plan-reviewer",
        "planner",
        "plan-reviewer",
        "teammate",
        "reviewer",
    ]
