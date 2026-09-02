#!/usr/bin/env python3
"""Plan review as a headless role through the runner both harnesses use.

Codex teammates have neither `--plugin-dir` nor subagents; the script is what
makes the shipped charter reachable there.
"""

import argparse
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

import review
from card_review import review_findings_path, review_marker, run_detached
from close import fail, story_card
from spawn import _read, _read_shipped, tree_state
from work import chdir_repo_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent


def findings_path(story_id: str) -> Path:
    """The charter's own rule, computed HERE so the reviewer is handed exactly one
    absolute path: <story-id>.md, then <story-id>.round-N.md beside it. One name
    for a file written once per round destroys the earlier round on write."""
    return review_findings_path(story_id, "plan")


def incomplete_marker(story_id: str) -> Path:
    """Written BEFORE the reviewer launches and removed only on findings.

    Inverted deliberately: the failure that matters kills the process (codex's
    shell timeout_ms is model-supplied, ~10s by default, and a review runs
    minutes), and a killed process writes nothing on its way out. So absence of
    the marker is the success signal, and its presence outlives any death.
    """
    return review_marker(story_id, "plan")


def card_for(story_id: str) -> str:
    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError):
        return ""


def build_bundle(charter: str, plan: str, card: str, plan_file: Path, out: Path) -> str:
    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out}"),
        ("The plan file", f"PLAN_PATH: {plan_file}"),
        ("The plan under review", plan),
        ("Story card", card),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def review_state(plan_file: Path, story_id: str) -> tuple[str, str, str]:
    """State a plan reviewer must leave unchanged outside its draft.

    THIS STORY'S OWN CARD, never the whole plan: plan.md is project-global and the
    lead edits it throughout a run — status flips, re-mints, a sibling lane's card
    — so a whole-file digest refuses a review that did nothing wrong, and blames
    the reviewer by name for it (bug 5a1abadb, which cost story-032 a full run).
    close.review.check_reviewer_motion already scopes its card check this way.
    """

    head, porcelain = tree_state(Path.cwd())
    try:
        relative = str(plan_file.relative_to(Path.cwd()))
    except ValueError:
        relative = ""
    if relative:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", f":(exclude){relative}"],
            capture_output=True,
            text=True,
        )
        if status.returncode:
            raise OSError(status.stderr.strip())
        porcelain = status.stdout.strip()
    return head, porcelain, card_for(story_id)


def plan_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def normalized_whitespace(text: str) -> str:
    """Whitespace AND the markdown quote marker, because a blockquote is how a
    reviewer sets a reason apart: it carries a `> ` on every wrapped line that
    the reason string it also reports cannot (bug 6677e018 — six reasoned edits
    landed in a plan and the whole round was discarded over the prefix)."""
    return " ".join(w for ln in text.splitlines() for w in ln.lstrip("> ").split())


def disposition(text: str, before: bytes | None, after: bytes | None) -> str:
    changed = before != after
    try:
        report = json.loads(text)
    except ValueError:
        values = []
        for fence in re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.S):
            with contextlib.suppress(ValueError):
                values.append(json.loads(fence))
        # A non-object in a fence is no rival verdict — kept only when none is an object,
        # so a fenced `[]` refuses by TYPE. Narrowing either discards a completed round.
        values = [v for v in values if isinstance(v, dict)] or values
        if len(values) == 1:
            report = values[0]
        elif len(values) > 1:
            return "the plan review wrote an ambiguous disposition — write exactly one JSON object"
        else:
            decoder, objects, end = json.JSONDecoder(), [], 0
            for start in (i for i, char in enumerate(text) if char == "{"):
                if start < end:
                    continue
                try:
                    value, end = decoder.raw_decode(text, start)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    objects.append(value)
            if len(objects) > 1:
                return (
                    "the plan review wrote an ambiguous disposition — write exactly one JSON object"
                )
            return "the plan review wrote no structured disposition"
    if not isinstance(report, dict):
        return "the plan disposition must be a JSON object"
    status = report.get("status")
    if status == "blocked":
        question = report.get("question", "")
        if changed:
            return "a human-only question changed the plan instead of stopping"
        return f"blocked for the human: {question}" if question else "blocked without a question"
    if status == "clean":
        return "" if not changed else "a clean review changed the plan"
    if status != "edited":
        return "plan disposition status must be clean, edited, or blocked"
    reasons = report.get("reasons", [])
    if not isinstance(reasons, list):
        return "edited plan reasons must be a JSON list"
    plan = (after or b"").decode(errors="replace")
    if not changed:
        return "an edited disposition left the plan unchanged"
    normalized_plan = normalized_whitespace(plan)
    if not reasons or not all(
        isinstance(reason, str) and normalized_whitespace(reason) in normalized_plan
        for reason in reasons
    ):
        return "every plan edit must carry its reason in the plan file"
    return ""


def cmd_review(story_id: str, plan_file: Path, dry_run: bool) -> int:
    if not plan_file.is_file():
        return fail(f"refused: no plan at {plan_file} — draft it to a file first")
    plan = plan_file.read_text()
    if not plan.strip():
        return fail(f"refused: the draft plan at {plan_file} is empty")
    # An empty read would spend a whole review on no rubric and still exit 0 with
    # plausible prose: nothing downstream can tell that from a real round.
    charter = review.charter("plan-reviewer")
    if not charter:
        return fail(
            f"refused: {PLUGIN_ROOT / 'agents' / 'plan-reviewer.md'} carries no charter"
            " — a review with an empty rubric certifies. Restore the file"
        )
    card = card_for(story_id)
    if not card:
        return fail(f"refused: no {story_id} card in {plan_path()}")
    if dry_run:
        return _run_review(story_id, plan_file, charter, plan, card, findings_path(story_id), True)
    return run_detached(
        story_id,
        "plan",
        findings_path(story_id),
        [str(Path(__file__).resolve()), story_id, str(plan_file)],
    )


def _run_review(
    story_id: str, plan_file: Path, charter: str, plan: str, card: str, out: Path, dry_run: bool
) -> int:
    try:
        before = review_state(plan_file, story_id)
    except OSError as e:
        return fail(f"refused: cannot snapshot the repository before review: {e}")
    before_plan = plan_bytes(plan_file)
    bundle = build_bundle(charter, plan, card, plan_file, out)
    _result, err = review.run(bundle, Path.cwd(), dry_run, name="plan-reviewer", card=card)
    if dry_run:
        return fail("refused: " + err) if err else 0
    try:
        changed = review_state(plan_file, story_id) != before
    except OSError as e:
        return fail(f"refused: the plan reviewer left the repository unreadable: {e}")
    if changed:
        return fail(
            "refused: the plan reviewer changed the repository or story card"
            " — inspect and restore its changes before continuing"
        )
    if err:
        return fail(err)
    try:
        findings = out.read_text().strip() if out.is_file() else ""
    except OSError:
        findings = ""
    if not findings:
        return fail(f"refused: the plan reviewer wrote no findings at {out}")
    if problem := disposition(findings, before_plan, plan_bytes(plan_file)):
        return fail(f"refused: {problem}")
    incomplete_marker(story_id).unlink(missing_ok=True)  # the child's own verdict
    print(findings)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("story_id")
    p.add_argument("plan_file", help="the draft plan to review")
    p.add_argument("--dry-run", action="store_true")
    # the detached half re-enters here; not a user surface, hence the name
    p.add_argument("--_review", default="", help=argparse.SUPPRESS)
    a = p.parse_args()
    # resolved BEFORE the chdir, or a relative path names a different file after it
    plan_file = Path(a.plan_file).resolve()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if a._review:
        charter = review.charter("plan-reviewer")
        card = card_for(a.story_id)
        return _run_review(
            a.story_id, plan_file, charter, plan_file.read_text(), card, Path(a._review), False
        )
    return cmd_review(a.story_id, plan_file, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
