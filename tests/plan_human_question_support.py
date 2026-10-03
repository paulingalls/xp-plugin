import json
import re
import subprocess
import sys

from spawn_helpers import make_repo, spawn
from spawn_stages_support import stub_stages
from test_plan_review import PLUGIN
from test_spawn_stages import event_roles

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
                else 'return "", None, "plan reasons must contain non-empty text"'
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


def consumer(tmp_path, status="edited"):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = stub_stages(tmp_path)
    binary = tmp_path / "bin/claude"
    text = binary.read_text()
    text = text.replace("'# execution plan\\nred then green\\n'", repr(BEFORE.decode()))
    clean = json.dumps({"status": "clean", "human_question": None, "reasons": []})
    payload = report(status, QUESTION, [REASON] if status != "clean" else [])
    text = text.replace(repr(clean), repr(payload))
    if status != "clean":
        text = text.replace(
            "elif role == 'plan-reviewer':\n",
            "elif role == 'plan-reviewer':\n"
            " plan = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M)\n"
            f" open(plan.group(1), 'a').write({AFTER[len(BEFORE) :].decode()!r})\n",
        )
    binary.write_text(text)
    return repo, env, seen


def answer(tmp_path, repo, env, launch=spawn):
    card = tmp_path / "data/plan.md"
    card.write_text(
        card.read_text().replace("Context: demo.", "Context: human chose local storage.")
    )
    result = launch(repo, env, "amend", "story-042", "--reason", "human chose local storage")
    assert result.returncode == 0, result.stderr
    for binary in (tmp_path / "bin").iterdir():
        text = binary.read_text()
        text = text.replace(
            repr(report("edited", QUESTION, [REASON])),
            repr(
                report(
                    "edited",
                    None,
                    [REASON],
                )
            ),
        )
        text = text.replace(
            repr(report("blocked", QUESTION, [REASON])), repr(report("edited", None, [REASON]))
        )
        binary.write_text(text)


def repeated_stop(tmp_path, repo, env, seen, launch=spawn):
    for args in [
        ("story-042",),
        ("resume", "story-042"),
        ("resume", "story-042"),
        ("resume", "story-042"),
    ]:
        assert launch(repo, env, *args).returncode != 0
    assert event_roles(seen).count("plan-reviewer") == 1
    assert "teammate" not in event_roles(seen)
    assert not (tmp_path / "data/plans/story-042.round-3.md").exists()
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert QUESTION in state["why"]


def answered_resume(tmp_path, repo, env, seen, launch=spawn):
    answer(tmp_path, repo, env, launch)
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    event = next(
        json.loads(line)
        for line in seen.read_text().splitlines()
        if json.loads(line)["role"] == "teammate"
    )
    path = re.search(r"^Plan-review findings: (.+)$", event["prompt"], re.M).group(1)
    current = json.loads(__import__("pathlib").Path(path).read_text())
    assert current["human_question"] is None
    assert REASON in current["reasons"]
    assert "human chose local storage" in event["prompt"]
