"""Sprint round coverage and exemptions at land."""

import overlap
from release import release_bump_paths
from review import CLEARABLE_BY_FULL, covered_ranges, reviewer_strays, validate_clearable
from sprint_close import _shown_diff, default_branch, git, read_sprint_state


def _is_retro_prose(path: str) -> bool:
    return path.startswith(".xp/") and path not in overlap.GATE_FILES


def _blocking_refusal(blocking: list) -> str:
    return (
        "refused: the last round left blocking findings:\n  "
        + "\n  ".join(blocking)
        + "\nFix them, then review again — a flag cannot clear these"
    )


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


def coverage_refusal(
    sprint_id: str, head: str, state: dict | None = None, reported: set[str] | None = None
) -> str:
    if state is None:
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
        shown = str(round_.get("shown_sha", state.get("shown_sha")))
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
    if (shown := str(round_.get("shown_sha", state.get("shown_sha")))) == head:
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
    paths = git("diff", "--no-renames", "--name-only", shown, head).stdout.splitlines()
    eligible, trunk_range, state_reason = overlap.trunk_only_paths(
        round_.get("review_base"), shown, head, default_branch()
    )
    if state_reason.startswith("refused:"):
        return state_reason
    exempt = sorted(set(paths) & eligible)
    if exempt and (reported is None or trunk_range not in reported):
        print(f"trunk-only paths from {trunk_range}: {', '.join(exempt)}")
        if reported is not None:
            reported.add(trunk_range)
    paths = [path for path in paths if path not in eligible]
    bumps = release_bump_paths(shown, head, paths) - set(overlap.GATE_FILES)
    if code := [f for f in paths if not _is_retro_prose(f) and f not in bumps]:
        return (
            f"refused: the review did not cover HEAD — {', '.join(code)}"
            f" changed since {shown[:8]}. {rerun}"
        )
    retro = sorted(set(paths) - bumps)
    kinds = [f".xp/ prose: {', '.join(retro)}"] if retro else []
    if bumps:
        kinds.append(f"the release bump: {', '.join(sorted(bumps))}")
    if kinds:
        print(f"reviewed earlier; the delta since is {' and '.join(kinds)}")
    return ""
