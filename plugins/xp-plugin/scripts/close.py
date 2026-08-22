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
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bookkeep import (
    delete_story_branch,
    delete_story_markers,
    held_trunk_tree,
    log_close,
    remove_story_worktree,
    render_land_preview,
    render_merge_body,
    render_noted,
    render_prior_rounds,
)
from work import (
    chdir_repo_root,
    config_block_value,
    data_root,
    edit_plan,
    plan_path,
    stale_plan,
    work_entries_since,
)


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
        raise KeyError(f"{story_id} not found in the plan")
    rest = range(start + 1, len(lines))
    end = next((i for i in rest if lines[i].startswith(("# ", "## ", "### ", "#### "))), len(lines))
    card = "".join(lines[start:end])
    if "[" not in lines[start]:
        raise KeyError(f"{story_id} header has no [status] bracket in the plan")
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
        ("PROCESS", _read_first(str(review.PLUGIN_ROOT / "PROCESS.md"))),
        ("VALUES", _read_first(str(Path(__file__).parent.parent / "VALUES.md"))),
        ("Constraints", _read_first(".xp/constraints.md")),
        ("System context", _read_first(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _preflight(story_id: str, action: str) -> tuple[str, str, str]:
    """(card, trunk, error) — the checks both legs share."""
    if git("status", "--porcelain").stdout.strip():
        return "", "", "refused: working tree is dirty — commit or stash first"
    if not plan_path().exists():
        why = stale_plan() or f"no plan at {plan_path()} — is this an xp-managed repo?"
        return "", "", f"refused: {why}"
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return "", "", f"refused: {e.args[0]}"
    if status != "in-progress":
        return "", "", f"refused: {story_id} is [{status}], {action} requires [in-progress]"
    try:  # 3e2ad94b: an annotated Verify line reached /bin/sh at LAND, post-review
        shlex.split(verify_commands(card))
    except ValueError as e:
        return "", "", f"refused: {story_id}'s Verify: line is not runnable ({e})"
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
    motion = review.check_reviewer_motion(head, marker, digest_before, card, story_id)
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

    sys.path.insert(0, str(Path(__file__).parent / "close"))
    import overlap

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
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    if state.get("review_base") != base:
        return fail(
            f"refused: the recorded round did not cover this tree — it was based on"
            f" {str(state.get('review_base'))[:8]}, today's merge base is {base[:8]}."
            f" Run `close.py story {story_id} review`"
        )
    shown = state.get("shown_sha", head)
    if git("merge-base", "--is-ancestor", shown, "HEAD", check=False).returncode:
        return fail(
            f"refused: HEAD does not contain {shown[:8]}, the tree you were shown —"
            " the reviewer's commits are not in what would merge, so the recorded"
            f" round describes no tree. Run `close.py story {story_id} review`"
        )
    rounds = state["rounds"]
    blocking = rounds[-1]["blocking"]
    if blocking:
        return fail(
            "refused: the last review round left blocking findings:\n  "
            + "\n  ".join(blocking)
            + "\nFix them (or review again once fixed) — a flag cannot clear these"
        )
    ref = overlap.merge_source(trunk, merge_mode)
    if files := overlap.overlapping(ref, base):
        return fail(overlap.collision(ref, files))
    pending = overlap.unmerged(ref)

    # Structural, and checked HERE rather than beside the merge (5d7388fc): it is a
    # `git worktree list` compare, so paying ~2min of Verify and tier to reach it was
    # pure waste. spawn.py's DEFAULT puts trunk in the lead's tree and the story in a
    # worktree, so `held` is the normal case, not the exception.
    held, err = held_trunk_tree(trunk)
    if err:
        return fail(err)
    if not plan_path().exists():
        return fail(f"refused: {stale_plan() or f'no plan at {plan_path()}'}")
    plan = plan_path().read_text()
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
    # the push stays: pr_sync's --ff-only is a no-op when local trunk is AHEAD,
    # so without it a lead's trunk commits never reach origin
    pr_bookkeep = [["git", "push", "origin", trunk]]
    pr_steps = (pr_cmds, pr_sync, pr_bookkeep)
    if dry_run:  # pure preview: nothing runs, nothing changes, marker survives
        print(
            render_land_preview(verify, tier, merge_mode, branch, trunk, pr_steps, pending),
            end="",
        )
        return 0
    if red := overlap.gates(ref, verify, tier, pending):
        return fail(red)

    # Assent is given by RUNNING land, so what it rests on must be readable HERE —
    # not only in a review leg whose stdout may be long gone.
    reviewer_work = review.reviewer_range(state.get("reviewed_head", head), shown)
    if reviewer_work:
        print("the reviewer changed this tree — you are merging its work:")
        print(reviewer_work, end="")
        print(f"full diff: {review.diff_path(review.report_path(story_id, len(rounds)))}")
    lead_work = review.reviewer_range(shown, head)
    if lead_work:
        print("you committed after the review you were shown — merging unreviewed:")
        print(lead_work, end="")

    # `gh pr create|merge` take no --head: gh reads the head branch off the cwd
    # repo, so it must run in the STORY tree. The chdir happens per-arm below,
    # after gh and before pr_sync — the first step that needs trunk checked out.
    story_tree = str(Path.cwd())
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
        if held:
            os.chdir(held)
    else:
        os.chdir(held) if held else git("checkout", trunk)
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
    if merge_mode == "pr":
        for c in pr_sync:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
        merge_sha = git("rev-parse", f"refs/remotes/origin/{trunk}").stdout.strip()
    # locked: a sibling lane may be flipping its own card right now
    edit_plan(lambda text: _flip_status(text, story_id))
    if merge_mode == "local":
        merge_sha = git("rev-parse", "HEAD").stdout.strip()
        if bool(git("remote", check=False).stdout.strip()) and (
            git("push", "origin", trunk, check=False).returncode != 0
        ):
            failed.append(f"git push origin {trunk}")
    else:
        for c in pr_bookkeep:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
    if held:
        failed += remove_story_worktree(story_tree)
    failed += delete_story_branch(branch)
    # merge_sha is the merge commit, always on a ref now that no amend rewrites it
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
