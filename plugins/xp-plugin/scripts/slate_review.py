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
from env import sprint_id_value
from plan_writer import strip_lifecycle
from work import (
    card_digest,
    chdir_repo_root,
    data_root,
    edit_plan,
    flip_status,
    missing_plan_refusal,
    plan_path,
)

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
    legacy = parent / f"{stem}.md"
    rounds = [1] if legacy.exists() else []
    prefix = f"{stem}.round-"
    if parent.is_dir():
        for path in parent.iterdir():
            name = path.name
            if not (name.startswith(prefix) and name.endswith(".md")):
                continue
            encoded = name[len(prefix) : -3]
            if encoded.isdecimal() and int(encoded) > 0 and encoded == str(int(encoded)):
                rounds.append(int(encoded))
    return parent / f"{stem}.round-{max(rounds, default=0) + 1}.md"


def review_marker(identifier: str, kind: str) -> Path:
    """sprint_id_value is session_start's spelling too: two spellings make an
    incomplete review look completed, because a missing marker is the success signal."""
    identifier = safe_story_id(identifier)
    suffix = "plan-review-incomplete"
    if kind != "plan":
        suffix = f"{'card-refresh' if kind == 'refresh' else 'slate-review'}-incomplete"
    return data_root() / "markers" / f"{sprint_id_value(identifier)}.{suffix}"


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
    while not _dead(pid, child):
        time.sleep(POLL_SECONDS)
    marker = review_marker(identifier, kind)
    state = _marker_state(identifier, kind)
    if marker.exists():
        if refusal := state.get("refusal"):
            return fail(refusal)
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


def build_refresh_bundle(
    charter: str, card_file: Path, edit_command: str, card: str, out: Path
) -> str:
    from spawn import _read, _read_shipped

    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out.resolve()}"),
        ("Your card file", f"CARD_PATH: {card_file}"),
        ("The locked plan edit", f"PLAN_EDIT_COMMAND: {edit_command}"),
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
    candidate = out.with_name(f"{out.name}.{os.getpid()}.card")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(card)
    command = shlex.join(
        [
            "python3",
            str(Path(__file__).with_name("work.py").resolve()),
            "edit-card",
            story_id,
            "--digest",
            card_digest(card),
            "--status",
            status,
            str(candidate.resolve()),
        ]
    )
    bundle = build_refresh_bundle(charter, candidate.resolve(), command, card, out)
    try:
        _result, error = review.run(bundle, Path.cwd(), dry_run, name="card-refresher")
        if dry_run:
            return fail("refused: " + error) if error else 0
        if tree_state(Path.cwd()) != before:
            return fail(
                "refused: the card refresher changed the repository — restore it and refresh again"
            )
        plan_after = plan_path().read_text()
        try:
            current_card, current_status = story_card(plan_after, story_id)
        except KeyError as e:
            return fail(
                f"refused: the card refresher left {story_id} unparsable ({e.args[0]}). Its edit"
                f" stands and no git diff shows it: repair the card in {plan_path()}, then refresh"
            )
        try:
            candidate_text = candidate.read_text()
            new_card, new_status = story_card(candidate_text, story_id)
            if new_card.rstrip() != candidate_text.rstrip():
                raise KeyError("candidate contains text outside its one story card")
        except (OSError, KeyError) as e:
            return fail(
                f"refused: card refresh {story_id} left its candidate unparsable ({e.args[0]}). "
                f"{ready.refresh_instruction(story_id)}"
            )

        def reject_plan_edit(why: str) -> int:
            def restore(text: str) -> str:
                try:
                    found, found_status = story_card(text, story_id)
                except KeyError:
                    return text
                restored = flip_status(card, f"#### {story_id} ", status, found_status)
                return text.replace(found, restored, 1)

            edit_plan(restore)
            rest = "" if plan_path().read_text() == plan_before else " Text outside it changed too"
            return fail(
                why
                + f" Restored the card outside the repo; no git diff shows it.{rest} "
                + ready.refresh_instruction(story_id)
            )

        if new_status != status:
            return reject_plan_edit(
                f"refused: card refresh {story_id} changed lifecycle [{status}] to [{new_status}]."
            )
        candidate_changed = new_card != card
        target_changed = current_card != card
        if not candidate_changed and target_changed:
            return reject_plan_edit(
                f"refused: card refresh {story_id} wrote plan.md directly instead of its candidate."
            )
        if candidate_changed and current_card == card:
            return fail(
                f"refused: card refresh {story_id} changed its candidate but did not apply it. "
                f"{ready.refresh_instruction(story_id)}"
            )
        if candidate_changed and current_card != new_card:
            return reject_plan_edit(
                f"refused: card refresh {story_id} applied text other than its candidate."
            )
        outside_changed = strip_lifecycle(
            plan_before.replace(card, current_card, 1)
        ) != strip_lifecycle(plan_after)
        if outside_changed:
            print(
                "card refresh observation: text outside its own card changed too",
                file=sys.stderr,
            )
        if current_status != status:
            return reject_plan_edit(
                f"refused: card refresh {story_id} changed lifecycle [{status}] to"
                f" [{current_status}]."
            )
        if error:
            return fail(error)
        try:
            findings = out.read_text().strip()
        except OSError:
            findings = ""
        if not findings:
            return fail(f"refused: the card refresher wrote no findings at {out.resolve()}")
        if problem := ready.write_refresh_receipt(story_id, current_card, candidate_changed):
            marker = review_marker(story_id, "refresh")
            marker.write_text(json.dumps(_marker_state(story_id, "refresh") | {"refusal": problem}))
            return fail(problem)
        review_marker(story_id, "refresh").unlink(missing_ok=True)
        if outside_changed:
            receipt = ready.refresh_receipt_path(story_id)
            payload = json.loads(receipt.read_text())
            payload["observation"] = "Text outside the refreshed card changed too."
            receipt.write_text(json.dumps(payload, ensure_ascii=False))
        return 0
    finally:
        candidate.unlink(missing_ok=True)


def _refresh_handoff(story_id: str, out: Path) -> int:
    import ready

    receipt = ready.refresh_receipt_path(story_id)
    try:
        payload = json.loads(receipt.read_text())
        changed = payload["changed"]
    except (OSError, ValueError, KeyError, TypeError):
        return fail(
            f"refused: the card refresh recorded no receipt at {receipt} — refresh {story_id} again"
        )
    state = "the card CHANGED" if changed else "the card was already correct"
    corrections = f"; what it read: {out.resolve()}" if out.is_file() else ""
    observation = f" {payload.get('observation', '')}" if payload.get("observation") else ""
    print(
        f"{story_id} card refresh ran — {state}. Receipt {receipt}{corrections}."
        f"{observation} Read it and the card, then `spawn.py ready {story_id}`"
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
