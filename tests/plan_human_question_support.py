import json
import subprocess
import sys

from test_plan_review import PLUGIN

QUESTION = "Which storage policy should the human choose?"
REASON = "Feedback: exercise the silent loss boundary"
BEFORE = b"# plan\nHuman storage choice: undecided\n"
AFTER = BEFORE + f"Run the loss check.\nReason: {REASON}\n".encode()


def report(status="clean", question=None, reasons=None, **extra):
    return json.dumps(
        dict(status=status, human_question=question, reasons=reasons or [], summary="", **extra)
    )


def invalid_cases():
    base = json.loads(report())
    cases = []

    def add(name, update, before=BEFORE, after=BEFORE):
        cases.append((name, json.dumps(base | update), before, after))

    cases.append(
        (
            "missing-question",
            json.dumps({k: v for k, v in base.items() if k != "human_question"}),
            BEFORE,
            BEFORE,
        )
    )
    duplicate = report("clean", QUESTION)[:-1] + ', "human_question": null}'
    for name, text in [
        ("duplicate-question", duplicate),
        ("duplicate-question-fenced", f"```json\n{duplicate}\n```"),
        ("duplicate-question-prose", f"Review findings:\n{duplicate}\nEnd of review."),
    ]:
        cases.append((name, text, BEFORE, BEFORE))
    for field in ["status", "reasons"]:
        cases.append(
            (
                field + "-missing",
                json.dumps({k: v for k, v in base.items() if k != field}),
                BEFORE,
                BEFORE,
            )
        )
    for value in [True, 1, [], {}, "", "  "]:
        add(f"question-{value!r}", {"human_question": value})
    add("blocked-null", {"status": "blocked"})
    add("old-field", {"question": QUESTION})
    add("contradictory-question", {"question": QUESTION, "human_question": "different"})
    for value in [None, 3, [], "unknown"]:
        add(f"status-{value!r}", {"status": value})
    for value in [None, "reason", [None], [3], [""], ["***"]]:
        add(f"reasons-{value!r}", {"reasons": value})
    add("edited-unchanged", {"status": "edited"})
    add("clean-changed", {}, BEFORE, AFTER)
    add("blocked-no-reason", {"status": "blocked", "human_question": QUESTION}, BEFORE, AFTER)
    add("reason-absent", {"status": "edited", "reasons": ["absent reason"]}, BEFORE, AFTER)
    add("reason-without-motion", {"reasons": [REASON]})
    cases.extend(
        (name, text, BEFORE, BEFORE)
        for name, text in [
            ("missing-object", "no verdict"),
            ("non-object", "[]"),
            ("malformed", '```json\n{"status":\n```'),
            ("ambiguous", report() + "\n" + report()),
        ]
    )
    return cases


def guard_faults():
    fields = {
        "missing-question": (
            'return "", None, "plan disposition must carry explicit human_question"',
            'report["human_question"] = None',
        ),
        "blocked-null": (
            'return "", None, "blocked disposition requires a human_question"',
            "pass",
        ),
        "old-field": (
            'return "", None, f"legacy question is not valid new output: {report[\'question\']}"',
            "pass",
        ),
        "contradictory-question": ('if "question" in report:', "if False:"),
        "edited-unchanged": (
            'problem = "an edited disposition left the plan unchanged"',
            'problem = ""',
        ),
        "reason-without-motion": (
            'problem = "edit reasons reported but the plan is unchanged"',
            'problem = ""',
        ),
        "clean-changed": ('problem = "a clean review changed the plan"', 'problem = ""'),
        "blocked-no-reason": (
            'problem = "every plan edit must carry its reason in the plan file"',
            'problem = ""',
        ),
        "reason-absent": (
            'problem = "every plan edit must carry its reason in the plan file"',
            'problem = ""',
        ),
        "missing-object": (
            'return None, "the plan review wrote no structured disposition"',
            f'return {json.loads(report())!r}, ""',
        ),
        "non-object": (
            'return None, "the plan disposition must be a JSON object"',
            f'return {json.loads(report())!r}, ""',
        ),
        "ambiguous": ("if len(values) > 1:", "if False:"),
        "malformed": (
            "if failed:",
            f'if failed:\n            return {json.loads(report())!r}, ""\n        if False:',
        ),
    }
    faults = []
    for name, text, before, after in invalid_cases():
        if name.startswith("duplicate-question"):
            mutation = ("if key in report:", "if False:")
        elif name.startswith("question-"):
            mutation = (
                'return "", None, "human_question must be null or a non-empty string"',
                'report["human_question"] = question = None',
            )
        elif name.startswith("status-"):
            mutation = (
                'return "", None, "plan disposition status must be clean, edited, or blocked"',
                'report["status"] = status = "clean"',
            )
        elif name.startswith("reasons-"):
            line = (
                'return "", None, "plan reasons must be a JSON list"'
                if not isinstance(json.loads(text).get("reasons"), list)
                else 'return "", None, "every plan edit must carry its reason in the plan file"'
            )
            mutation = (line, 'report["reasons"] = reasons = []')
        else:
            mutation = fields[name]
        if name == "ambiguous":
            mutation = (
                "if len(values) > 1:",
                "if len(values) > 1:\n            values = values[:1]\n        if False:",
            )
        faults.append((name, text, before, after, mutation))
    return faults


def parser_probe(path, text, before, after):
    program = (
        f"import sys; sys.path[:0] = [{str(PLUGIN / 'scripts')!r},"
        f"{str(PLUGIN / 'scripts/spawn')!r}]; "
        f'ns = {{"__file__": {str(path)!r}, "__name__": "probe"}}; '
        f'exec(compile(open({str(path)!r}).read(), {str(path)!r}, "exec"), ns); '
        f'print(ns["evaluate_disposition"]({text!r}, {before!r}, {after!r}))'
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_capped_foreground_plan_review_is_recorded_apart_from_a_dead_reviewer(tmp_path):
    from pathlib import Path

    from spawn_helpers import make_repo, spawn
    from test_spawn_stages import event_roles, stub_stages

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = stub_stages(tmp_path, blocking_plan=True)
    assert spawn(repo, env, "story-042").returncode != 0
    plans = Path(env["XP_DATA"]) / "plans"
    (plans / "story-042.round-2.md").write_text(
        '{"status":"clean","human_question":null,"reasons":[]}'
    )
    marker = plans / "story-042.handoff.json"
    state = json.loads(marker.read_text())
    state["state"], state["stages"]["plan-reviewer"] = "STOPPED", "failed"
    marker.write_text(json.dumps(state))
    seen = len(event_roles(events))
    stub_stages(tmp_path)
    capped = spawn(repo, env, "resume", "story-042")
    assert capped.returncode == 2 and event_roles(events)[seen:] == []
    state = json.loads(marker.read_text())
    assert state["stages"]["plan-reviewer"] == "ran" and "cap" in state["why"]
    assert spawn(repo, env, "resume", "story-042").returncode == 0
    assert event_roles(events)[seen:] == ["teammate", "reviewer"]
