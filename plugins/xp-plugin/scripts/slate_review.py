#!/usr/bin/env python3
"""Run the shipped slate-reviewer charter over a sprint slate."""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

from close import fail, story_card
from work import chdir_repo_root, data_root, missing_plan_refusal, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent
POLL_SECONDS = 3
LOG_TAIL = 2000

ACTIVITY_NOUN = {"slate": "slate review", "plan": "plan review", "refresh": "card refresh"}


def safe_story_id(identifier: str) -> str:
    if not identifier or Path(identifier).name != identifier or identifier in (".", ".."):
        raise ValueError(f"refused: {identifier!r} is not a safe story id")
    return identifier


def review_findings_path(identifier: str, kind: str) -> Path:
    identifier = safe_story_id(identifier)
    parent = data_root() / ("plans" if kind in ("plan", "refresh") else "slate-reviews")
    if kind == "plan":
        stem = identifier
    elif kind == "refresh":
        stem = f"{identifier}.refresh"
    else:
        stem = f"sprint-{identifier}"
    path, round_n = parent / f"{stem}.md", 1
    while path.exists():
        round_n += 1
        path = parent / f"{stem}.round-{round_n}.md"
    return path


def review_marker(identifier: str, kind: str) -> Path:
    r"""One spelling for the writer and the reader. A sprint id is typed by the lead
    and read back by session_start from `### Sprint (\d+)` through int(), so `07`
    and `7` MUST name one marker — two spellings make an incomplete slate review
    indistinguishable from a completed one, and absence of the marker is the
    success signal. A story id is not numeric and survives verbatim."""
    identifier = safe_story_id(identifier)
    suffix = "plan-review-incomplete"
    if kind != "plan":
        suffix = f"{'card-refresh' if kind == 'refresh' else 'slate-review'}-incomplete"
    name = str(int(identifier)) if identifier.isdigit() else identifier
    return data_root() / "markers" / f"{name}.{suffix}"


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
        print(f"joining the {ACTIVITY_NOUN[kind]} already running (pid {pid})", file=sys.stderr)
        return _wait(identifier, kind, out, pid)
    out.parent.mkdir(parents=True, exist_ok=True)
    pid, child = _detach(identifier, kind, out, argv)
    return _wait(identifier, kind, out, pid, child)


def _detach(identifier: str, kind: str, out: Path, argv: list[str]) -> tuple[int, subprocess.Popen]:
    identifier = safe_story_id(identifier)
    log = data_root() / "logs" / f"{identifier}-{ACTIVITY_NOUN[kind].replace(' ', '-')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    marker = review_marker(identifier, kind)
    marker.parent.mkdir(parents=True, exist_ok=True)
    # The scripts ship non-executable, so the pasteable action needs `python3`.
    next_command = shlex.join(["python3", *argv])
    marker.write_text(
        json.dumps(
            {
                "findings": str(out),
                "log": str(log),
                "state": f"{ACTIVITY_NOUN[kind].upper()} DID NOT COMPLETE",
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
    # Do not recreate a marker a fast child already removed as its success signal.
    if state := _marker_state(identifier, kind):
        marker.write_text(json.dumps(state | {"pid": child.pid}))
    print(f"{ACTIVITY_NOUN[kind]} running (pid {child.pid}); live log: {log}", file=sys.stderr)
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
        action = state.get("next", f"run the {ACTIVITY_NOUN[kind]} again")
        log = state.get("log", "(no log)")
        return fail(
            f"{tail}\n(the {ACTIVITY_NOUN[kind]} ended without a verdict; full output in"
            f" {log}; {action})"
        )
    if kind == "refresh":
        return _refresh_handoff(identifier, out)
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


def _slate(sprint_id: str) -> str:
    from sprint_close import sprint_cards

    try:
        return sprint_cards(plan_path().read_text(), sprint_id)
    except OSError:
        return ""


def _inputs(sprint_id: str) -> tuple[str, str, str, str]:
    import review
    from close import config_flat

    return (
        review.charter("slate-reviewer"),
        _slate(sprint_id),
        config_flat("sprint_cap"),
        config_flat("debt_budget"),
    )


def _run_review(sprint_id: str, out: Path, dry_run: bool) -> int:
    import review
    from spawn import tree_state

    charter, cards, sprint_cap, debt_budget = _inputs(sprint_id)
    before = tree_state(Path.cwd()), cards
    _result, error = review.run(
        build_bundle(charter, cards, sprint_cap, debt_budget, out),
        Path.cwd(),
        dry_run,
        name="slate-reviewer",
    )
    if dry_run:
        return fail("refused: " + error) if error else 0
    if (tree_state(Path.cwd()), _slate(sprint_id)) != before:
        return fail(
            "refused: the slate reviewer changed the repository or the slate — restore it"
            " and review again. The plan lives outside the repo, so no diff shows it"
        )
    if error:
        return fail(error)
    try:
        findings = out.read_text().strip()
    except OSError:
        findings = ""
    if not findings:
        return fail(f"refused: the slate reviewer wrote no findings at {out.resolve()}")
    review_marker(sprint_id, "slate").unlink(missing_ok=True)
    print(findings)
    return 0


def cmd_review(sprint_id: str, dry_run: bool) -> int:
    charter, cards, sprint_cap, debt_budget = _inputs(sprint_id)
    if not charter:
        return fail("refused: slate-reviewer.md carries no charter — restore it")
    if not cards:
        return fail(f"refused: no Sprint {sprint_id} slate in {plan_path()}")
    if not sprint_cap:
        return fail("refused: .xp/config.yml carries no sprint_cap")
    if not debt_budget:
        return fail("refused: .xp/config.yml carries no debt_budget")
    out = review_findings_path(sprint_id, "slate")
    if dry_run:
        return _run_review(sprint_id, out, True)
    return run_detached(sprint_id, "slate", out, [str(Path(__file__).resolve()), sprint_id])


def build_refresh_bundle(charter: str, plan_file: Path, card: str, out: Path) -> str:
    from spawn import _read, _read_shipped

    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out.resolve()}"),
        ("The plan file", f"PLAN_PATH: {plan_file}"),
        ("Story card", card),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _run_refresh(story_id: str, out: Path, dry_run: bool) -> int:
    import ready
    import review
    from spawn import tree_state

    try:
        safe_story_id(story_id)
    except ValueError as error:
        return fail(str(error))
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    charter = review.charter("card-refresher")
    plan_before = plan_path().read_text()
    before = tree_state(Path.cwd())
    bundle = build_refresh_bundle(charter, plan_path().resolve(), card, out)
    _result, error = review.run(bundle, Path.cwd(), dry_run, name="card-refresher")
    if dry_run:
        return fail("refused: " + error) if error else 0
    if tree_state(Path.cwd()) != before:
        return fail(
            "refused: the card refresher changed the repository — restore it and refresh again"
        )
    plan_after = plan_path().read_text()
    try:
        new_card, new_status = story_card(plan_after, story_id)
    except KeyError as e:
        return fail(
            f"refused: the card refresher left {story_id} unparsable ({e.args[0]}). Its edit"
            f" stands and no git diff shows it: repair the card in {plan_path()}, then refresh"
        )

    def reject_plan_edit(why: str) -> int:
        # THIS CARD, never plan_before: plan.md is project-global and the refresher ran
        # detached for minutes, so restoring the snapshot silently reverts another lane's
        # write (bug 5a1abadb). Unattributable motion is LEFT and named.
        plan_path().write_text(plan_path().read_text().replace(new_card, card, 1))
        rest = "" if plan_path().read_text() == plan_before else " Text outside it changed too"
        return fail(why + f" Restored the card outside the repo; no git diff shows it.{rest}")

    if new_status != status:
        return reject_plan_edit(
            f"refused: the card refresher changed {story_id}'s status from [{status}] to"
            f" [{new_status}] — it may correct the card only, never its lifecycle state."
        )
    if plan_before.replace(card, new_card, 1) != plan_after:
        return reject_plan_edit(
            "refused: the card refresher moved something outside its own card — it may"
            f" replace only {story_id}'s block in the plan."
        )
    if error:
        return fail(error)
    review_marker(story_id, "refresh").unlink(missing_ok=True)
    ready.write_refresh_receipt(story_id, new_card, new_card != card)
    return 0


def _refresh_handoff(story_id: str, out: Path) -> int:
    import ready

    receipt = ready.refresh_receipt_path(story_id)
    try:
        changed = json.loads(receipt.read_text())["changed"]
    except (OSError, ValueError, KeyError, TypeError):
        return fail(
            f"refused: the card refresh recorded no receipt at {receipt} — refresh {story_id} again"
        )
    state = "the card CHANGED" if changed else "the card was already correct"
    corrections = f"; what it read: {out.resolve()}" if out.is_file() else ""
    print(
        f"{story_id} card refresh ran — {state}. Receipt {receipt}{corrections}."
        f" Read it and the card, then `spawn.py ready {story_id}`"
    )
    return 0


def cmd_refresh(story_id: str, dry_run: bool) -> int:
    import review

    try:
        safe_story_id(story_id)
    except ValueError as error:
        return fail(str(error))
    charter = review.charter("card-refresher")
    if not charter:
        return fail("refused: card-refresher.md carries no charter — restore it")
    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    out = review_findings_path(story_id, "refresh")
    if dry_run:
        return _run_refresh(story_id, out, True)
    argv = [str(Path(__file__).resolve()), story_id, "--refresh"]
    return run_detached(story_id, "refresh", out, argv)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier", metavar="sprint-id-or-story-id")
    parser.add_argument(
        "--refresh", action="store_true", help="refresh one story card against HEAD, not a review"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--_review", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if args._review:
        if args.refresh:
            return _run_refresh(args.identifier, Path(args._review), False)
        return _run_review(args.identifier, Path(args._review), False)
    if args.refresh:
        return cmd_refresh(args.identifier, args.dry_run)
    return cmd_review(args.identifier, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
