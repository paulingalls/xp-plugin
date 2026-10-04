"""Validate the merged shipping tree and publish under sprint authority."""

import json

import lifecycle
import overlap
import sprint_state
import tier_legs
from close import config_flat, default_branch, git
from env import sprint_branch, sprint_branch_name
from review_report import normalize_report, validate_clearable


def inputs():
    legs, error = tier_legs.declared()
    if error:
        raise ValueError(error)
    return {
        "head": git("rev-parse", "HEAD").stdout.strip(),
        "tree": git("rev-parse", "HEAD^{tree}").stdout.strip(),
        "branch": git("branch", "--show-current").stdout.strip(),
        "full": tier_legs.full_command(legs),
        "legs": legs,
        "owner": sprint_branch(),
        "config": config_flat(lifecycle.KEY),
    }


def review_refusal(state):
    if state.get("running_producer"):
        return "uncertain integration producer — inspect and salvage its reports before release"
    rounds = state.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return "no integration review evidence — restore the marker and review the release"
    for raw in rounds:
        if error := normalize_report(raw)[1]:
            return f"unreadable integration review: {error} — repair the marker"
    if rounds[-1].get("incomplete"):
        return "incomplete integration review — the lead must inspect the preserved handoff"
    bound, remaining, error = validate_clearable(rounds[-1], "closer")
    if error:
        return error
    if rounds[-1]["blocking"] and (not bound or remaining):
        return "integration blockers remain — return them to the lead"
    if overlap.unresolved_blocking(state) != rounds[-1]["blocking"]:
        return "unresolved salvaged integration blockers — return them to the lead"
    return ""


def coverage_refusal(release_id, state):
    from release import recorded_release_head
    from sprint_coverage import coverage_refusal as coverage

    shown, error = recorded_release_head(state)
    if error or not shown:
        return error or "missing reviewed release head — restore integration evidence"
    tip = git(
        "rev-parse", "--verify", "-q", f"{sprint_branch()}^{{commit}}", check=False
    ).stdout.strip()
    parents = git("log", "--first-parent", "--merges", "--format=%P", "HEAD").stdout
    for line in parents.splitlines():
        trunk, *merged = line.split()
        if not git("merge-base", "--is-ancestor", tip or shown, trunk, check=False).returncode:
            continue
        for parent in merged:
            if not git("merge-base", "--is-ancestor", tip or shown, parent, check=False).returncode:
                return coverage(release_id, tip or parent, state, released_ref=trunk)
    if not tip:
        return (
            "missing sprint ref and no identifiable merge tip — restore the actual "
            "merged sprint ref, then retry post-merge"
        )
    return coverage(release_id, tip, state, released_ref=state.get("review_base", shown))


def validation_refusal(state, receipt, before):
    history, error = sprint_state.read_tier_history(state)
    if error or history is None:
        return error or "missing validation history — remeasure the shipping tree"
    if before["legs"] is None:
        return sprint_state.reuse_veto(history, before["tree"], before["full"], receipt["head"])
    for name, command in before["legs"]:
        latest = tier_legs.latest(history, name, command, before["tree"])
        if latest is None or latest["outcome"] == "failed":
            return f"full tier leg {name} has no current pass — remeasure the shipping tree"
    return ""


def finish(release_id, publish):
    marker, state, error = sprint_state.read_sprint_state(release_id)
    if error or (error := review_refusal(state)) or (error := coverage_refusal(release_id, state)):
        return error
    if git("status", "--porcelain").stdout.strip():
        return "dirty merged shipping tree — commit or restore it before post-merge"
    try:
        before = inputs()
    except (ValueError, OSError) as exc:
        return str(exc)
    names = tuple(name for name, _ in before["legs"] or [])
    history, error = sprint_state.read_tier_history(state)
    if error:
        return f"{error} — repair the marker before post-merge"

    def record(event, receipt):
        try:
            sprint_state.append_tier_evidence(marker, event, receipt, names)
        except (OSError, ValueError) as exc:
            return f"could not persist merged-tree validation: {exc}"
        return ""

    error, receipt = overlap.gates(
        "HEAD",
        [],
        "full",
        False,
        state.get("full_tier", overlap.MISSING_RECEIPT),
        record_attempt=record,
        history=history,
        legs=before["legs"],
    )
    if error:
        return error
    marker, accepted, error = sprint_state.read_sprint_state(release_id)
    if error or (error := review_refusal(accepted)):
        return error
    if accepted.get("rounds") != state.get("rounds"):
        return "integration authority changed during validation — inspect it before retrying"
    if error := validation_refusal(accepted, receipt, before):
        return error
    if error := lifecycle.run(before["config"], "sprint-close", release_id):
        return error
    authority = json.dumps(accepted, sort_keys=True)

    def under_lock(current):
        if json.dumps(current, sort_keys=True) != authority:
            raise ValueError(
                "release authority changed before publication — inspect current evidence"
            )
        if inputs() != before or git("status", "--porcelain").stdout.strip():
            raise ValueError(
                "shipping inputs changed during validation/lifecycle — retry post-merge"
            )
        if before["branch"] != default_branch() or before["owner"] != sprint_branch_name(
            release_id
        ):
            raise ValueError("release branch/owner changed — restore the intended release context")
        if error := coverage_refusal(release_id, accepted):
            raise ValueError(error)
        owner_head = git(
            "rev-parse", "--verify", "-q", f"{before['owner']}^{{commit}}", check=False
        ).stdout.strip()
        if (
            owner_head
            and git("merge-base", "--is-ancestor", owner_head, "HEAD", check=False).returncode
        ):
            raise ValueError(
                "release branch carries unmerged commits — merge or drop them before retrying"
            )
        if receipt["tree"] != before["tree"]:
            raise ValueError("validation measured another tree — retry post-merge")

    def after_write():
        if error := publish():
            raise ValueError(error)

    try:
        sprint_state.write_sprint_state(marker, under_lock, after_write=after_write)
    except (OSError, ValueError) as exc:
        return str(exc)
    return ""
