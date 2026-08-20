#!/usr/bin/env python3
"""Spawn the story-reviewer and read its structured report — close.py's review leg.

Extracted from close.py at story-008 rather than left inline: this block is the
only seam, and close.py runs against the 500-line hard cap (constraints.md #8).
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PLUGIN_ROOT = Path(__file__).parent.parent

REPORT_KEYS = ("fixed", "blocking", "noted")
# The report rides into the merge body, closes.jsonl and SessionStart's recovery
# block. Bounded AT THE WRITE, not at each read: the predecessor's json bounded
# size by validating on the way in, and three unbounded lists in the section that
# already evicted constraints.md is the same defect with more shapes.
ITEM_CAP = 400
LIST_CAP = 20

# The reviewer FIXES now, so it writes. The deny-list never bounded that anyway —
# Bash was always allowed and `git commit` was always reachable. What held
# story-008's G1 was the moved-HEAD refusal, and story-012b replaces it with
# AUTHORSHIP: the reviewer commits under its own identity, and any commit in the
# range that is not its own means unreviewed work is riding along.
REVIEWER_NAME = "xp story-reviewer"
REVIEWER_EMAIL = "story-reviewer@xp.local"


def charter() -> str:
    """agents/story-reviewer.md, frontmatter stripped.

    The reviewer runs as a top-level headless session, not as a subagent, so the
    harness never loads the agent file — inlining it is the mechanism and the
    path is the fallback (spawn.py's rule).
    """
    from spawn import _read_shipped

    text = _read_shipped(PLUGIN_ROOT / "agents" / "story-reviewer.md")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def report_path(story_id: str, round_n: int) -> Path:
    """Where this round's report goes. ROUND-scoped, not story-scoped: the round
    index advances only on a RECORDED round, so every failed attempt at round N
    reuses N's path and a leftover from a crashed reviewer would certify a round
    that produced nothing. The caller unlinks before launching."""
    from work import data_root

    d = data_root() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{story_id}.round-{round_n}.json"


def _cap(items: list, path: Path) -> list:
    kept = [i if len(i) <= ITEM_CAP else i[: ITEM_CAP - 1] + "…" for i in items[:LIST_CAP]]
    if len(items) > LIST_CAP:
        # name the FILE: the merge body is where this is read, and without a path
        # the reader knows only that something was elided, not where it survives
        kept[-1] = f"(+{len(items) - LIST_CAP + 1} more, in full at {path})"
    return kept


def read_report(path: Path) -> tuple[dict, str]:
    """(report, error). Replaces the VERDICT-line grep, which was forgeable by
    design (story-002) and then defeated by backticks (story-008). This fixes
    PARSING, not forgery — a reviewer under bypass writes any path it likes.
    """
    if not path.exists():
        return {}, (
            f"the reviewer wrote no report at {path} — its findings are above and"
            " are all that survives. No report, no round"
        )
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        return {}, f"the reviewer's report is not JSON ({e})"
    if not isinstance(data, dict):
        return {}, f"the reviewer's report is JSON but not an object: got {type(data).__name__}"
    missing = [k for k in REPORT_KEYS if not isinstance(data.get(k), list)]
    if missing:
        return {}, f"the reviewer's report is missing list keys: {', '.join(missing)}"
    return {k: _cap([str(i) for i in data[k]], path) for k in REPORT_KEYS}, ""


def marker_digest(path: Path) -> str:
    """Content hash of the file that GATES the merge. It lives outside the repo,
    so no diff shows it, and the reviewer's Bash can reach it — emptying its own
    blocking[] is the charter's own "gate that advances its own state"."""
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def abort_text(reviewed_head: str, why: str) -> str:
    """EVERY abort in the review leg, not only the motion checks. The tree now
    holds commits from a process refused mid-fix — a state this pipeline has
    never had, and "nothing was recorded" was written for a reviewer that could
    not write. The undo is offered only when the reviewer actually moved
    something: offering it on a tree nobody touched teaches the lead to skip it
    on the run where it is real.
    """
    from close import git

    moved = git("rev-parse", "HEAD").stdout.strip() != reviewed_head
    if not (moved or git("status", "--porcelain").stdout.strip()):
        return f"refused: {why}"
    stat = git("diff", "--stat", f"{reviewed_head}..HEAD").stdout
    return (
        f"refused: {why}\n\n{stat}\nNo round was recorded, and the reviewer's work is"
        f" in your tree — yours to keep or undo: git reset --hard {reviewed_head[:8]}"
    )


def check_reviewer_motion(reviewed_head: str, marker: Path, digest_before: str) -> str:
    """The complete refusal text, or "" if the reviewer behaved.

    The dirty-tree case never says WHO left the files: at story-008 the guard
    blamed the reviewer for the LEAD's edit, and that misattribution is the
    measured complaint this whole story descends from.
    """
    from close import git

    def refuse(why: str) -> str:
        return abort_text(reviewed_head, why)

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
    rng = f"{reviewed_head}..HEAD"
    strays = [
        ln
        for ln in git("log", "--format=%h|%an|%s", rng).stdout.splitlines()
        if ln.split("|")[1] != REVIEWER_NAME
    ]
    if strays:
        return refuse(
            "commits in this review's range were not authored by the reviewer, so"
            " work no reviewer read would ride the merge:\n  " + "\n  ".join(strays)
        )
    touched = git("diff", "--name-only", rng).stdout.splitlines()
    if any(f.startswith(".xp/") for f in touched):
        return refuse("the reviewer changed .xp/ — it may fix code, never the plan or the rules")
    return ""


def reviewer_range(reviewed_head: str) -> str:
    """`git log` + `--stat` over what the reviewer committed, or "" if it committed
    nothing. The lead reads this to accept the fixes; land re-prints it because
    assent is given by RUNNING land, not by having read an earlier command."""
    from close import git

    if git("rev-parse", "HEAD").stdout.strip() == reviewed_head:
        return ""
    rng = f"{reviewed_head}..HEAD"
    return git("log", "--format=%h %an %s", rng).stdout + git("diff", "--stat", rng).stdout


def diff_path(report: Path) -> Path:
    """One spelling: review writes it, review unlinks the stale one, land prints
    it — three sites that would otherwise drift."""
    return report.with_suffix(".diff")


def write_reviewer_diff(report: Path, reviewed_head: str) -> Path | None:
    """The reviewer's work, on disk beside its report. review's stdout is the
    channel this project lost three reviews down in one session, and it is the
    only place the assent artifact lived."""
    from close import git

    summary = reviewer_range(reviewed_head)
    if not summary:
        return None
    diff = diff_path(report)
    diff.write_text(summary + "\n" + git("diff", f"{reviewed_head}..HEAD").stdout)
    return diff


def run(prompt: str, cwd: Path, dry_run: bool = False) -> tuple[str, str]:
    """Launch the reviewer. Returns (result_text, error) — never raises on a
    reviewer that crashes, prints prose, or is missing from PATH.

    Imports are function-local: spawn.py imports from close.py and close.py
    imports this module, so module-level edges would close a cycle.
    """
    from spawn import claude_argv, resolve_role, run_agent

    _harness, model, effort = resolve_role("reviewer")
    argv = claude_argv(model, effort, "json")
    if dry_run:
        print("would launch: " + " ".join(argv))
        print(prompt)
        return "", ""
    # capture + --output-format json means total silence for the whole run;
    # without this line a multi-minute review is indistinguishable from a hang.
    print(f"spawning story-reviewer ({model}) — no output until it finishes", file=sys.stderr)
    try:
        proc = run_agent(argv, cwd, prompt, role="reviewer", capture=True)
    except OSError as e:  # claude absent from PATH
        return "", f"could not launch the reviewer: {e}"
    except subprocess.TimeoutExpired as e:
        return "", (
            f"the reviewer exceeded its {e.timeout:.0f}s wall clock and was killed."
            " Its output is lost; check the tree for commits it made before dying"
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        return "", f"reviewer exited {proc.returncode}: {detail}"
    try:
        return json.loads(proc.stdout)["result"], ""
    except (ValueError, KeyError, TypeError):
        return "", f"reviewer output was not the expected JSON: {proc.stdout.strip()[:300]}"
