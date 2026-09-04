"""Sprint land coverage and release handoff."""

import json
import subprocess

import overlap
from release import cmd_post_merge as release_post_merge
from release import next_version, refuse_unbumpable
from review import CLEARABLE_BY_FULL, covered_ranges, reviewer_strays, validate_clearable
from sprint_close import _shown_diff, default_branch, fail, git, sprint_marker
from work import config_block_value


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


def _coverage_refusal(sprint_id: str, head: str) -> str:
    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
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
    if CLEARABLE_BY_FULL in round_:
        bound, error = validate_clearable(round_, stage="closer")
        if error:
            return f"refused: corrupt sprint review marker: {error}. {rerun}"
    else:
        bound = []
    if bound:
        remaining = list(blocking)
        for item in bound:
            remaining.remove(item)
        if remaining:
            return _blocking_refusal(blocking)
        shown = str(state.get("shown_sha"))
        if shown != head:
            moved, missing = _shown_diff(sprint_id, shown, head)
            if missing:
                return missing
            return (
                f"refused: the review did not cover HEAD — {', '.join(moved.stdout.splitlines())}"
                f" changed since {shown[:8]}. {rerun}"
            )
        gates = [
            path
            for start, end in covered_ranges(state, head)
            for path in git("diff", "--name-only", f"{start}..{end}").stdout.splitlines()
            if path in overlap.GATE_FILES
        ]
        if gates:
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
    cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", f"release {version}", "--body", f"Sprint {sprint_id}"],
    ]
    ref = overlap.merge_source(default_branch(), "pr")
    pending = overlap.unmerged(ref)
    state = json.loads(sprint_marker(sprint_id).read_text())
    bound = state["rounds"][-1].get(CLEARABLE_BY_FULL) or []
    if dry_run:
        full = config_block_value("tests", "full")
        if refusal := overlap.tier_refusal(full, "full"):
            return fail(_clearance_failure(refusal, bound) if bound else refusal)
        print(f"would run: {full}")
        for c in cmds:
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
    # Triage can stale start's tier, so land measures the shipping merge again.
    if red := overlap.gates(ref, "", "full", pending):
        return fail(_clearance_failure(red, bound) if bound else red)
    head = git("rev-parse", "HEAD").stdout.strip()
    review.disclose(
        state,
        head,
        lambda n: review.diff_path(review.sprint_report_path(sprint_id, "fix", n)),
    )
    if gates := [
        f
        for start, end in review.covered_ranges(state, head)
        for f in git("diff", "--name-only", f"{start}..{end}").stdout.splitlines()
        if f in overlap.GATE_FILES
    ]:
        print(f"among them a gate file, which no later check re-reads: {', '.join(gates)}")
    if not shutil.which("gh"):
        return fail(
            "refused: pr mode needs the gh CLI on PATH — install it, or open the PR by hand"
        )
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0:
            return fail(f"{c[0]} failed: {r.stderr.strip()}")
    print(f"release PR open. After it MERGES: close.py sprint {sprint_id} post-merge")
    return 0


def cmd_post_merge(sprint_id: str) -> int:
    return release_post_merge(sprint_id)
