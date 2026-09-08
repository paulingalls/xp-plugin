"""Sprint land coverage and release handoff."""

import json
import subprocess
import tempfile

import overlap
from env import data_root
from milestone import sprint_stories
from release import cmd_post_merge as release_post_merge
from release import next_version, refuse_unbumpable
from review import CLEARABLE_BY_FULL, covered_ranges, reviewer_strays, validate_clearable
from sprint_close import (
    _shown_diff,
    default_branch,
    fail,
    git,
    read_sprint_state,
    write_sprint_state,
)
from work import config_block_value, plan_path

PR_BODY_LIMIT = 65_536


def _release_body(sprint_id: str, state: dict, marker) -> tuple[str, str]:
    plan = plan_path()
    try:
        headings = sprint_stories(plan.read_text(), sprint_id)
    except FileNotFoundError:
        return "", f"refused: missing sprint plan {plan}"
    except (OSError, UnicodeError) as exc:
        return "", f"refused: unreadable sprint plan {plan}: {exc}"
    targets = [heading.split()[1] for heading in headings]
    close_log = data_root() / "closes.jsonl"
    try:
        lines = close_log.read_text().splitlines()
    except FileNotFoundError:
        return "", f"refused: missing close log {close_log}"
    except (OSError, UnicodeError) as exc:
        return "", f"refused: unreadable close log {close_log}: {exc}"
    closes = {}
    for line_n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return "", f"refused: unreadable close log {close_log} line {line_n}: {exc}"
        if not isinstance(record, dict):
            return "", f"refused: unreadable close log {close_log} line {line_n}: not an object"
        story = record.get("story")
        if story in targets:
            if not all(isinstance(record.get(key), str) for key in ("story", "title", "merge_sha")):
                return "", f"refused: unreadable close log {close_log} line {line_n}: story record"
            closes[story] = record

    rounds = state.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return "", f"refused: missing review rounds in sprint marker {marker}"
    rendered_rounds = []
    for number, round_ in enumerate(rounds, 1):
        if not isinstance(round_, dict) or not all(
            isinstance(round_.get(key), list) for key in ("fixed", "blocking", "noted")
        ):
            return "", f"refused: unreadable review round {number} in sprint marker {marker}"
        rendered_rounds.append(
            f"- Round {number}: {len(round_['fixed'])} fixed · "
            f"{len(round_['blocking'])} blocking · {len(round_['noted'])} noted"
        )
    latest = rounds[-1]
    reviewed = latest.get("reviewed_head", state.get("reviewed_head"))
    shown = latest.get("shown_sha", state.get("shown_sha"))
    if not isinstance(reviewed, str) or not reviewed:
        return "", f"refused: missing reviewed_head in sprint marker {marker}"
    if not isinstance(shown, str) or not shown:
        return "", f"refused: missing shown_sha in sprint marker {marker}"
    clearable = latest.get(CLEARABLE_BY_FULL, [])
    if not isinstance(clearable, list) or not all(isinstance(item, str) for item in clearable):
        return "", f"refused: unreadable {CLEARABLE_BY_FULL} in sprint marker {marker}"
    receipt = state.get("full_tier")
    fields = ("tier", "command", "tree", "head", "verdict", "ran_by")
    if (
        not isinstance(receipt, dict)
        or not all(isinstance(receipt.get(key), str) and receipt[key] for key in fields)
        or not isinstance(receipt.get("reused"), bool)
    ):
        return "", f"refused: unreadable full_tier receipt in sprint marker {marker}"

    stories = []
    for heading, story in zip(headings, targets, strict=True):
        if record := closes.get(story):
            stories.append(f"- {story} — {record['title']} — {record['merge_sha']}")
        else:
            stories.append(f"- {heading.removeprefix('#### ')} — no close record")
    obligations = ""
    if clearable:
        obligations = "\n- clearable_by_full:\n" + "".join(f"  - {item}\n" for item in clearable)
        obligations = obligations.rstrip()
    run = (
        f"reused from {receipt['ran_by']} at {receipt['head']}"
        if receipt["reused"]
        else f"ran by {receipt['ran_by']} at {receipt['head']}"
    )
    body = (
        f"# Sprint {sprint_id} release\n\n## Stories\n"
        + "\n".join(stories)
        + "\n\n## Sprint review\n"
        + "\n".join(rendered_rounds)
        + f"\n- Reviewed head: {reviewed}\n- Shown tree: {shown}{obligations}"
        + "\n\n## Full tier\n"
        + f"- Tier: {receipt['tier']}\n- Verdict: {receipt['verdict']}\n"
        + f"- Command: {receipt['command']}\n- Measured tree: {receipt['tree']}\n- Run: {run}\n"
    )
    if len(body) > PR_BODY_LIMIT:
        return "", f"refused: release PR body is {len(body)} characters; limit is {PR_BODY_LIMIT}"
    return body, ""


def _is_retro_prose(path: str) -> bool:
    return path.startswith(".xp/") and path not in overlap.GATE_FILES


def _blocking_refusal(blocking: list) -> str:
    return (
        "refused: the last round left blocking findings:\n  "
        + "\n  ".join(blocking)
        + "\nFix them, then review again — a flag cannot clear these"
    )


def _clearance_failure(red: str, bound: list[str]) -> str:
    return red + "\nThe full gate did not clear these bound blockers:\n  " + "\n  ".join(bound)


def _clearance_notice(verb: str, bound: list[str]) -> str:
    return f"the full gate {verb} these closer-bound blockers:\n  " + "\n  ".join(bound)


def _covered_gate_files(state: dict, head: str) -> list[str]:
    """Gate files the REVIEWER moved inside a round's own range — what land runs,
    changed by the agent whose round says land may run it."""
    hits = {}
    for start, end in covered_ranges(state, head):
        changed = git("diff", "--name-status", "--find-renames", f"{start}..{end}")
        for line in changed.stdout.splitlines():
            for path in line.split("\t")[1:]:
                if path in overlap.GATE_FILES:
                    hits[path] = None
    return list(hits)


def _coverage_refusal(sprint_id: str, head: str) -> str:
    _marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return marker_error
    rerun = f"run `close.py sprint {sprint_id} review`"
    if not (rounds := state.get("rounds") or []):
        return f"refused: no recorded review for sprint {sprint_id} — {rerun}"
    if incomplete := rounds[-1].get("incomplete"):
        detail = incomplete.replace("\n", "\n  ")
        return (
            f"refused: the last review round is incomplete:\n  {detail}\n"
            f"Its findings are recorded and stand; clear what it names, then {rerun}"
        )
    round_ = rounds[-1]
    blocking = round_["blocking"]
    bound, unbound = [], blocking
    if CLEARABLE_BY_FULL in round_:
        bound, unbound, error = validate_clearable(round_, stage="closer")
        if error:
            return f"refused: corrupt sprint review marker: {error}. {rerun}"
    if bound:
        if unbound:
            return _blocking_refusal(blocking)
        # No reviewer-stray or .xp/-only exemption here: those forgive motion the
        # lead still reads before merging, and clearance is the one path where no
        # judgment follows the gate.
        shown = str(state.get("shown_sha"))
        if shown != head:
            moved, missing = _shown_diff(sprint_id, shown, head)
            if missing:
                return missing
            return (
                f"refused: the review did not cover HEAD — {', '.join(moved.stdout.splitlines())}"
                f" changed since {shown[:8]}. {rerun}"
            )
        if gates := _covered_gate_files(state, head):
            return (
                "refused: deterministic clearance cannot use a reviewer-changed gate file"
                f" from the covered range: {', '.join(gates)}. {rerun}"
            )
        ref = overlap.merge_source(default_branch(), "pr")
        if overlap.unmerged(ref):
            return (
                f"refused: deterministic clearance cannot include pending {ref}. Merge it"
                f" here and {rerun} so the combined tree is reviewed"
            )
        return ""
    if blocking:
        return _blocking_refusal(blocking)
    if (shown := str(state.get("shown_sha"))) == head:
        return ""
    moved, missing = _shown_diff(sprint_id, shown, head)
    if missing:
        return missing
    # BEFORE the authorship branch: an empty range reads there as "no strays"
    if git("merge-base", "--is-ancestor", shown, head, check=False).returncode:
        return (
            f"refused: HEAD does not contain {shown[:8]}, the tree the round covered"
            f" — the recorded round describes no tree that exists. {rerun}"
        )
    strays = reviewer_strays(shown, head)
    if not strays and not any(f in overlap.GATE_FILES for f in moved.stdout.splitlines()):
        print(f"the delta since {shown[:8]} is the reviewer's own fixes")
        return ""
    if code := [f for f in moved.stdout.splitlines() if not _is_retro_prose(f)]:
        return (
            f"refused: the review did not cover HEAD — {', '.join(code)}"
            f" changed since {shown[:8]}. {rerun}"
        )
    if exempt := moved.stdout.splitlines():
        print(f"reviewed earlier; the delta since is .xp/ only: {', '.join(sorted(set(exempt)))}")
    return ""


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import shutil

    import review

    if refusal := _coverage_refusal(sprint_id, git("rev-parse", "HEAD").stdout.strip()):
        return fail(refusal)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not (version := next_version()):
        return refuse_unbumpable()
    ref = overlap.merge_source(default_branch(), "pr")
    pending = overlap.unmerged(ref)
    marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    bound = state["rounds"][-1].get(CLEARABLE_BY_FULL) or []
    if dry_run:
        full = config_block_value("tests", "full")
        if refusal := overlap.tier_refusal(full, "full"):
            return fail(_clearance_failure(refusal, bound) if bound else refusal)
        print(f"would run: {full}, unless a passed receipt matches the shipping tree and command")
        if bound:
            print("if green, " + _clearance_notice("clears", bound))
        preview = [
            ["git", "push", "-u", "origin", branch],
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"release {version}",
                "--body-file",
                "<release-pr-body>",
            ],
        ]
        for c in preview:
            print(" ".join(c))
        print(f"(then: close.py sprint {sprint_id} post-merge — tag {version}, retire the key)")
        if pending:
            print(f"...on a trial merge with {ref} — staged, then aborted either way")
        return 0

    if dirty := git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: the working tree is dirty — the tier must judge the tree"
            " that ships, and these files are not in it:\n  " + dirty
        )
    prior = state.get("full_tier", overlap.MISSING_RECEIPT)
    red, receipt = overlap.gates(ref, [], "full", pending, prior)
    if red:
        return fail(_clearance_failure(red, bound) if bound else red)
    state["full_tier"] = receipt
    try:
        write_sprint_state(marker, state)
    except OSError as exc:
        return fail(f"refused: could not persist the full tier receipt at {marker}: {exc}")
    action = "reused" if receipt["reused"] else "ran"
    print(
        f"full tier receipt {marker}: {action} {receipt['command']} on tree"
        f" {receipt['tree']}, passed at HEAD {receipt['head']}"
    )
    if bound:
        print(_clearance_notice("cleared", bound))
    head = git("rev-parse", "HEAD").stdout.strip()
    review.disclose(
        state,
        head,
        lambda n: review.diff_path(review.sprint_report_path(sprint_id, "fix", n)),
    )
    if gates := _covered_gate_files(state, head):
        print(f"among them a gate file, which no later check re-reads: {', '.join(gates)}")
    if not shutil.which("gh"):
        return fail(
            "refused: pr mode needs the gh CLI on PATH — install it, or open the PR by hand"
        )
    marker, persisted, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    body, body_error = _release_body(sprint_id, persisted, marker)
    if body_error:
        return fail(body_error)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as body_file:
        body_file.write(body)
        body_file.flush()
        cmds = [
            ["git", "push", "-u", "origin", branch],
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"release {version}",
                "--body-file",
                body_file.name,
            ],
        ]
        for c in cmds:
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                return fail(f"{c[0]} failed: {r.stderr.strip()}")
    print(f"release PR open. After it MERGES: close.py sprint {sprint_id} post-merge")
    return 0


def cmd_post_merge(sprint_id: str) -> int:
    return release_post_merge(sprint_id)
