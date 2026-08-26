#!/usr/bin/env python3
"""Spawn the story-reviewer and read its structured report — close.py's review leg."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# Module level: importers must reach env.py's 3.11 floor before the `Path | None` below
from env import refuse_direct_invocation
from work import data_root

PLUGIN_ROOT = Path(__file__).parent.parent

REPORT_KEYS = ("fixed", "blocking", "noted")
# Bounded AT THE WRITE, not at each read: the report rides into the merge body,
# closes.jsonl and the recovery block, and that section has evicted constraints.md
# before.
ITEM_CAP = 400
LIST_CAP = 20

REVIEWER_NAME = "xp story-reviewer"
REVIEWER_EMAIL = "story-reviewer@xp.local"


def charter(name: str = "story-reviewer") -> str:
    """agents/<name>.md, frontmatter stripped.

    It runs as a top-level headless session, not a subagent, so the harness never
    loads the agent file: inlining is the mechanism, the path is the fallback —
    and it is why the file's `tools:` line bounds nothing at all here.
    """
    from spawn import _read_shipped

    text = _read_shipped(PLUGIN_ROOT / "agents" / f"{name}.md")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def plan_review_notice(story_id: str) -> str:
    """The teammate's plan review left its marker behind, or "".

    A gate that did not run leaves no artifact of its own, so the marker is
    written at launch and removed on findings (plan_review.incomplete_marker).
    Measured twice in the field, neither visible from here: a review killed at the
    harness's own timeout guess, and one orphaned when its teammate yielded.
    """
    marker = data_root() / "markers" / f"{story_id}.plan-review-incomplete"
    if not marker.exists():
        return ""
    return (
        f"{story_id}'s plan review DID NOT COMPLETE — {marker.read_text().strip()}."
        " The story was written against a plan no reviewer signed off"
    )


def report_path(story_id: str, round_n: int) -> Path:
    """Where this round's report goes. ROUND-scoped: the index advances only on a
    RECORDED round, so failed attempts at round N share N's path and a leftover
    would certify a round that produced nothing. The caller unlinks first."""
    p = data_root() / "reports" / f"{story_id}.round-{round_n}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def sprint_report_path(sprint_id: str, stage: str, round_n: int) -> Path:
    """Its own DIRECTORY, not a prefix: story ids are free text, so any separator
    a sprint key uses is one a story can spell (constraints.md #10)."""
    d = data_root() / "reports" / "sprint"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sprint_id}.{stage}.round-{round_n}.json"


def patch_path(report: Path) -> Path:
    return report.with_suffix(".patch")


def _cap(items: list, path: Path) -> list:
    kept = [i if len(i) <= ITEM_CAP else i[: ITEM_CAP - 1] + "…" for i in items[:LIST_CAP]]
    if len(items) > LIST_CAP:
        # name the FILE: the merge body is where this is read, and without a path
        # the reader knows only that something was elided, not where it survives
        kept[-1] = f"(+{len(items) - LIST_CAP + 1} more, in full at {path})"
    return kept


def read_report(path: Path) -> tuple[dict, str]:
    """(report, error). This fixes PARSING, not forgery — a reviewer under bypass
    writes any path it likes.
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
    """EVERY abort in the review leg, not only the motion checks: a refused run can
    still have left commits behind. The undo is offered only when something
    actually moved — offered on an untouched tree, it teaches the lead to skip it
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


def check_reviewer_motion(
    reviewed_head: str, marker: Path, digest_before: str, card: str = "", story_id: str = ""
) -> str:
    """The complete refusal text, or "" if the reviewer behaved.

    The dirty-tree case never says WHO left the files — a guard that blames the
    reviewer for the lead's edit is worse than no guard.
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
    # `git diff` below cannot see the plan any more. Scoped to this story's OWN
    # card, never the whole file: it is shared, so a whole-file digest would let a
    # sibling lane's flip refuse THIS review (constraint 10). Cross-lane rewrites
    # stay uncaught by mechanism — note 1bcb794f.
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
        return refuse("the read-only reviewer changed HEAD; no reviewer leg may commit")
    return ""


def declared_files(card: str) -> set[str]:
    declared, in_files = set(), False
    for ln in card.splitlines():
        if ln.startswith("Files:"):
            in_files, ln = True, ln.removeprefix("Files:")
        elif in_files and re.match(r"[A-Za-z][A-Za-z ]*:", ln):
            in_files = False
        if in_files:
            declared |= {f.strip() for f in ln.split(",") if f.strip()}
    return declared


def reviewer_strays(start: str, end: str) -> list[str]:
    from close import git

    return [
        ln
        for ln in git("log", "--format=%h|%an|%s", f"{start}..{end}").stdout.splitlines()
        if ln.split("|")[1] != REVIEWER_NAME
    ]


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return ANSI.sub("", text).strip()


def apply_patch(report: Path, card: str) -> str:
    from close import git

    path = patch_path(report)
    if not path.exists() or not path.stat().st_size:
        return ""
    checked = git("apply", "--check", str(path), check=False)
    if checked.returncode:
        return f"the reviewer's patch does not apply cleanly: {checked.stderr.strip()}"
    applied = git("apply", "--index", str(path), check=False)
    if applied.returncode:
        return f"the reviewer's patch could not be applied: {applied.stderr.strip()}"
    # SCOPE from the staged tree with --no-renames, never from `git apply --numstat`:
    # numstat reports a rename's DESTINATION only, so a patch that renamed
    # .xp/config.yml OUT of .xp/ read as untouched and deleted the gate file.
    # Resetting is safe — check_reviewer_motion proved the tree clean and HEAD here.
    touched = git("diff", "--cached", "--name-only", "--no-renames", "HEAD").stdout.splitlines()
    if bad := [p for p in touched if p.startswith(".xp/") and p not in declared_files(card)]:
        git("reset", "-q", "--hard", check=False)  # a refusal must not become a traceback
        return f"the reviewer proposed {', '.join(bad)} — the Files line does not name it"
    env = os.environ | {
        "GIT_AUTHOR_NAME": REVIEWER_NAME,
        "GIT_COMMITTER_NAME": REVIEWER_NAME,
        "GIT_AUTHOR_EMAIL": REVIEWER_EMAIL,
        "GIT_COMMITTER_EMAIL": REVIEWER_EMAIL,
    }
    committed = subprocess.run(
        ["git", "commit", "-qm", "reviewer patch"], capture_output=True, text=True, env=env
    )
    if committed.returncode:
        # The commit gate is the caller here, so its output is a hook transcript:
        # ANSI frames and colour put the one line that matters screens deep inside
        # a box (field-reported, Legacy 0.7.4). Strip and tail to the cause.
        raw = _plain(committed.stderr) or _plain(committed.stdout)
        tail = "\n  ".join(raw.splitlines()[-12:])
        return (
            "the reviewer patch did not commit — the commit gate refused it. The"
            " fixer is gone, so this is yours: fix what the gate names, commit the"
            f" staged tree yourself, then re-run.\n  {tail}"
        )
    return ""


def card_now(story_id: str) -> str:
    """The story's card as the plan holds it now, or "" if unreadable."""
    from close import story_card
    from work import plan_path

    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError):
        return ""


def reviewer_range(start: str, end: str) -> str:
    """`git log` + `--stat` over one range, or "" if it is empty. TWO ranges now:
    HEAD may move past the review, so a single reviewed_head..HEAD would put the
    lead's own commits under the reviewer's name. land re-prints both because
    assent is given by RUNNING land, not by having read an earlier command."""
    from close import git

    if start == end:
        return ""
    rng = f"{start}..{end}"
    return git("log", "--format=%h %an %s", rng).stdout + git("diff", "--stat", rng).stdout


def disclose(state: dict, head: str, diff: Path | None = None) -> None:
    """Both ranges the lead assents to by RUNNING land. Printing only one of them
    puts the lead's own commits under the reviewer's name."""
    shown = state.get("shown_sha", head)
    if work := reviewer_range(state.get("reviewed_head", head), shown):
        print("the reviewer changed this tree — you are merging its work:")
        print(work, end="")
        if diff:
            print(f"full diff: {diff}")
    if late := reviewer_range(shown, head):
        print("you committed after the review you were shown — merging unreviewed:")
        print(late, end="")


def diff_path(report: Path) -> Path:
    """One spelling: review writes it, review unlinks the stale one, land prints
    it — three sites that would otherwise drift."""
    return report.with_suffix(".diff")


def write_reviewer_diff(report: Path, reviewed_head: str) -> Path | None:
    """The reviewer's work, on disk beside its report: stdout is lossy and it was
    the only place the assent artifact lived."""
    from close import git

    summary = reviewer_range(reviewed_head, git("rev-parse", "HEAD").stdout.strip())
    if not summary:
        return None
    diff = diff_path(report)
    diff.write_text(summary + "\n" + git("diff", f"{reviewed_head}..HEAD").stdout)
    return diff


def run(
    prompt: str, cwd: Path, dry_run: bool = False, name: str = "", card: str = ""
) -> tuple[str, str]:
    """Launch a reviewer; `name` doubles as the role key, so the two charters are
    the two roles. Returns (result_text, error) — never raises on a reviewer that
    crashes, prints prose, or is missing from PATH.

    Function-local imports: spawn -> close -> review would close a cycle.
    """
    from close import config_flat
    from spawn import agent_argv, missing_harness, resolve_codex_sandbox, resolve_role, run_agent

    name = name or "story-reviewer"
    role = name if name == "plan-reviewer" else "reviewer"
    harness, model, effort = resolve_role(role, card)
    sandbox, problem = resolve_codex_sandbox(harness, config_flat("codex_sandbox"))
    if problem:
        return "", problem
    argv = agent_argv(harness, model, effort, "stream-json", sandbox)
    if dry_run:
        print("would launch: " + " ".join(argv))
        print(prompt)
        return "", ""
    if missing := missing_harness(harness):
        return "", missing
    log_id = ((re.search(r"#### (story-\d+)", card) or [None, name])[1] + "-review").replace(
        " ", "-"
    )
    try:
        proc = run_agent(argv, cwd, prompt, role, harness, log_id)
    except OSError as e:  # claude absent from PATH
        return "", f"could not launch the reviewer: {e}"
    except subprocess.TimeoutExpired as e:
        return "", (
            f"the reviewer exceeded its {e.timeout:.0f}s wall clock and was killed"
            f" — raise it with XP_AGENT_TIMEOUT=<seconds> and review again."
            f" Live output remains in {e.stderr}; check the tree for commits"
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
    refuse_direct_invocation("close.py <mode> <id> review")
