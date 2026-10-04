"""Sprint land coverage and release handoff."""

import json
import subprocess
import tempfile

import bookkeep
import overlap
import preflight as pf
import tier_legs
from env import data_root
from milestone import sprint_stories
from release import (
    VERSIONING_OFF_TEXT,
    next_version,
    refuse_unbumpable,
    version_refusal,
    versioning_mode,
)
from release import cmd_post_merge as release_post_merge
from review import CLEARABLE_BY_FULL
from review_report import normalize_report
from sprint_close import (
    config_flat,
    default_branch,
    fail,
    git,
    read_sprint_state,
)
from sprint_coverage import _covered_gate_files
from sprint_coverage import coverage_refusal as _coverage_refusal
from sprint_state import append_tier_evidence, read_tier_history, write_sprint_state
from work import plan_path

# GitHub's own ceiling on a pull request body; gh rejects a longer --body-file.
PR_BODY_LIMIT = 65_536


def _release_body(sprint_id: str, state: dict, marker) -> tuple[str, str]:
    rerun = f"run `xp.py sprint {sprint_id} review`"
    again = f"then run `xp.py sprint {sprint_id} land` again"
    plan = plan_path()
    try:
        headings = sprint_stories(plan.read_text(), sprint_id)
    except FileNotFoundError:
        return "", f"refused: missing sprint plan {plan} — restore it, {again}"
    except (OSError, UnicodeError) as exc:
        return "", f"refused: unreadable sprint plan {plan}: {exc} — repair it, {again}"
    if not headings:
        return "", (
            f"refused: no `### Sprint {sprint_id}` section in {plan} — a sprint whose"
            f" heading no longer exists is not a sprint that closed no story, and the"
            f" release PR would name neither. Restore the heading and its cards, {again}"
        )
    targets = {heading.split()[1]: heading for heading in headings}
    close_log = data_root() / "closes.jsonl"
    try:
        lines = close_log.read_text().splitlines()
    except FileNotFoundError:
        return "", (
            f"refused: no close log at {close_log} — no story has closed through"
            f" `xp.py story <id> land` here, so the PR could name no merge SHA."
            f" Restore it, or create it empty if that is genuinely this sprint, {again}"
        )
    except (OSError, UnicodeError) as exc:
        return "", f"refused: unreadable close log {close_log}: {exc} — repair it, {again}"
    closes = {}
    for line_n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return "", (
                f"refused: unreadable close log {close_log} line {line_n}: {exc}"
                f" — repair that line, {again}"
            )
        if not isinstance(record, dict):
            return "", (
                f"refused: unreadable close log {close_log} line {line_n}: not an object"
                f" — repair that line, {again}"
            )
        story = record.get("story")
        if story in targets:
            if not all(isinstance(record.get(key), str) for key in ("story", "title", "merge_sha")):
                return "", (
                    f"refused: unreadable close log {close_log} line {line_n}: story record"
                    f" — repair that line, {again}"
                )
            closes[story] = record

    rounds = state.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return "", f"refused: missing review rounds in sprint marker {marker} — {rerun}"
    for number, round_ in enumerate(rounds, 1):
        _report, error = normalize_report(round_)
        if error:
            return "", (
                f"refused: unreadable review round {number} in sprint marker {marker}:"
                f" {error} — {rerun}"
            )
    rendered_rounds = [bookkeep._render_rounds(rounds, f"sprint/{sprint_id}")]
    latest = rounds[-1]
    reviewed = latest.get("reviewed_head", state.get("reviewed_head"))
    shown = latest.get("shown_sha", state.get("shown_sha"))
    if not isinstance(reviewed, str) or not reviewed:
        return "", f"refused: missing reviewed_head in sprint marker {marker} — {rerun}"
    if not isinstance(shown, str) or not shown:
        return "", f"refused: missing shown_sha in sprint marker {marker} — {rerun}"
    clearable = latest.get(CLEARABLE_BY_FULL, [])
    if not isinstance(clearable, list) or not all(isinstance(item, str) for item in clearable):
        return "", (f"refused: unreadable {CLEARABLE_BY_FULL} in sprint marker {marker} — {rerun}")
    receipt = state.get("full_tier")
    fields = ("tier", "command", "tree", "head", "verdict", "ran_by")
    if (
        not isinstance(receipt, dict)
        or not all(isinstance(receipt.get(key), str) and receipt[key] for key in fields)
        or not isinstance(receipt.get("reused"), bool)
    ):
        return "", (
            f"refused: unreadable full_tier receipt in sprint marker {marker} — delete"
            f" the key, {again} to measure the shipping tree afresh"
        )

    stories = []
    for story, heading in targets.items():
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
        + f"\n- Latest round reviewed head: {reviewed}"
        + f"\n- Latest round shown tree: {shown}{obligations}"
        + "\n\n## Full tier\n"
        + f"- Tier: {receipt['tier']}\n- Verdict: {receipt['verdict']}\n"
        + f"- Command: {receipt['command']}\n- Measured tree: {receipt['tree']}\n- Run: {run}\n"
    )
    if "components" in receipt:
        body += "".join(
            f"- Leg {c['leg']}: {c['status']} {c['command']} at {c['head']}\n"
            for c in receipt["components"]
        )
    if len(body) > PR_BODY_LIMIT:
        return "", (
            f"refused: release PR body is {len(body)} characters; limit is {PR_BODY_LIMIT}"
            f" — findings prose is counted, never quoted, so shorten the"
            f" {CLEARABLE_BY_FULL} entries recorded in {marker}, {again}"
        )
    return body, ""


def _clearance_failure(red: str, bound: list[str]) -> str:
    return red + "\nThe full gate did not clear these bound blockers:\n  " + "\n  ".join(bound)


def _clearance_notice(verb: str, bound: list[str]) -> str:
    return f"the full gate {verb} these closer-bound blockers:\n  " + "\n  ".join(bound)


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import shutil

    import review

    reported: set[str] = set()
    if refusal := _coverage_refusal(
        sprint_id, git("rev-parse", "HEAD").stdout.strip(), reported=reported
    ):
        return fail(refusal)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    versioned, refusal = versioning_mode()
    if refusal:
        return fail(refusal)
    version = next_version() if versioned else ""
    if versioned and not version:
        return refuse_unbumpable()
    if versioned and (refusal := version_refusal(version)):
        return fail(refusal)
    title = f"release {version}" if versioned else f"release {branch}"
    ref = overlap.merge_source(default_branch(), "pr", fetch=not dry_run)
    pending = overlap.unmerged(ref)
    marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    legs, full, legs_error = tier_legs.inspect(ref, pending)
    if legs_error:
        return fail(legs_error)
    bound = state["rounds"][-1].get(CLEARABLE_BY_FULL) or []
    if dry_run:
        preflight_raw, _commands, error = pf.prepare(config_flat("preflight"))
        if error:
            return fail(error)
        if refusal := overlap.tier_refusal(full, "full"):
            return fail(_clearance_failure(refusal, bound) if bound else refusal)
        if preflight_raw:
            print(pf.preview(preflight_raw))
        print(f"would run: {full}, unless a passed receipt matches the shipping tree and command")
        if legs is not None:
            for name, command in legs:
                print(f"would run leg {name}: {command}, unless passed on this tree")
        if bound:
            print("if green, " + _clearance_notice("clears", bound))
        preview = [
            ["git", "push", "-u", "origin", branch],
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body-file",
                "<release-pr-body>",
            ],
        ]
        for c in preview:
            print(" ".join(c))
        handoff = f"tag {version}, retire the key" if versioned else "retire the key"
        print(f"(then: xp.py sprint {sprint_id} post-merge — {handoff})")
        if not versioned:
            print(VERSIONING_OFF_TEXT)
        if pending:
            print(f"...on a trial merge with {ref} — staged, then aborted either way")
        return 0

    if dirty := git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: the working tree is dirty — the tier must judge the tree"
            " that ships, and these files are not in it:\n  " + dirty
        )
    if error := pf.check(config_flat("preflight")):
        return fail(error)
    prior = state.get("full_tier", overlap.MISSING_RECEIPT)
    declared_names = tuple(name for name, _ in legs) if legs is not None else ()
    history, history_error = read_tier_history(state)
    if history_error:
        return fail(
            f"refused: {history_error} in sprint marker {marker} — repair or delete"
            " full_tier_history, then run land again"
        )

    def record_attempt(event: dict, receipt: dict | None) -> str:
        try:
            append_tier_evidence(marker, event, receipt, declared_names)
        except (OSError, ValueError) as exc:
            return f"refused: could not persist the full tier evidence at {marker}: {exc}"
        return ""

    red, receipt = overlap.gates(
        ref, [], "full", pending, prior, None, record_attempt, history, legs
    )
    if red:
        return fail(_clearance_failure(red, bound) if bound else red)
    # Validation may outlast a concurrent review; gate its latest state.
    marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    head = git("rev-parse", "HEAD").stdout.strip()
    if refusal := _coverage_refusal(sprint_id, head, state, reported):
        return fail(refusal)
    bound = state["rounds"][-1].get(CLEARABLE_BY_FULL) or []
    action = "reused" if receipt["reused"] else "ran"
    print(
        f"full tier receipt {marker}: {action} {receipt['command']} on tree"
        f" {receipt['tree']}, passed at HEAD {receipt['head']}"
    )
    if legs is not None:
        for component in receipt["components"]:
            print(
                f"full tier leg {component['leg']}: {component['status']} "
                f"{component['command']} at {component['head']}"
            )
    if bound:
        print(_clearance_notice("cleared", bound))
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
    body, body_error = _release_body(sprint_id, state, marker)
    if body_error:
        return fail(body_error)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as body_file:
        body_file.write(body)
        body_file.flush()
        prepared = {
            "branch": branch,
            "head": head,
            "tree": git("rev-parse", "HEAD^{tree}").stdout.strip(),
        }
        cmds = [
            ["git", "push", "-u", "origin", branch],
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body-file",
                body_file.name,
            ],
        ]
        for c in cmds:
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                return bookkeep.refuse_command(c, r)
        try:
            write_sprint_state(marker, {"prepared_pr": prepared | {"url": r.stdout.strip()}})
        except (OSError, ValueError) as exc:
            return fail(
                f"release PR prepared at {r.stdout.strip()}, but its locator could not be saved: "
                f"{exc} — preserve that URL and repair the marker before post-merge"
            )
    print(f"release PR open. After it MERGES: xp.py sprint {sprint_id} post-merge")
    if not versioned:
        print(VERSIONING_OFF_TEXT)
    return 0


def cmd_post_merge(sprint_id: str, dry_run: bool = False) -> int:
    return release_post_merge(sprint_id, dry_run=dry_run)
