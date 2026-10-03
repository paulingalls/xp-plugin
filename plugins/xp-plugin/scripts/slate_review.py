#!/usr/bin/env python3
"""Run the shipped slate-reviewer charter over a sprint slate."""

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

from close import fail
from env import sprint_branch, sprint_branch_name
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
)
from review_runner import _running as _running
from review_runner import _wait as _wait
from review_runner import subprocess as subprocess
from work import (
    chdir_repo_root,
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
        (
            "Record lookup",
            "Append the cited ID; XP_DATA is already set.\nRECORD_LOOKUP: "
            + shlex.join([sys.executable, str(PLUGIN_ROOT / "scripts/work.py"), "show"]),
        ),
        ("Full proposed slate", cards),
        ("Sprint capacity", f"sprint_cap: {sprint_cap}\ndebt_budget: {debt_budget}"),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),
        ("Shipped card template", _read_shipped(PLUGIN_ROOT / "templates/plan.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    if prior:
        sections.insert(4, ("Findings from prior rounds", prior))
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _slate(sprint_id: str) -> str:
    from milestone import find
    from sprint_close import sprint_cards

    try:
        text = plan_path().read_text()
        cards = sprint_cards(text, sprint_id)
        if cards and (owner := find(text, sprint_id)):
            header = owner.block.split("\n### ", 1)[0]
            fields = [
                line for line in header.splitlines() if line.startswith(("Goal:", "Done when:"))
            ]
            return "\n".join([owner.heading.rstrip(), *fields, cards])
        return cards
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


def _complete_verdict(cards: str, findings: str) -> bool:
    card_ids = re.findall(r"^#### ([^\s]+) — ", cards, re.M)
    if not card_ids:
        return False
    headings = re.findall(r"^## ([^\n]+) — (?:RED|GREEN)$", findings, re.M)
    return all(headings.count(identifier) == 1 for identifier in [*card_ids, "Slate"])


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

    # A dead reviewer spends a round only if it left a complete verdict to judge; any
    # other dead round counted would let two of them lock the slate out of its review.
    def refused(message: str) -> int:
        return fail(message + archive_failed_findings(out))

    if (tree_state(Path.cwd()), _slate(sprint_id)) != before:
        return refused(
            "refused: the slate reviewer changed the repository or the slate — restore it"
            " and review again. The plan lives outside the repo, so no diff shows it"
        )
    try:
        findings = out.read_text()
    except OSError:
        findings = ""
    if error:
        if _complete_verdict(cards, findings):
            error += (
                f"\nits complete verdict at {out.resolve()} spent this round — judge those"
                " findings before reviewing again"
            )
            marker = review_marker(sprint_id, "slate")
            marker.write_text(
                json.dumps(
                    _marker_state(sprint_id, "slate")
                    | {"disposition": "slate-verdict", "refusal": error}
                )
            )
            return fail(error)
        return refused(error)
    if not findings.strip():
        return refused(f"refused: the slate reviewer wrote no findings at {out.resolve()}")
    review_marker(sprint_id, "slate").unlink(missing_ok=True)
    print(findings.strip())
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
                "refused: two slate-review rounds already exist and the sprint is open — any dead"
                " attempt owes nothing; continue with the cards"
            )
        return fail(
            "refused: two slate-review rounds already exist — judge and apply their findings,"
            " then open the sprint"
        )
    out = review_findings_path(sprint_id, "slate")
    if dry_run:
        return _run_review(sprint_id, out, True)
    return run_detached(sprint_id, "slate", out, [str(Path(__file__).resolve()), sprint_id])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier", metavar="sprint-id-or-story-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--_review", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if args._review:
        return _run_review(args.identifier, Path(args._review), False)
    return cmd_review(args.identifier, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
