#!/usr/bin/env python3
"""Run the shipped slate-reviewer charter over a sprint slate."""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

from close import fail, git, story_card
from env import sprint_branch, sprint_branch_name
from plan_writer import strip_lifecycle
from review_runner import ACTIVITY_NOUN as ACTIVITY_NOUN
from review_runner import _dead as _dead
from review_runner import _detach as _detach
from review_runner import (
    _marker_state,
    archive_failed_findings,
    review_findings_path,
    review_is_capped,
    review_marker,
    review_prior,
    run_detached,
    safe_story_id,
)
from review_runner import _running as _running
from review_runner import _wait as _wait
from review_runner import subprocess as subprocess
from review_scope import declared_files
from work import (
    card_digest,
    chdir_repo_root,
    edit_plan,
    flip_status,
    missing_plan_refusal,
    plan_path,
)

PLUGIN_ROOT = Path(__file__).parent.parent


def build_bundle(
    charter: str,
    cards: str,
    sprint_cap: str,
    debt_budget: str,
    out: Path,
    prior: str = "",
) -> str:
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
    if prior:
        sections.insert(4, ("Findings from prior rounds", prior))
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
    prior, problem = review_prior(sprint_id, "slate")
    if problem:
        return fail(problem)
    before = tree_state(Path.cwd()), cards
    _result, error = review.run(
        build_bundle(charter, cards, sprint_cap, debt_budget, out, prior),
        Path.cwd(),
        dry_run,
        name="slate-reviewer",
    )
    if dry_run:
        return fail("refused: " + error) if error else 0

    # A refused round is not a round: left in place it spends one of the two the cap
    # allows, and two dead reviewers would lock the slate out of every review it has
    # yet to get, under a refusal telling the lead to judge findings nobody wrote.
    def refused(message: str) -> int:
        return fail(message + archive_failed_findings(out))

    if (tree_state(Path.cwd()), _slate(sprint_id)) != before:
        return refused(
            "refused: the slate reviewer changed the repository or the slate — restore it"
            " and review again. The plan lives outside the repo, so no diff shows it"
        )
    if error:
        return refused(error)
    try:
        findings = out.read_text().strip()
    except OSError:
        findings = ""
    if not findings:
        return refused(f"refused: the slate reviewer wrote no findings at {out.resolve()}")
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
    _prior, problem = review_prior(sprint_id, "slate")
    if problem:
        return fail(problem)
    # A round already launched under the cap writes its findings file while it runs, so
    # counting alone would refuse the rejoin the lead is told to use instead of relaunching
    # — stranding the live round's marker and reading its half-written file as a round.
    if review_is_capped(sprint_id, "slate") and not _running(sprint_id, "slate"):
        if sprint_branch() == sprint_branch_name(sprint_id):
            return fail(
                "refused: two slate-review rounds already exist — the dead attempt owes nothing;"
                " continue with the cards"
            )
        return fail(
            "refused: two slate-review rounds already exist — judge and apply their findings,"
            " then open the sprint"
        )
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

        def refuse(message: str) -> int:
            action = ready.refresh_instruction(story_id)
            refusal = message if action in message else f"{message} {action}"
            # Archive as the slate and plan paths do, but for a reason only this one
            # has: refresh is read by no cap and no prior-findings render, and the
            # retry REUSES this round path, so text left here is what the "wrote no
            # findings" guard below reads when the next refresher writes none.
            refusal += archive_failed_findings(out)
            marker = review_marker(story_id, "refresh")
            marker.write_text(json.dumps(_marker_state(story_id, "refresh") | {"refusal": refusal}))
            return fail(refusal)

        if tree_state(Path.cwd()) != before:
            return refuse(
                "refused: the card refresher changed the repository — restore it and refresh again"
            )
        plan_after = plan_path().read_text()
        try:
            current_card, current_status = story_card(plan_after, story_id)
        except KeyError as e:
            return refuse(
                f"refused: the card refresher left {story_id} unparsable ({e.args[0]}). Its edit"
                f" stands and no git diff shows it: repair the card in {plan_path()}, then refresh"
            )
        try:
            candidate_text = candidate.read_text()
            new_card, new_status = story_card(candidate_text, story_id)
            if new_card.rstrip() != candidate_text.rstrip():
                raise KeyError("candidate contains text outside its one story card")
        except (OSError, KeyError) as e:
            return refuse(
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
            return refuse(
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
            return refuse(
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
            return refuse(error)
        try:
            findings = out.read_text().strip()
        except OSError:
            findings = ""
        if not findings:
            return refuse(f"refused: the card refresher wrote no findings at {out.resolve()}")
        if problem := ready.write_refresh_receipt(story_id, current_card, candidate_changed):
            return refuse(problem)
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
        card, _status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if not dry_run:
        import ready

        try:
            paths = sorted(declared_files(card))
        except ValueError as error:
            return fail(ready.UNPARSABLE.format(error, plan_path(), story_id))
        pathspecs = [f":(literal){path}" for path in paths]
        state = git("status", "--porcelain", "--untracked-files=all", "--", *pathspecs, check=False)
        if state.returncode:
            return fail("refused: cannot read the declared paths' working-tree state")
        if dirty := state.stdout.strip():
            return fail(
                "refused: card refresh reads declared paths from HEAD, but these paths have"
                f" working-tree edits:\n{dirty}\nCommit or restore them, then refresh again"
            )
        receipt, path_problem = ready.refresh_path_receipt(story_id, card)
        if not path_problem:
            if receipt.get("digest") == card_digest(card):
                return fail(
                    "refused: the receipt is current. " + ready.refresh_instruction(story_id)
                )
            if problem := ready.remint_refresh_receipt(story_id, card, receipt):
                return fail(problem)
            print(
                f"{story_id} receipt re-minted locally; no agent ran."
                f" Next run `spawn.py ready {story_id}`"
            )
            return 0
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
