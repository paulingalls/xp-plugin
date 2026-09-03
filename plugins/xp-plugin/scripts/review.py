#!/usr/bin/env python3
"""Spawn the story-reviewer and read its structured report — close.py's review leg."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import refuse_direct_invocation
from work import data_root

PLUGIN_ROOT = Path(__file__).parent.parent

REPORT_KEYS = ("fixed", "blocking", "noted")
NO_ROUND = "No round was recorded."
ITEM_CAP = 400
LIST_CAP = 20

REVIEWER_NAME = "xp story-reviewer"
REVIEWER_EMAIL = "story-reviewer@xp.local"


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
        state = json.loads(detail)
    except OSError as exc:
        return f"{story_id}'s plan-review marker is UNREADABLE at {marker} ({exc})"
    except ValueError:
        state = {}
    default = data_root() / "plans" / f"{story_id}.md"
    findings = Path(state.get("findings") or default) if isinstance(state, dict) else default
    try:
        written = findings.read_text().strip()
    except FileNotFoundError:
        written = ""
    except OSError as exc:
        return f"{story_id}'s plan-review findings are UNREADABLE at {findings} ({exc})"
    if written:
        return f"{story_id}'s plan review PRODUCED FINDINGS at {findings}; its marker remains"
    return (
        f"{story_id}'s plan review DID NOT COMPLETE — {detail}."
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


def cap_items(items: list) -> list:
    return [i if len(i) <= ITEM_CAP else i[: ITEM_CAP - 1] + "…" for i in items]


def cap_display(items: list, path: Path) -> list:
    kept = cap_items(items[:LIST_CAP])
    if len(items) > LIST_CAP:
        # A display elision must point to the full durable report.
        kept[-1] = f"(+{len(items) - LIST_CAP + 1} more, in full at {path})"
    return kept


def _report_data(path: Path) -> tuple[dict, str]:
    if not path.exists():
        message = f"the reviewer wrote no report at {path} — its findings are above"
        return {}, f"{message} and are all that survives. {NO_ROUND}"
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        return {}, f"could not read reviewer report {path} ({e})"
    except ValueError as e:
        return {}, f"the reviewer's report is not JSON ({e})"
    if not isinstance(data, dict):
        return {}, f"the reviewer's report is JSON but not an object: got {type(data).__name__}"
    missing = [k for k in REPORT_KEYS if not isinstance(data.get(k), list)]
    if missing:
        return {}, f"the reviewer's report is missing list keys: {', '.join(missing)}"
    return data, ""


def read_report(path: Path) -> tuple[dict, str]:
    """Parse and cap a report; a reviewer under bypass can still forge its path."""
    data, error = _report_data(path)
    if error:
        return {}, error
    return {k: cap_items([str(i) for i in data[k]]) for k in REPORT_KEYS}, ""


def launch_marker(story_id: str) -> Path:
    """What the review was launched AGAINST, on disk before it starts, because a
    killed reviewer returns nothing on its way out and salvage needs it all."""
    p = data_root() / "markers" / f"{story_id}.review-launch"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def stamp(path: Path, why: str) -> str:
    """Record the refusal IN the report and return `why`; `why` of "" clears one.

    close.py keeps a refused round's report on purpose, and the file a person
    opens to ask "did this round pass" then answered `blocking: []` either way.
    Writing only when the key MOVES is what leaves an accepted report byte-
    identical. Only a report we could parse: unreadable is a different problem
    and read_report already distinguishes unreadable from absent.
    """
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return why
    if not isinstance(report, dict):
        return why
    had = report.pop("refused", None)  # ours wins: a reviewer may write it too
    if why:
        path.write_text(json.dumps({"refused": why} | report, indent=2))
    elif had is not None:
        path.write_text(json.dumps(report, indent=2))
    return why


def marker_digest(path: Path) -> str:
    """Content hash of the file that GATES the merge. It lives outside the repo,
    so no diff shows it, and the reviewer's Bash can reach it — emptying its own
    blocking[] is the charter's own "gate that advances its own state"."""
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def write_round(marker: Path, state: dict, round_: dict, **coverage: str) -> None:
    rounds = state.setdefault("rounds", [])
    if old := next((r for r in reversed(rounds) if "reviewed_head" not in r), None):
        prior = {key: state[key] for key in coverage if key in state}
        old.update(prior)
    rounds.append(round_ | coverage)
    state.update(coverage)
    marker.write_text(json.dumps(state))


def abort_text(reviewed_head: str, why: str, recorded: str = NO_ROUND) -> str:
    """EVERY abort in the review leg, not only the motion checks: a refused run can
    still have left commits behind. The undo is offered only when something
    actually moved — offered on an untouched tree, it teaches the lead to skip it
    on the run where it is real. `recorded` is what became of the round, because a
    leg that records one before refusing must not offer the undo under a sentence
    saying it did not — and the reset may be what orphans the sha it names.
    """
    from close import git

    moved = git("rev-parse", "HEAD").stdout.strip() != reviewed_head
    if not (moved or git("status", "--porcelain").stdout.strip()):
        return f"refused: {why}" if recorded == NO_ROUND else f"refused: {why}\n\n{recorded}"
    stat = git("diff", "--stat", f"{reviewed_head}..HEAD").stdout
    return (
        f"refused: {why}\n\n{stat}\n{recorded} The reviewer's work is in your tree —"
        f" yours to keep or undo: git reset --hard {reviewed_head[:8]}"
    )


def check_reviewer_motion(
    reviewed_head: str,
    marker: Path,
    digest_before: str,
    card: str = "",
    story_id: str = "",
    moved: str = "",
) -> str:
    """The complete refusal text, or "" if the reviewer behaved.

    Neither the dirty-tree case nor `moved` says WHO — a guard that blames the
    reviewer for the lead's edit is worse than no guard. Only the completed leg
    can attribute HEAD motion, because there the lead is blocked inside the
    reviewer subprocess; salvage runs after unbounded lead time, so it passes
    its own text.
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
        return refuse(moved or "the read-only reviewer changed HEAD; no reviewer leg may commit")
    return ""


DECORATION = re.compile(r"\s*\(new\)\s*$")


def _bare(entry: str) -> str:
    """A Files: entry is prose a human wrote for a human, and git prints neither the
    markdown backticks nor the `(new)` a card puts on a file that does not exist yet.
    Twice, because either decoration may sit inside the other (issue #45)."""
    for _ in range(2):
        entry = DECORATION.sub("", entry.strip().strip("`"))
    return entry.strip()


def declared_files(card: str) -> set[str]:
    declared, in_files = set(), False
    for ln in card.splitlines():
        if ln.startswith("Files:"):
            in_files, ln = True, ln.removeprefix("Files:")
        elif in_files and re.match(r"[A-Za-z][A-Za-z ]*:", ln):
            in_files = False
        if in_files:
            declared |= {f for f in (_bare(e) for e in ln.split(",")) if f}
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
        return (
            f"the reviewer proposed {', '.join(bad)} — the Files line does not name it."
            f" The reset undoes the patch in the tree, NOT the patch itself: it survives"
            f" at {path}, and a relaunched review deletes that file. Copy it if you want"
            " it, then name the path on the card and review again"
        )
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
        lines = (_plain(committed.stderr) or _plain(committed.stdout)).splitlines()
        # abort_text appends `git reset --hard` right under this, which discards the
        # staged patch this text just told the human to commit. Naming the patch file
        # is what keeps the two from reading as opposite instructions.
        return (
            "the reviewer patch did not commit — the commit gate refused it. The"
            " fixer is gone, so this is yours: fix what the gate names, commit the"
            f" staged tree yourself, then re-run — the patch is also at {path}, so"
            f" discarding the staged tree loses nothing. The gate's last"
            f" {min(12, len(lines))} of {len(lines)} lines:\n  " + "\n  ".join(lines[-12:])
        )
    return ""


def card_now(story_id: str) -> str:
    from close import story_card
    from work import plan_path

    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError):
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
    each round's own diff. A round that recorded no coverage — killed mid-round, or
    pre-0.18 — holds its PLACE; only the LAST of them left its coverage at top level."""
    rounds = state.get("rounds", [])
    ranges = [
        (r["reviewed_head"], r.get("shown_sha", head)) if "reviewed_head" in r else (head, head)
        for r in rounds
    ]
    legacy = (state.get("reviewed_head", head), state.get("shown_sha", head))
    if (head, head) in ranges and legacy not in ranges:
        ranges[max(i for i, c in enumerate(ranges) if c == (head, head))] = legacy
    return ranges or [legacy]


def disclose(state: dict, head: str, diff_for=None) -> None:
    """Show every reviewed range plus work committed after the last one."""
    for round_n, (reviewed, round_shown) in enumerate(covered_ranges(state, head), 1):
        if work := reviewer_range(reviewed, round_shown):
            print(f"the reviewer changed this tree — you are merging its work:\n{work}", end="")
            if diff_for:
                print(f"full diff: {diff_for(round_n)}")
    if late := reviewer_range(state.get("shown_sha", head), head):
        print("you committed after the review you were shown — merging unreviewed:")
        print(late, end="")


def diff_path(report: Path) -> Path:
    return report.with_suffix(".diff")


def write_reviewer_diff(report: Path, reviewed_head: str, noun: str) -> str:
    """Hand the script-applied fix over on disk, or say why no round may be
    recorded: stdout is lossy and this was the only place the assent artifact
    lived. The tree has ALREADY moved here, so a write that fails rolls back
    rather than leave the lead accepting commits nothing showed them, and
    abort_text covers a rollback that itself fails. `noun` is the caller's
    `story <id>` / `sprint <id>` / `free <slug>`: one rule, one implementation."""
    from close import git

    summary = reviewer_range(reviewed_head, git("rev-parse", "HEAD").stdout.strip())
    if not summary:
        return ""
    diff = diff_path(report)
    try:
        diff.write_text(summary + "\n" + git("diff", f"{reviewed_head}..HEAD").stdout)
    except OSError as exc:
        why = f"could not write reviewer handoff at {diff} ({exc})"
        if git("reset", "--hard", reviewed_head, check=False).returncode:
            return abort_text(reviewed_head, why)
        return f"refused: {why}; rolled the fix back — fix that path, then `close.py {noun} review`"
    print(
        f"the script-applied review fix changed the tree. Read its commit and full"
        f" diff at {diff} before `close.py {noun} land`; landing accepts it."
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
    prompt: str, cwd: Path, dry_run=False, name="", card="", role="", checked=False, noun=""
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
        # Old configs lack planner; executor is its behavioral fallback.
        harness, model, effort = stage_role(role, card, "executor" if role == "planner" else "")
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
    log_card = "" if stage else card
    log_id = ((re.search(r"#### (story-\d+)", log_card) or [None, name])[1] + "-review").replace(
        " ", "-"
    )
    try:
        proc = run_agent(argv, cwd, prompt, "reviewer" if stage else role, harness, log_id)
    except OSError as e:  # claude absent from PATH
        return "", f"could not launch the reviewer: {e}"
    except subprocess.TimeoutExpired as e:
        salvage = (
            # NOT "saves you a review": true of story/free, where salvage records a
            # landable round, and false of sprint, where it records an incomplete one
            # land always refuses. One sentence, three nouns.
            f" If it wrote its report and patch before dying, `close.py {noun}"
            " salvage` records that round from what survives instead of discarding it."
            if noun
            else ""
        )
        return "", (
            f"the reviewer produced NO OUTPUT for {e.timeout:.0f}s and was killed."
            f" Live output remains in {e.stderr}.{salvage} Widen the silence it may"
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
    refuse_direct_invocation("close.py <mode> <id> review")
