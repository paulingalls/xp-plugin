#!/usr/bin/env python3
"""Spawn the story-reviewer and read its structured report — xp.py's review leg."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import refuse_direct_invocation
from review_card import card_now
from review_refusal import abort_text
from review_report import (
    CLEARABLE_BY_FULL,  # noqa: F401
    ITEM_CAP,  # noqa: F401
    LIST_CAP,  # noqa: F401
    NO_ROUND,  # noqa: F401
    REPORT_KEYS,  # noqa: F401
    cap_display,  # noqa: F401
    cap_items,  # noqa: F401
    read_report,  # noqa: F401
    validate_clearable,  # noqa: F401
)
from review_scope import declared_files  # noqa: F401
from teammate_tee import agent_log_id
from work import data_root

PLUGIN_ROOT = Path(__file__).parent.parent

# Either key means the round accounts for its own range, so top-level coverage is not its.
ACCOUNTED = {"reviewed_head", "incomplete"}

# A marker naming no artifact leaves the verdict UNKNOWN, which is neither "signed off"
# nor "nobody signed": the lead is owed the state and the check, never a guessed file.
UNKNOWN = " — what that review produced is UNKNOWN; confirm the plan was reviewed before close"


def charter(name: str = "story-reviewer") -> str:
    from spawn import _read_shipped

    text = _read_shipped(PLUGIN_ROOT / "agents" / f"{name}.md")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def plan_review_notice(story_id: str) -> str:
    from slate_review import review_marker

    marker = review_marker(story_id, "plan")
    if not marker.exists():
        return ""
    try:
        detail = marker.read_text().strip()
    except OSError as exc:
        return f"{story_id}'s plan-review marker is UNREADABLE at {marker} ({exc}){UNKNOWN}"
    try:
        state = json.loads(detail)
    except ValueError:
        return f"{story_id}'s plan review marker is CORRUPT at {marker}{UNKNOWN}"
    if not isinstance(state, dict):
        return f"{story_id}'s plan review marker is CORRUPT at {marker}{UNKNOWN}"
    binding = state.get("findings")
    if not isinstance(binding, str) or not binding.strip():
        return f"{story_id}'s plan review marker has no findings binding at {marker}{UNKNOWN}"
    findings = Path(binding)
    try:
        written = findings.read_text().strip()
    except FileNotFoundError:
        return (
            f"{story_id}'s plan review DID NOT COMPLETE — its bound findings are MISSING at"
            f" {findings}; its marker remains. The story was written against a plan no reviewer"
            " signed off"
        )
    except OSError as exc:
        return f"{story_id}'s plan-review findings are UNREADABLE at {findings} ({exc})"
    if written:
        return f"{story_id}'s plan review PRODUCED FINDINGS at {findings}; its marker remains"
    return (
        f"{story_id}'s plan review DID NOT COMPLETE at {findings} — its bound findings are empty."
        " The story was written against a plan no reviewer signed off"
    )


def report_path(story_id: str, round_n: int) -> Path:
    p = data_root() / "reports" / f"{story_id}.round-{round_n}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def sprint_report_path(sprint_id: str, stage: str, round_n: int) -> Path:
    d = data_root() / "reports" / "sprint"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sprint_id}.{stage}.round-{round_n}.json"


def patch_path(report: Path) -> Path:
    return report.with_suffix(".patch")


def launch_marker(story_id: str, *, create: bool = True) -> Path:
    """What the review was launched AGAINST, on disk before it starts, because a
    killed reviewer returns nothing on its way out and salvage needs it all."""
    p = data_root() / "markers" / f"{story_id}.review-launch"
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def stamp(path: Path, why: str) -> str:
    return why


def marker_digest(path: Path) -> str:
    """Content hash of the file that GATES the merge. It lives outside the repo,
    so no diff shows it, and the reviewer's Bash can reach it — emptying its own
    blocking[] is the charter's own "gate that advances its own state"."""
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def write_round(
    marker: Path, state: dict, round_: dict, edit=None, position=None, **coverage: str
) -> None:
    def append(current: dict) -> None:
        rounds = current.setdefault("rounds", [])
        stamped = round_ | coverage
        if position is not None and position < len(rounds):
            # A SALVAGED round is an older attempt recorded out of order. It never
            # saw the rounds already here, and they never saw it, so neither can
            # clear the other's findings — the flag is what lets land say so.
            rounds.insert(position, stamped | {"salvaged": True})
            return
        if old := next((r for r in reversed(rounds) if not r.keys() & ACCOUNTED), None):
            prior = {key: current[key] for key in coverage if key in current}
            old.update(prior)
        rounds.append(stamped)
        current.update(coverage)

    if edit:
        current = edit(marker, append)
        state.clear()
        state.update(current)
    else:
        append(state)
        marker.write_text(json.dumps(state))


def check_reviewer_motion(
    reviewed_head: str,
    marker: Path,
    digest_before: str,
    card: str = "",
    story_id: str = "",
    moved: str = "",
    salvage=False,
    preserve_motion=False,
) -> str:
    """The complete refusal text, or "" if the reviewer behaved.

    Neither the dirty-tree case nor `moved` says WHO — a guard that blames the
    reviewer for the lead's edit is worse than no guard. Only the completed leg
    can attribute HEAD motion, because there the lead is blocked inside the
    reviewer subprocess; salvage runs after unbounded lead time, so it passes
    its own text.
    """
    from close import git, salvage_dirty_refusal

    def refuse(why: str) -> str:
        return abort_text(reviewed_head, why, salvage=salvage)

    if salvage and (dirty := salvage_dirty_refusal()):
        return refuse(dirty)
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty:
        return refuse(
            "the working tree is dirty at the end of the review; uncommitted:\n  " + dirty
        )

    if marker_digest(marker) != digest_before:
        return refuse(
            f"the close marker changed during the review ({marker}). It is the file"
            " land reads for blocking findings, it is outside the repo, and no diff"
            " shows it — a review may not move its own gate"
        )
    # `git diff` below cannot see the plan any more. Scoped to this story's OWN
    # card, never the whole file: it is shared, so a whole-file digest would let a
    # sibling lane's flip refuse THIS review. Cross-lane rewrites stay uncaught by
    # mechanism — note 1bcb794f.
    if story_id and card_now(story_id) != card:
        return refuse(
            f"{story_id}'s own card changed during the review. The plan lives outside"
            " the repo, so no diff shows it, and a review may not rewrite the card it"
            " is being reviewed under"
        )
    # Ancestry-BLIND, and every check below reads that range: a reviewer that RESET
    # past reviewed_head leaves only its own commits in it, so authorship passes over
    # the lead's deleted work — and shown_sha is read too late to see it (012b N2).
    if git("merge-base", "--is-ancestor", reviewed_head, "HEAD", check=False).returncode:
        return refuse(
            "HEAD no longer contains the tree you were shown — the review REWROTE"
            " history, so commits it was handed are not in what would merge"
        )
    if git("rev-parse", "HEAD").stdout.strip() != reviewed_head:
        if preserve_motion:
            return f"refused: {moved}"
        return refuse(moved or "the read-only reviewer changed HEAD; no reviewer leg may commit")
    return ""


def reviewer_range(start: str, end: str) -> str:
    """Show the commits and stat in one covered range."""
    from close import git

    if start == end:
        return ""
    rng = f"{start}..{end}"
    return git("log", "--format=%h %an %s", rng).stdout + git("diff", "--stat", rng).stdout


def covered_ranges(state: dict, head: str) -> list[tuple[str, str]]:
    """One range PER ROUND, in round order: disclose numbers them by position and names
    each round's own diff. A round with no coverage holds its PLACE, and only a PRE-0.18
    one may claim the top-level pair: a killed round reviewed nothing (distinct-state rule)."""
    rounds = state.get("rounds", [])
    ranges = [(r.get("reviewed_head", head), r.get("shown_sha", head)) for r in rounds]
    legacy = (state.get("reviewed_head", head), state.get("shown_sha", head))
    stale = [i for i, r in enumerate(rounds) if not r.keys() & ACCOUNTED]
    if stale and legacy not in ranges:
        ranges[stale[-1]] = legacy
    return ranges or [legacy]


def disclose(state: dict, head: str, diff_for=None) -> None:
    """Show every reviewed range plus work committed after the last one."""
    rounds = state.get("rounds") or []
    for index, (reviewed, round_shown) in enumerate(covered_ranges(state, head)):
        if work := reviewer_range(reviewed, round_shown):
            print(f"the reviewer changed this tree — you are merging its work:\n{work}", end="")
            if diff_for:
                # the file was named for the round it was WRITTEN as; an insertion
                # moves the list index away from it, and the index would name
                # another round's diff or none at all.
                at = rounds[index] if index < len(rounds) else {}
                print(f"full diff: {diff_for(at.get('round_file', index + 1))}")
    if late := reviewer_range(state.get("shown_sha", head), head):
        print("you committed after the review you were shown — merging unreviewed:")
        print(late, end="")


def round_number(report: Path) -> int:
    """The round a report FILE is named for. rotate_story names the diff beside it,
    so this is what pairs a recorded round with its evidence on disk."""
    tail = report.stem.rpartition(".round-")[2]
    return int(tail) if tail.isdigit() else 0


def diff_path(report: Path) -> Path:
    return report.with_suffix(".diff")


def write_reviewer_diff(report: Path, reviewed_head: str, noun: str) -> str:
    from close import git

    summary = reviewer_range(reviewed_head, git("rev-parse", "HEAD").stdout.strip())
    if not summary:
        return ""
    diff = diff_path(report)
    try:
        diff.write_text(summary + "\n" + git("diff", f"{reviewed_head}..HEAD").stdout)
    except OSError as exc:
        return f"refused: could not write fix evidence at {diff} ({exc}); keep the committed fix"

    print(
        f"the committed review fix changed the tree. Read its commit and full"
        f" diff at {diff} before `xp.py {noun} land`; landing accepts it."
    )
    return ""


def stage_role(stage: str, card: str, fallback: str = "") -> tuple[str, str, str]:
    """(harness, model, effort) for one role whose config key may be absent. The
    default fallback is `reviewer` AND DROPS THE CARD: `Reviewer:` is the story
    leg's per-story twin of `Executor:`, and one card carrying it must not
    retarget a whole sprint's review. A NAMED fallback keeps the card, because it
    stands in for a role the card may legitimately pin. Resolving REFUSES on a bad
    spec, which is why cmd_review walks every stage before the first launch."""
    from spawn import card_role, config_role, resolve_role

    if card_role(card, stage) or config_role(stage, "\0") != "\0":
        return resolve_role(stage, card)
    return resolve_role(fallback or "reviewer", card if fallback else "")


def run(
    prompt: str,
    cwd: Path,
    dry_run=False,
    name="",
    card="",
    role="",
    checked=False,
    noun="",
    cancel=None,
    log_id="",
) -> tuple[str, str]:
    """Launch a configured reviewer, returning (result text, error).
    Function-local imports avoid spawn -> close -> review cycling at import time."""
    from close import config_flat
    from spawn import agent_argv, missing_harness, resolve_codex_sandbox, run_agent

    name = name or "story-reviewer"
    if stage := role:
        harness, model, effort = stage_role(stage, card)
    else:
        role = name if name in ("planner", "plan-reviewer") else "reviewer"
        # `seat` is the config key ONLY — `role` stays "reviewer" for both read-only
        # gates, because run_agent binds their timeout and credential strip off it.
        seat, fallback = {
            "planner": ("planner", "executor"),
            "plan-reviewer": ("plan-reviewer", ""),
            "slate-reviewer": ("slate-reviewer", "reviewer"),
        }.get(name, ("reviewer", ""))
        seat_card = "" if name == "slate-reviewer" else card
        harness, model, effort = stage_role(seat, seat_card, fallback)
    sandbox, problem = resolve_codex_sandbox(harness, config_flat("codex_sandbox"))
    if problem:
        return "", problem
    if not checked and (missing := missing_harness(harness)):
        return "", missing
    argv = agent_argv(harness, model, effort, "stream-json", sandbox)
    if dry_run:
        print("would launch: " + " ".join(argv))
        print(prompt)
        return "", ""
    log_id = log_id or agent_log_id(
        name, role, card if stage in ("reviewer", "fixer", "closer") else "" if stage else card
    )
    try:
        # finders, then verifiers, run concurrently: their streams stay in their own logs
        echo = stage not in ("finder", "verifier")
        proc = run_agent(
            argv,
            cwd,
            prompt,
            "fixer" if stage == "fixer" else "reviewer" if stage else role,
            harness,
            log_id,
            echo,
            cancel=cancel,
        )
    except OSError as e:  # claude absent from PATH
        return "", f"could not launch the reviewer: {e}"
    except subprocess.TimeoutExpired as e:
        return "", (
            f"the reviewer produced NO OUTPUT for {e.timeout:.0f}s and was killed."
            f" Live output remains in {e.stderr}. Lead: inspect retained work."
            " Widen the silence it may"
            " keep with XP_AGENT_TIMEOUT=<seconds> and review again"
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        return "", f"reviewer exited {proc.returncode}: {detail}"
    return result_text(harness, proc)


def result_text(harness: str, proc: subprocess.CompletedProcess) -> tuple[str, str]:
    """(what to show the lead, error) — the only harness divergence here; downstream
    reads the report JSON. run_stream already reassembled the terminal result, so
    codex's agent_message text IS the value; claude's is the envelope around it."""
    if harness != "claude":
        return (proc.stdout.strip() or proc.stderr.strip()), ""
    try:
        return json.loads(proc.stdout)["result"], ""
    except (ValueError, KeyError, TypeError):
        return "", f"reviewer output was not the expected JSON: {proc.stdout.strip()[:300]}"


if __name__ == "__main__":
    refuse_direct_invocation("xp.py <mode> <id> review")
