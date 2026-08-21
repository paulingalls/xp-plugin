#!/usr/bin/env python3
"""Story-close pipeline: mechanical steps scripted, judgment left to the lead.

Two invocations, one judgment gap between them:
  close.py story <id> review -> preflight, spawn the story-reviewer, record the
                                structured report it writes, print its findings
  (the lead reads them and decides fix-or-ask — the one LLM-present moment the
   pipeline must not absorb, constraints.md #7)
  close.py story <id> land   -> Verify, merge under every recorded round, push,
                                delete the story branch, log the close

review owns the tree and is slow; land only moves refs, is a pure function of
recorded state, and NEVER spawns — so the rounds are the lead's to choose. The
report is pipeline-received: there is no --verdict flag, because a lead-supplied
one is forgeable, and Sprint 1 forged one.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bookkeep import (
    delete_story_branch,
    delete_story_markers,
    log_close,
    render_land_preview,
    render_merge_body,
    render_noted,
    render_prior_rounds,
)
from work import chdir_repo_root, config_block_value, data_root, work_entries_since


def fail(msg: str) -> "int":
    print(msg, file=sys.stderr)
    return 2


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def story_card(plan: str, story_id: str) -> tuple[str, str]:
    """Return (card_text, status) for the story's block in plan.md."""
    lines = plan.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"#### {story_id} ")), None)
    if start is None:
        raise KeyError(f"{story_id} not found in .xp/plan.md")
    rest = range(start + 1, len(lines))
    end = next((i for i in rest if lines[i].startswith("#### ")), len(lines))
    card = "".join(lines[start:end])
    if "[" not in lines[start]:
        raise KeyError(f"{story_id} header has no [status] bracket in .xp/plan.md")
    status = lines[start].rsplit("[", 1)[1].rstrip().rstrip("]")
    return card, status


def verify_commands(card: str) -> str:
    for ln in card.splitlines():
        if ln.startswith("Verify:"):
            return ln.removeprefix("Verify:").strip()
    return ""


def config_flat(key: str) -> str:
    """A flat top-level `key: value` from .xp/config.yml."""
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    for ln in cfg.read_text().splitlines():
        if ln.startswith(f"{key}:"):
            return ln.split(":", 1)[1].split("#")[0].strip()
    return ""


def integration_target() -> str:
    """The branch this story integrates into: the sprint branch under
    release: sprint (when it exists), else the default branch."""
    if config_flat("release") == "sprint":
        branch = config_flat("sprint_branch")
        if branch:
            # refs/heads explicitly: a tag with the same name wins plain rev-parse
            # and would freeze every guard on a ref that never moves
            ok = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
            if ok.returncode != 0:
                print(
                    f"sprint_branch is configured but refs/heads/{branch} does not exist —"
                    " refusing to fall back to the default branch (a fresh clone must"
                    " create the sprint branch, not silently merge to main)",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            return branch
    return default_branch()


def default_branch() -> str:
    head = git("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    if head.returncode == 0:
        return head.stdout.strip().rsplit("/", 1)[1]
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode == 0:
            return name
    raise SystemExit(fail("no main/master branch found and origin/HEAD unset"))


def origin_trunk_sha(trunk: str) -> str | None:
    """Fetched origin/<trunk> sha, or None without a remote. pr mode merges on
    origin; local mode merges the local trunk — each mode guards the ref it
    actually integrates (recording both at start, since mode is unknown then)."""
    if not git("remote", check=False).stdout.strip():
        return None
    git("fetch", "-q", "origin", trunk, check=False)
    r = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{trunk}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def trunk_worktree(trunk: str) -> str:
    """Path of the worktree holding <trunk>, or "" if no tree has it checked out."""
    path = ""
    for ln in git("worktree", "list", "--porcelain").stdout.splitlines():
        if ln.startswith("worktree "):
            path = ln[9:]
        elif ln == f"branch refs/heads/{trunk}":
            return path
    return ""


def marker_path(story_id: str) -> Path:
    d = data_root() / "markers"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{story_id}.close.json"


def build_bundle(card: str, base: str, report: Path, prior: str = "") -> str:
    import review  # function-local: spawn -> close -> review would close a cycle

    base_epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    sections = [
        ("Your charter", review.charter()),
        # One greppable line: the charter explains the shape, this is the address.
        ("Your report", f"REPORT_PATH: {report}"),
        ("Story card", card),
        ("Earlier rounds of THIS story", prior or "none — you are round 1"),
        ("Cumulative diff", git("diff", f"{base}..HEAD").stdout),
        ("work.md entries filed during the story", work_entries_since(base_epoch) or "none"),
        ("VALUES", _read_first(str(Path(__file__).parent.parent / "VALUES.md"))),
        ("Constraints", _read_first(".xp/constraints.md")),
        ("System context", _read_first(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _preflight(story_id: str, action: str) -> tuple[str, str, str]:
    """(card, trunk, error) — the checks both legs share."""
    if git("status", "--porcelain").stdout.strip():
        return "", "", "refused: working tree is dirty — commit or stash first"
    if not Path(".xp/plan.md").exists():
        return "", "", "refused: no .xp/plan.md here — is this an xp-managed repo?"
    try:
        card, status = story_card(Path(".xp/plan.md").read_text(), story_id)
    except KeyError as e:
        return "", "", f"refused: {e.args[0]}"
    if status != "in-progress":
        return "", "", f"refused: {story_id} is [{status}], {action} requires [in-progress]"
    trunk = integration_target()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in (trunk, default_branch()):
        return (
            "",
            "",
            f"refused: close from a story branch, not {branch} — a self-merge is a no-op"
            " that records the verdict nowhere",
        )
    return card, trunk, ""


def cmd_review(story_id: str, dry_run: bool = False) -> int:
    import review

    card, trunk, err = _preflight(story_id, "review")
    if err:
        return fail(err)
    # merge-base does NOT move when trunk advances, so a bare re-review re-baselines
    # this guard while the reviewer sees nothing new. BOTH refs: land guards whichever
    # one its mode integrates — local mode the local trunk, pr mode origin's.
    tips = (
        (trunk, git("rev-parse", f"refs/heads/{trunk}").stdout.strip()),
        (f"origin/{trunk}", origin_trunk_sha(trunk)),
    )
    for label, tip in tips:
        if tip and git("merge-base", "--is-ancestor", tip, "HEAD", check=False).returncode:
            return fail(
                f"refused: {label} has moved ahead of this branch's fork point."
                f" Run `git merge {label}` here first — that moves the merge base, so"
                " the review covers what land would actually merge. Re-running review"
                " without it buys no coverage"
            )
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    if not dry_run:  # a preview must not delete the findings of a refused round
        path.unlink(missing_ok=True)
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    digest_before = review.marker_digest(marker)
    prior = render_prior_rounds(state.get("rounds", []))
    result, err = review.run(build_bundle(card, base, path, prior), Path.cwd(), dry_run)
    if dry_run:
        return 0
    if err:  # crash, timeout, absent binary — it may still have committed first
        return fail(review.abort_text(head, err))
    # BEFORE any refusal below: a report the pipeline rejects still cost a full
    # review, and its findings exist nowhere else.
    print(result)
    motion = review.check_reviewer_motion(head, marker, digest_before)
    if motion:
        return fail(motion)
    report, err = review.read_report(path)
    if err:
        return fail(review.abort_text(head, err))
    state.setdefault("rounds", []).append(report)
    state["reviewed_head"] = head  # the tree the REVIEWER was shown
    diff = review.write_reviewer_diff(path, head)
    if diff:
        print(f"the reviewer changed the tree. Its commits and full diff: {diff}")
    # AFTER the leg: the reviewer's own fixes are part of what the lead is shown.
    state["shown_sha"] = git("rev-parse", "HEAD").stdout.strip()
    state["review_base"] = base
    # the tips READ BEFORE the launch: a teammate pushing during the review window
    # would otherwise be recorded as the reviewed state, and land would compare
    # equal and merge what no reviewer saw.
    state["trunk_sha"], state["origin_trunk_sha"] = tips[0][1], tips[1][1]
    marker.write_text(json.dumps(state))
    return 0


def _read_first(*candidates: str) -> str:
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p.read_text()
    return f"(missing: {candidates[0]})"


def cmd_land(story_id: str, merge_mode: str, dry_run: bool) -> int:
    import review

    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — Verify must judge the tree that merges")
    marker = marker_path(story_id)
    if not marker.exists():
        return fail(f"refused: no close in progress for {story_id} — run review first")
    state = json.loads(marker.read_text())
    trunk = integration_target()
    if merge_mode == "pr" and trunk != default_branch():
        return fail(
            f"refused: release: sprint stories close with --merge-mode local into {trunk};"
            " the PR to main happens at sprint close"
        )
    head = git("rev-parse", "HEAD").stdout.strip()
    # land NEVER spawns: a merge command that reviews owns the tree for minutes,
    # is never idempotent, and makes rounds something inflicted rather than chosen.
    if head != state.get("shown_sha"):
        return fail(
            f"refused: HEAD moved since the review you were shown"
            f" ({str(state.get('shown_sha'))[:8]}..{head[:8]})."
            f" Run `close.py story {story_id} review`, then land again"
        )
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    if state.get("review_base") != base:
        return fail(
            f"refused: the recorded round did not cover this tree — it was based on"
            f" {str(state.get('review_base'))[:8]}, today's merge base is {base[:8]}."
            f" Run `close.py story {story_id} review`"
        )
    rounds = state.get("rounds") or []
    if not rounds:
        return fail(f"refused: no recorded review round for {story_id} — run review first")
    blocking = rounds[-1]["blocking"]
    if blocking:
        return fail(
            "refused: the last review round left blocking findings:\n  "
            + "\n  ".join(blocking)
            + "\nFix them (or review again once fixed) — a flag cannot clear these"
        )
    moved = (
        origin_trunk_sha(trunk) != state.get("origin_trunk_sha")
        if merge_mode == "pr"
        else git("rev-parse", f"refs/heads/{trunk}").stdout.strip() != state.get("trunk_sha")
    )
    if moved:
        return fail(
            f"refused: {trunk} moved since review — the merged tree would differ from"
            " what was reviewed; run review again to re-baseline"
        )

    plan = Path(".xp/plan.md").read_text()
    try:
        card, _ = story_card(plan, story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    verify = verify_commands(card)
    if not verify:
        return fail(f"refused: {story_id} has no Verify: line — an unverifiable story cannot close")
    tier = config_block_value("tests", "story")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    verdict = render_merge_body(rounds)
    message = f"Merge {branch} ({story_id})\n\n{verdict}\n"
    pr_cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", f"{story_id}", "--body", verdict],
        ["gh", "pr", "merge", "--merge", "--delete-branch", "--body", verdict],
    ]
    # the merge happened on the REMOTE, so trunk comes back here before the flip
    pr_sync = [
        ["git", "fetch", "-q", "origin"],
        ["git", "checkout", "-q", trunk],
        ["git", "merge", "--ff-only", f"origin/{trunk}"],
    ]
    pr_bookkeep = [
        ["git", "commit", "-qm", f"{story_id} done"],
        ["git", "push", "origin", trunk],
    ]
    pr_steps = (pr_cmds, pr_sync, pr_bookkeep)
    if dry_run:  # pure preview: nothing runs, nothing changes, marker survives
        print(render_land_preview(verify, tier, merge_mode, branch, trunk, pr_steps), end="")
        return 0
    if subprocess.run(verify, shell=True).returncode != 0:
        return fail(f"refused: story Verify red: {verify}")
    if tier and subprocess.run(tier, shell=True).returncode != 0:
        return fail(f"refused: story test tier red: {tier}")

    # Assent is given by RUNNING land, so what it rests on must be readable HERE —
    # not only in a review leg whose stdout may be long gone.
    reviewer_work = review.reviewer_range(state.get("reviewed_head", head))
    if reviewer_work:
        print("the reviewer changed this tree — you are merging its work:")
        print(reviewer_work, end="")
        print(f"full diff: {review.diff_path(review.report_path(story_id, len(rounds)))}")

    if merge_mode == "pr":
        import shutil

        if not shutil.which("gh"):
            return fail(
                "refused: pr mode needs the gh CLI on PATH — install it or use --merge-mode local"
            )
        for c in pr_cmds:
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                return fail(f"{c[0]} failed: {r.stderr.strip()}")
    else:
        # git refuses to check out a branch held by another worktree (exit 128), and
        # that is spawn.py's DEFAULT arrangement — the lead's tree holds trunk, the
        # story lives in a worktree. Refuse with the next action rather than dying
        # on an unchecked CalledProcessError, which is what landing story-010 did.
        if (held := trunk_worktree(trunk)) and Path(held).resolve() != Path.cwd().resolve():
            return fail(
                f"refused: {trunk} is checked out at {held}, so this tree cannot merge into"
                f" it. Land from there: remove this worktree (`git worktree remove {Path.cwd()}`),"
                f" `git switch {branch}` in {held}, and re-run land"
            )
        git("checkout", trunk)
        merged = git("merge", "--no-ff", branch, "-m", message, check=False)
        if merged.returncode != 0:
            git("merge", "--abort", check=False)
            git("checkout", branch)
            return fail(
                "merge conflict: resolve on the story branch, re-review the "
                "post-resolution diff, then run review again to re-baseline"
            )

    # AFTER the merge lands: printed earlier, any refusal below would still have
    # instructed the lead to file records for a close that did not happen.
    print(render_noted(rounds), end="")

    failed = []
    orphaning = False  # only a failed amend leaves merge_sha on no ref
    if merge_mode == "pr":
        for c in pr_sync:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
        merge_sha = git("rev-parse", f"refs/remotes/origin/{trunk}").stdout.strip()
    merged_plan = Path(".xp/plan.md").read_text()  # POST-merge: keeps trunk-side changes
    Path(".xp/plan.md").write_text(_flip_status(merged_plan, story_id))
    git("add", ".xp/plan.md")
    if merge_mode == "local":
        # check=False: the amend re-runs the commit wall on a tree that just
        # gained a merge, so it CAN fail — and raising there left the merge
        # landed with the flip abandoned.
        orphaning = git("commit", "--amend", "--no-edit", "-q", check=False).returncode != 0
        if orphaning:
            failed.append("git commit --amend --no-edit  (merge landed WITHOUT the [done] flip)")
        # merge_sha AFTER the amend: the pre-amend commit is on no ref and stops
        # resolving at gc, so a record holding it points at nothing.
        merge_sha = git("rev-parse", "HEAD").stdout.strip()
        if bool(git("remote", check=False).stdout.strip()) and (
            git("push", "origin", trunk, check=False).returncode != 0
        ):
            failed.append(f"git push origin {trunk}")
    else:
        for c in pr_bookkeep:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
    failed += delete_story_branch(branch)
    if not orphaning:
        # Record unless merge_sha is about to be orphaned. Every failure EXCEPT a
        # failed amend leaves it valid and on a ref, and by here the card reads
        # [done] — withholding the record then makes the close unrecordable.
        delete_story_markers(story_id)
        log_close(story_id, card, rounds, merge_sha)
        marker.unlink()
    if failed:
        # The merge HAS landed, so this is not a refusal (2) — but exiting 0
        # would make a hand-step invisible, which M1's done-when forbids.
        print("\nincomplete — the merge landed, these did not. Re-run them:", file=sys.stderr)
        for c in failed:
            print(f"  {c}", file=sys.stderr)
        return 3
    print(
        f"{story_id} closed. Update the session digest (you are its sole writer);"
        " first line must be: # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0


def _flip_status(plan: str, story_id: str) -> str:
    out = []
    for ln in plan.splitlines(keepends=True):
        if ln.startswith(f"#### {story_id} ") and "[in-progress]" in ln:
            ln = ln.replace("[in-progress]", "[done]")
        out.append(ln)
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sp = sub.add_parser("sprint")
    sp.add_argument("sprint_id")
    sp.add_argument("action", choices=["start", "review", "land", "post-merge"])
    # no choices=[...]: sprint_close.LENSES is the one copy, and close.py cannot
    # import it at module scope — sprint_close imports from here
    sp.add_argument("--lens", default="")
    sp.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("story")
    s.add_argument("story_id")
    s.add_argument("action", choices=["review", "land"])
    # DERIVED, not chosen: pr mode is refused whenever the integration target is not
    # the default branch, and `merge-mode` appeared in no shipped prose — so the
    # documented invocation was the one that refuses.
    s.add_argument("--merge-mode", choices=["pr", "local"], default=None)
    s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    # The gate the teammate profile only DECLARES (constraints #5): a teammate
    # loaded via --plugin-dir can reach close.py through Bash, and a self-close
    # is an unreviewed merge. Any non-lead role, so an unknown role fails safe
    # and the reviewer this pipeline spawns cannot close either. It bounds the
    # /story-close path, NOT a teammate who types XP_ROLE=lead — say so rather
    # than implying a boundary the code does not have.
    role = os.environ.get("XP_ROLE", "lead")
    if role != "lead":
        return fail(
            f"refused: XP_ROLE={role!r} — only the lead may close. You hand back a green"
            " Verify; the lead owns the judgment gap and the merge"
        )
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if a.kind == "sprint":
        import sprint_close

        if a.action == "start":
            return sprint_close.cmd_start(a.sprint_id)
        if a.action == "review":
            return sprint_close.cmd_review(a.sprint_id, a.lens, a.dry_run)
        if a.action == "land":
            return sprint_close.cmd_land(a.sprint_id, a.dry_run)
        return sprint_close.cmd_post_merge(a.sprint_id)
    if a.action == "review":
        return cmd_review(a.story_id, a.dry_run)
    mode = a.merge_mode or ("local" if integration_target() != default_branch() else "pr")
    return cmd_land(a.story_id, mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
