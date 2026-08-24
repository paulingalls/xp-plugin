#!/usr/bin/env python3
"""Plan review as a headless role through the runner both harnesses use.

Codex teammates have neither `--plugin-dir` nor subagents; the script is what
makes the shipped charter reachable there.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

import review
from close import fail, story_card
from spawn import _read, _read_shipped, tree_state
from work import chdir_repo_root, data_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent
POLL_SECONDS = 3
LOG_TAIL = 2000


def findings_path(story_id: str) -> Path:
    """The charter's own rule, computed HERE so the reviewer is handed exactly one
    absolute path: <story-id>.md, then <story-id>.round-N.md beside it. One name
    for a file written once per round destroys the earlier round on write."""
    plans = data_root() / "plans"
    path, n = plans / f"{story_id}.md", 1
    while path.exists():
        n += 1
        path = plans / f"{story_id}.round-{n}.md"
    return path


def incomplete_marker(story_id: str) -> Path:
    """Written BEFORE the reviewer launches and removed only on findings.

    Inverted deliberately: the failure that matters kills the process (codex's
    shell timeout_ms is model-supplied, ~10s by default, and a review runs
    minutes), and a killed process writes nothing on its way out. So absence of
    the marker is the success signal, and its presence outlives any death.
    """
    return data_root() / "markers" / f"{story_id}.plan-review-incomplete"


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
        ("Story card", card or "none in the plan — judge the plan on its own"),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
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


def disposition(text: str, before: bytes | None, after: bytes | None) -> str:
    changed = before != after
    try:
        report = json.loads(text)
    except ValueError:
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
    if not reasons or not all(isinstance(reason, str) and reason in plan for reason in reasons):
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
    if running := _running(story_id):
        out, pid = running
        print(f"joining the review already running for {story_id} (pid {pid})", file=sys.stderr)
    else:
        out = findings_path(story_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        pid, child = _detach(story_id, plan_file, out)
        return _wait(story_id, out, pid, child)
    return _wait(story_id, out, pid)


def _marker_state(story_id: str) -> dict:
    try:
        return json.loads(incomplete_marker(story_id).read_text())
    except (OSError, ValueError):
        return {}


def _running(story_id: str) -> tuple[Path, int] | None:
    """(findings path, pid) of a review still going, or None.

    A caller killed mid-wait must JOIN rather than launch a second reviewer: the
    first one is still writing, and two would race for one findings path.
    """
    state = _marker_state(story_id)
    pid, out = state.get("pid"), state.get("findings")
    if not (pid and out):
        return None
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return None
    return Path(out), int(pid)


def _detach(story_id: str, plan_file: Path, out: Path) -> tuple[int, subprocess.Popen]:
    """Launch the review in its OWN session, so a caller's death is not its own.

    Measured, both harnesses: a codex tool call is killed at a timeout the MODEL
    chose (~10s by default), and a headless claude run ends when the model yields
    — either takes a foreground review with it, and a plain background job dies
    with its parent's group.
    """
    log = data_root() / "logs" / f"{story_id}-plan-review.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    marker = incomplete_marker(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "a")  # noqa: SIM115 — owned by the detached child, not by us
    child = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            story_id,
            str(plan_file),
            "--_review",
            str(out),
        ],
        cwd=Path.cwd(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    marker.write_text(
        json.dumps(
            {"pid": child.pid, "findings": str(out), "log": str(log), "plan": str(plan_file)}
        )
    )
    print(f"plan review running (pid {child.pid}); live log: {log}", file=sys.stderr)
    return child.pid, child


def _wait(story_id: str, out: Path, pid: int, child: subprocess.Popen | None = None) -> int:
    """Block until the review PROCESS ends, then read its verdict off the marker.

    Not "until findings appear": the reviewer writes them before the motion guards
    run, so returning on the file would report a review that its own guards went on
    to refuse. The child clears the marker only when it is satisfied, which makes
    the marker's absence the success signal for the joiner too — a joiner is not
    the child's parent and has no exit code to read.

    The caller may be killed in this loop and nothing is lost: the marker holds
    the pid and the next call joins.
    """
    log = _marker_state(story_id).get("log", "(no log)")
    while not _dead(pid, child):
        time.sleep(POLL_SECONDS)
    if incomplete_marker(story_id).exists():
        # the child's own refusal, not a summary of it: WHY it refused is the whole
        # value, and the caller cannot read the log of a process it did not start
        try:
            tail = Path(log).read_text(errors="replace")[-LOG_TAIL:].strip()
        except OSError:
            tail = ""
        return fail(f"{tail}\n(the plan review ended without a verdict; full output in {log})")
    print(out.read_text().strip() if out.is_file() else "")
    print(f"findings: {out}", file=sys.stderr)
    return 0


def _dead(pid: int, child: subprocess.Popen | None) -> bool:
    """poll() when we are the parent, signal 0 when we are only a joiner.

    os.kill(pid, 0) succeeds against a ZOMBIE, and an unreaped child is exactly
    what a launched-then-exited reviewer leaves — waiting on that never ends.
    """
    if child is not None:
        return child.poll() is not None
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


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
        return 0
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
