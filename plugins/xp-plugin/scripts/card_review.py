#!/usr/bin/env python3
"""Run the shipped card-reviewer charter over a sprint slate."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))

from close import fail
from work import chdir_repo_root, data_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent
POLL_SECONDS = 3
LOG_TAIL = 2000


def review_findings_path(identifier: str, kind: str) -> Path:
    parent = data_root() / ("plans" if kind == "plan" else "card-reviews")
    stem = identifier if kind == "plan" else f"sprint-{identifier}"
    path, round_n = parent / f"{stem}.md", 1
    while path.exists():
        round_n += 1
        path = parent / f"{stem}.round-{round_n}.md"
    return path


def review_marker(identifier: str, kind: str) -> Path:
    suffix = "plan-review-incomplete" if kind == "plan" else "card-review-incomplete"
    return data_root() / "markers" / f"{identifier}.{suffix}"


def _marker_state(identifier: str, kind: str) -> dict:
    try:
        return json.loads(review_marker(identifier, kind).read_text())
    except (OSError, ValueError):
        return {}


def _running(identifier: str, kind: str) -> tuple[Path, int] | None:
    state = _marker_state(identifier, kind)
    pid, out = state.get("pid"), state.get("findings")
    if not (pid and out):
        return None
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return None
    return Path(out), int(pid)


def run_detached(identifier: str, kind: str, out: Path, argv: list[str]) -> int:
    if running := _running(identifier, kind):
        out, pid = running
        print(f"joining the {kind} review already running (pid {pid})", file=sys.stderr)
        return _wait(identifier, kind, out, pid)
    out.parent.mkdir(parents=True, exist_ok=True)
    pid, child = _detach(identifier, kind, out, argv)
    return _wait(identifier, kind, out, pid, child)


def _detach(identifier: str, kind: str, out: Path, argv: list[str]) -> tuple[int, subprocess.Popen]:
    log = data_root() / "logs" / f"{identifier}-{kind}-review.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    marker = review_marker(identifier, kind)
    marker.parent.mkdir(parents=True, exist_ok=True)
    label = kind.upper()
    next_command = " ".join(argv[:-2]) if argv[-2:] == ["--_review", str(out)] else " ".join(argv)
    marker.write_text(
        json.dumps(
            {
                "findings": str(out),
                "log": str(log),
                "state": f"{label} REVIEW DID NOT COMPLETE",
                "next": f"run {next_command} again to join or restart it",
            }
        )
    )
    handle = open(log, "a")  # noqa: SIM115 — the detached child owns it
    child = subprocess.Popen(
        [sys.executable, *argv, "--_review", str(out)],
        cwd=Path.cwd(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    state = _marker_state(identifier, kind) | {"pid": child.pid}
    marker.write_text(json.dumps(state))
    print(f"{kind} review running (pid {child.pid}); live log: {log}", file=sys.stderr)
    return child.pid, child


def _wait(
    identifier: str,
    kind: str,
    out: Path,
    pid: int,
    child: subprocess.Popen | None = None,
) -> int:
    state = _marker_state(identifier, kind)
    while not _dead(pid, child):
        time.sleep(POLL_SECONDS)
    marker = review_marker(identifier, kind)
    if marker.exists():
        try:
            tail = Path(state.get("log", "")).read_text(errors="replace")[-LOG_TAIL:].strip()
        except OSError:
            tail = ""
        action = state.get("next", f"run the {kind} review again")
        return fail(f"{tail}\n(the {kind} review ended without a verdict; {action})")
    print(out.read_text().strip() if out.is_file() else "")
    handoff = (
        "read the disposition and re-read the reviewed plan before coding"
        if kind == "plan"
        else "read every finding before accepting or rejecting its conclusion"
    )
    print(f"findings: {out.resolve()} — {handoff}", file=sys.stderr)
    return 0


def _dead(pid: int, child: subprocess.Popen | None) -> bool:
    if child is not None:
        return child.poll() is not None
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


def build_bundle(charter: str, cards: str, sprint_cap: str, debt_budget: str, out: Path) -> str:
    from spawn import _read, _read_shipped

    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out.resolve()}"),
        ("Full proposed slate", cards),
        ("Sprint capacity", f"sprint_cap: {sprint_cap}\ndebt_budget: {debt_budget}"),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _inputs(sprint_id: str) -> tuple[str, str, str, str]:
    import review
    from close import config_flat
    from sprint_close import sprint_cards

    try:
        cards = sprint_cards(plan_path().read_text(), sprint_id)
    except OSError:
        cards = ""
    return (
        review.charter("card-reviewer"),
        cards,
        config_flat("sprint_cap"),
        config_flat("debt_budget"),
    )


def _run_review(sprint_id: str, out: Path, dry_run: bool) -> int:
    import review
    from spawn import tree_state

    charter, cards, sprint_cap, debt_budget = _inputs(sprint_id)
    before = tree_state(Path.cwd())
    _result, error = review.run(
        build_bundle(charter, cards, sprint_cap, debt_budget, out),
        Path.cwd(),
        dry_run,
        name="card-reviewer",
    )
    if dry_run:
        return fail("refused: " + error) if error else 0
    if tree_state(Path.cwd()) != before:
        return fail(
            "refused: the card reviewer changed the repository — restore it and review again"
        )
    if error:
        return fail(error)
    try:
        findings = out.read_text().strip()
    except OSError:
        findings = ""
    if not findings:
        return fail(f"refused: the card reviewer wrote no findings at {out.resolve()}")
    review_marker(sprint_id, "card").unlink(missing_ok=True)
    print(findings)
    return 0


def cmd_review(sprint_id: str, dry_run: bool) -> int:
    charter, cards, sprint_cap, debt_budget = _inputs(sprint_id)
    if not charter:
        return fail("refused: card-reviewer.md carries no charter — restore it")
    if not cards:
        return fail(f"refused: no Sprint {sprint_id} slate in {plan_path()}")
    if not sprint_cap:
        return fail("refused: .xp/config.yml carries no sprint_cap")
    if not debt_budget:
        return fail("refused: .xp/config.yml carries no debt_budget")
    out = review_findings_path(sprint_id, "card")
    if dry_run:
        return _run_review(sprint_id, out, True)
    return run_detached(sprint_id, "card", out, [str(Path(__file__).resolve()), sprint_id])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sprint_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--_review", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if args._review:
        return _run_review(args.sprint_id, Path(args._review), False)
    return cmd_review(args.sprint_id, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
