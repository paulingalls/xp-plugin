#!/usr/bin/env python3
"""Sprint opening and close: branch state, checks, review, release."""

import glob
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
import close as story_close
import lifecycle as lc
import milestone
import overlap
from close import config_flat, default_branch, fail, git, story_card
from env import record_sprint_branch, refuse_direct_invocation, sprint_branch, sprint_branch_name
from falsifier_batch import (
    batch_refusal,
    corpus,
    execute_batch,
    ledger,
    resolved_offers,
    tier_covers,
    triage_notes,
    unavailable_coverage,
    validated_coverage,
)
from review_artifacts import (
    restore_sprint_queue,
    sprint_paths,
)
from sprint_state import read_sprint_state, sprint_marker, write_sprint_state
from work import (
    config_block_value,
    data_root,
    entries,
    missing_plan_refusal,
    plan_path,
    record_summary,
)

PLUGIN_ROOT = Path(__file__).parent.parent
sprint_stories = milestone.sprint_stories


def sprint_cards(plan: str, sprint_id: str) -> str:
    return "\n".join(story_card(plan, ln.split()[1])[0] for ln in sprint_stories(plan, sprint_id))


def cmd_salvage(sprint_id: str, dry_run: bool = False) -> int:
    """Record reports left by a host-killed sprint review as incomplete."""
    import review

    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    round_n = len(state.get("rounds", [])) + 1
    root = data_root() / "reports" / "sprint"
    shown = f"{sprint_id}.*.round-{round_n}.json"
    paths = sorted(root.glob(f"{glob.escape(sprint_id)}.*.round-{round_n}.json"))
    if not paths:
        if dry_run:
            print(f"dry run: no round-{round_n} reports for {sprint_id} — nothing was restored")
            return 0
        try:
            restore_sprint_queue(sprint_id, round_n)
        except FileExistsError as exc:
            return fail(
                f"refused: cannot restore queued sprint artifacts over {exc} — move that"
                " file out of the way, then run salvage again"
            )
        paths = sorted(root.glob(f"{glob.escape(sprint_id)}.*.round-{round_n}.json"))
    recovered, unreadable, prefix, suffix = [], [], f"{sprint_id}.", f".round-{round_n}.json"
    for path in paths:
        report, err = review.read_report(path)
        if err:
            unreadable.append(f"{path}: {err}")
        else:
            recovered.append((path.name[len(prefix) : -len(suffix)], report))
    if not recovered:
        if unreadable:  # distinct states stay distinct: missing is not unreadable
            queued = ", ".join(str(path) for path in sprint_paths(sprint_id, round_n + 1))
            return fail(
                f"refused: every sprint report at {root / shown} is UNREADABLE, not"
                f" absent: {'; '.join(unreadable)}. Repair or delete them, then review"
                + (f"; queued artifacts remain at {queued}" if queued else "")
            )
        return fail(
            f"refused: no unrecorded sprint reports for round {round_n}; looked for"
            f" {root / shown}. Run review"
        )
    if dirty := story_close.salvage_dirty_refusal():
        return fail(f"refused: {dirty}")
    seen = {
        key: dict.fromkeys(item for _stage, report in recovered for item in report[key])
        for key in review.REPORT_KEYS
    }
    why = f"the sprint review process ended before round {round_n} could be recorded"
    if unreadable:
        why += "; unreadable artifacts: " + "; ".join(unreadable)
    round_ = {key: list(items) for key, items in seen.items()}
    round_.update(incomplete=why, stages=[stage for stage, _report in recovered])
    if dry_run:
        print(f"dry run: would record round {round_n} incomplete: {why}")
        return 0
    review.write_round(marker, state, round_, edit=write_sprint_state)
    print(f"round {round_n} recorded incomplete after {', '.join(round_['stages'])}")
    return fail(f"refused: {why}") if unreadable else 0


def cmd_start(sprint_id: str, dry_run: bool = False) -> int:
    plan = plan_path()
    if not plan.exists():
        return fail(f"refused: {missing_plan_refusal()}")
    members = sprint_stories(plan.read_text(), sprint_id)
    if not members:
        return fail(f"refused: no `### Sprint {sprint_id}` section in {plan}")
    branch = git("branch", "--show-current").stdout.strip()
    if not branch or branch == default_branch():
        return fail("refused: open the sprint from its freshly cut branch, not trunk")
    if branch != (expected := sprint_branch_name(sprint_id)):
        return fail(f"refused: open sprint {sprint_id} from {expected}, not {branch}")
    if dry_run:
        does = "re-runs the close checks for" if sprint_branch() else "opens"
        print(f"dry run: {branch} {does} sprint {sprint_id}; nothing ran, nothing recorded")
        return 0
    if not sprint_branch() and (red := lc.run(config_flat(lc.KEY), "sprint-open", sprint_id)):
        return fail(red)
    opening = record_sprint_branch(branch)
    if (owner := milestone.find(plan.read_text(), sprint_id)) and owner.status == "planned":
        milestone.move(sprint_id)
    print(f"sprint branch: {branch}")
    if unfinished := [m for m in members if not m.endswith(("[done]", "[retired]"))]:
        if not opening:
            return fail(f"refused: sprint {sprint_id} is unfinished:\n  " + "\n  ".join(unfinished))
        print(f"recorded; {len(unfinished)} stories unfinished — close checks wait")
        return 0

    marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    if dirty := git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: the working tree is dirty before the close batch — commit or"
            f" remove these files first:\n  {dirty}"
        )
    if "full_tier" in state:
        state.pop("full_tier")
        write_sprint_state(marker, {}, remove=("full_tier",))

    root = data_root()
    source = entries(root)
    records = ledger(root, source)
    batch = corpus(root, records)
    grouped = {}
    for eid, head, falsifier, covered in batch:
        grouped.setdefault(falsifier, []).append((eid, head, covered))
    tiers = config_block_value("tests")
    graph, coverage_error = validated_coverage(tiers)
    if coverage_error:
        return fail(f"refused: {coverage_error}")
    for notice in unavailable_coverage(records, tiers):
        print(notice)
    tier = tiers.get("full", "")
    # EDIT-ME ONLY — an absent full tier is a tested position (test_falsifier_batch runs
    # the batch without one); EDIT-ME reached `sh -c`, returned 127, and refused as red.
    if tier == "EDIT-ME":
        return fail(overlap.tier_refusal(tier, "full"))
    deferred = {
        command: records
        for command, records in grouped.items()
        if tier
        and all(tier_covers(covered, "full", tiers, graph) for _eid, _head, covered in records)
    }
    standalone = {key: value for key, value in grouped.items() if key not in deferred}
    results = execute_batch(standalone)
    if red := batch_refusal(root, standalone, results):
        return fail(red)

    if tier:
        if dirty := git("status", "--porcelain").stdout.strip():
            return fail(
                "refused: the falsifier batch left the working tree dirty before the"
                f" full tier:\n  {dirty}"
            )
        tree = git("write-tree", check=False)
        if tree.returncode:
            return fail(
                f"refused: Git could not write tree for the full tier: {tree.stderr.strip()}"
            )
        before = {
            "command": tier,
            "head": git("rev-parse", "HEAD").stdout.strip(),
            "tree": tree.stdout.strip(),
        }
        print(f"running the full tier: {tier}")
        if subprocess.run(tier, shell=True).returncode == 0:
            for sources in deferred.values():
                for eid, head, covered in sources:
                    print(f"trusted {eid} ({head}) via tier {covered}")
            written = git("write-tree", check=False)
            after = {
                "command": config_block_value("tests", "full"),
                "head": git("rev-parse", "HEAD").stdout.strip(),
                "tree": written.stdout.strip(),
            }
            dirty = git("status", "--porcelain").stdout.strip()
            if before == after and not dirty:
                state["full_tier"] = {
                    "tier": "full",
                    **before,
                    "verdict": "passed",
                    "ran_by": "start",
                    "reused": False,
                }
                write_sprint_state(marker, {"full_tier": state["full_tier"]})
            else:
                motion = (
                    f"Git could not name the tree again: {written.stderr.strip()}"
                    if written.returncode
                    else dirty or f"HEAD/tree/command moved from {before} to {after}"
                )
                print(f"full tier passed, but no reusable receipt was recorded: {motion}")
        else:
            deferred_results = execute_batch(deferred)
            if red := batch_refusal(root, deferred, deferred_results):
                return fail(red)
            return fail(f"refused: full tier red: {tier}")

    if completion := milestone.candidate(plan.read_text(), sprint_id):
        print(f"\n{completion.heading.rstrip()}")
        print(f"close.py sprint {sprint_id} milestone-done")

    notes = triage_notes(source)
    print("\n" + resolved_offers(records, results))
    print(f"\n{len(members)} stories, {len(notes)} notes to triage. Each note: promote to")
    print("constraints.md/system.md via the retro diff, or archive it.\n")
    for text in notes:
        heading, body = record_summary(text)
        print(f"  {heading[3:]} — {body[:100]}")
    print("\n" + (PLUGIN_ROOT / "templates" / "retro.md").read_text())
    print(
        "Then write the sprint digest yourself — this leg emits facts, never a"
        " narrative; judgment belongs only where an LLM is present. First line:"
        " # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0


def _shown_diff(sprint_id: str, shown: str, head: str) -> tuple[subprocess.CompletedProcess, str]:
    moved = git("diff", "--name-only", shown, head, check=False)
    if moved.returncode:
        action = (
            f"move {sprint_marker(sprint_id)} aside — it holds this sprint's recorded"
            f" rounds and moving it forfeits them — then run `close.py sprint"
            f" {sprint_id} review`"
        )
        return moved, f"refused: the review recorded {shown[:8]}, which no longer exists — {action}"
    return moved, ""


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import sprint_land

    return sprint_land.cmd_land(sprint_id, dry_run)


def cmd_post_merge(sprint_id: str, dry_run: bool = False) -> int:
    import sprint_land

    return sprint_land.cmd_post_merge(sprint_id, dry_run)


if __name__ == "__main__":
    refuse_direct_invocation("close.py sprint <id> <action>")
