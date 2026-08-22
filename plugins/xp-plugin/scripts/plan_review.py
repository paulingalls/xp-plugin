#!/usr/bin/env python3
"""Plan review as a headless role — the last subagent call, made a spawn.

A codex teammate has no `--plugin-dir` and no subagents, so TEAMMATE.md's "spawn
the plan-reviewer" named an agent file that is not in its tree: the review this
repo added after three measured slips was skipped, or invented. This runs the
same charter on either harness, through the runner every other leg already uses.

Usage: plan_review.py <story-id> <plan-file> [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

import review
from close import fail, story_card
from spawn import _read, _read_shipped, tree_state
from work import chdir_repo_root, data_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent


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


def card_for(story_id: str) -> str:
    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError):
        return ""


def build_bundle(charter: str, plan: str, card: str, out: Path) -> str:
    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out}"),
        ("The plan under review", plan),
        ("Story card", card or "none in the plan — judge the plan on its own"),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def review_state(
    plan_file: Path,
) -> tuple[tuple[str, str], bytes | None, bytes | None]:
    """State a report-only plan reviewer must leave unchanged."""

    def contents(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except OSError:
            return None

    live_plan = plan_path()
    return tree_state(Path.cwd()), contents(plan_file), contents(live_plan)


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
    out = findings_path(story_id)
    if not dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle(charter, plan, card, out)
    try:
        before = review_state(plan_file)
    except OSError as e:
        return fail(f"refused: cannot snapshot the repository before review: {e}")
    _result, err = review.run(bundle, Path.cwd(), dry_run, name="plan-reviewer", card=card)
    if dry_run:
        return 0
    try:
        changed = review_state(plan_file) != before
    except OSError as e:
        return fail(f"refused: the plan reviewer left the repository unreadable: {e}")
    if changed:
        return fail(
            "refused: the plan reviewer changed the repository, draft, or story plan"
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
    print(findings)
    print(f"findings: {out}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("story_id")
    p.add_argument("plan_file", help="the draft plan to review")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    # resolved BEFORE the chdir, or a relative path names a different file after it
    plan_file = Path(a.plan_file).resolve()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return cmd_review(a.story_id, plan_file, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
