#!/usr/bin/env python3
"""Story-close pipeline: mechanical steps scripted, judgment left to the lead.

Two invocations, one judgment gap between them:
  close.py story <id> review -> preflight, spawn the story-reviewer, record its
                                VERDICT line, print its findings
  (the lead reads them and decides fix-or-ask — the one LLM-present moment the
   pipeline must not absorb, constraints.md #7)
  close.py story <id> land   -> Verify, merge under the recorded verdict, push,
                                delete the story branch, log the close

The verdict is PIPELINE-RECEIVED: there is no --verdict flag, because a
lead-supplied verdict is forgeable, and Sprint 1 forged one.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import chdir_repo_root, data_root


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


def story_tier_command() -> str:
    """The `tests: story:` command from .xp/config.yml (stdlib line-parse, no yaml dep)."""
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    in_tests = False
    for ln in cfg.read_text().splitlines():
        if ln.rstrip() == "tests:":
            in_tests = True
        elif in_tests and ln.strip().startswith("story:"):
            return ln.split("story:", 1)[1].split("#")[0].strip()
        elif in_tests and ln and not ln.startswith(" "):
            in_tests = False
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


def work_entries_since(branch_point_epoch: int) -> str:
    """work.md entries whose header timestamp postdates the branch point."""
    from datetime import datetime, timezone

    path = data_root() / "work.md"
    if not path.exists():
        return ""
    out, keep = [], False
    for ln in path.read_text().splitlines():
        if ln.startswith("## "):
            ts = ln.rsplit(" ", 1)[1]
            try:
                epoch = (
                    datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                keep = epoch >= branch_point_epoch
            except ValueError:
                keep = False
        if keep:
            out.append(ln)
    return "\n".join(out)


def build_bundle(card: str, base: str) -> str:
    import review  # function-local: spawn -> close -> review would close a cycle

    base_epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    sections = [
        ("Your charter", review.charter()),
        ("Story card", card),
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


def cmd_review(story_id: str, dry_run: bool = False, delta: bool = False) -> int:
    import review

    card, trunk, err = _preflight(story_id, "review")
    if err:
        return fail(err)
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if delta and marker.exists() else {}
    # HEAD is read BEFORE the launch. Read after, a reviewer that commits (it runs
    # under bypass) has its own commit recorded as reviewed_sha, and land then
    # merges unreviewed code under a verdict that never saw it.
    head = git("rev-parse", "HEAD").stdout.strip()
    base = (
        state["reviewed_sha"]
        if delta
        else git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    )
    result, err = review.run(build_bundle(card, base), Path.cwd(), dry_run)
    if dry_run:
        return 0
    if err:
        return fail(f"refused: {err}")
    dirtied = git("status", "--porcelain").stdout.strip()
    if git("rev-parse", "HEAD").stdout.strip() != head or dirtied:
        return fail(
            "refused: the reviewer moved HEAD or dirtied the working tree — it reviews,"
            " it does not write. Nothing was recorded; inspect the tree, then re-run review"
        )
    print(result)
    verdict = review.extract_verdict(result)
    if not verdict:
        print("WARNING: the reviewer emitted no VERDICT line — land will refuse", file=sys.stderr)
    state["reviewed_sha"] = head
    if delta:
        # ONLY the sha and the verdict. Rewriting trunk_sha here would silently
        # clear the guard against a trunk that moved during the review window —
        # the delta diff is on the story branch and covers no trunk motion.
        state["verdicts"] = state.get("verdicts", []) + ([verdict] if verdict else [])
    else:
        state["verdicts"] = [verdict] if verdict else []
        state["trunk_sha"] = git("rev-parse", f"refs/heads/{trunk}").stdout.strip()
        state["origin_trunk_sha"] = origin_trunk_sha(trunk)
    marker.write_text(json.dumps(state))
    return 0


def _read_first(*candidates: str) -> str:
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p.read_text()
    return f"(missing: {candidates[0]})"


def _delete_story_markers(story_id: str) -> None:
    """Clear the story's test-status markers rather than writing a green into
    them: those files are session-scoped gate state, and a green close.py never
    measured is close.py forging another session's measurement (DESIGN §4,
    constraints #6). The [done] flip is what honestly releases the Stop gate;
    this only stops dead files accumulating."""
    for path in (data_root() / "markers").glob(f"*.{story_id}.test-status"):
        path.unlink(missing_ok=True)


def _log_close(story_id: str, card: str, verdicts: list[str], merge_sha: str) -> None:
    """APPEND one line per close. A single overwritten file would be the
    project-global mutable marker constraints #10 calls a design error; a log is
    not, it survives two closes in one sprint, and the retro gets the history."""
    from datetime import datetime, timezone

    record = {
        "story": story_id,
        "title": card.splitlines()[0].split("— ", 1)[-1].split(" [")[0].strip(),
        "verdicts": verdicts,
        "merge_sha": merge_sha,
        "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (data_root() / "closes.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def _finish_branch(branch: str, trunk: str) -> list[str]:
    """Push the integration branch, then delete the story branch LOCAL FIRST.

    Order is load-bearing and was measured at story-007 close: `git branch -d`
    checks the branch against its UPSTREAM ref, so deleting origin first forces a
    -D, which discards the only check that the work is actually merged.

    Returns the commands that failed, for the caller to surface.
    """
    failed = []
    has_remote = bool(git("remote", check=False).stdout.strip())
    if has_remote and git("push", "origin", trunk, check=False).returncode != 0:
        failed.append(f"git push origin {trunk}")
    # only when origin actually carries the branch: a story closed with
    # --in-place never pushed one, and a spurious failure here reads as a defect
    origin_has_branch = (
        git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", check=False).returncode
        == 0
    )
    if git("branch", "-d", branch, check=False).returncode != 0:
        failed.append(f"git branch -d {branch}")
    elif origin_has_branch and git("push", "origin", "--delete", branch, check=False).returncode:
        failed.append(f"git push origin --delete {branch}")
    return failed


def cmd_land(story_id: str, merge_mode: str, dry_run: bool) -> int:
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
    if not state.get("verdicts"):
        return fail(
            "refused: no VERDICT line was recorded — no verdict, no merge."
            " Re-run review; if the reviewer keeps emitting none, that is the finding"
        )
    head = git("rev-parse", "HEAD").stdout.strip()
    if head != state["reviewed_sha"]:
        print(f"drift: HEAD moved since review — reviewing {state['reviewed_sha'][:8]}..{head[:8]}")
        rc = cmd_review(story_id, delta=True)
        if rc != 0:
            return rc
        return fail(
            "refused: the delta above was reviewed in-pipeline and recorded."
            " Read the findings, then run land again"
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
    tier = story_tier_command()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    verdict = "\n".join(f"Review round {i}: {v}" for i, v in enumerate(state["verdicts"], 1))
    message = f"Merge {branch} ({story_id})\n\n{verdict}\n"
    pr_cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", f"{story_id}", "--body", verdict],
        ["gh", "pr", "merge", "--merge", "--delete-branch", "--body", verdict],
        ["git", "push"],  # plan-flip bookkeeping commit
    ]
    if dry_run:  # pure preview: nothing runs, nothing changes, marker survives
        print(f"would run: {verify}")
        if tier:
            print(f"would run: {tier}")
        if merge_mode == "pr":
            for c in pr_cmds:
                print(" ".join(c))
        else:
            print(f"git merge --no-ff {branch} on {trunk}, then flip status + amend")
        return 0
    if subprocess.run(verify, shell=True).returncode != 0:
        return fail(f"refused: story Verify red: {verify}")
    if tier and subprocess.run(tier, shell=True).returncode != 0:
        return fail(f"refused: story test tier red: {tier}")

    if merge_mode == "pr":
        import shutil

        if not shutil.which("gh"):
            return fail(
                "refused: pr mode needs the gh CLI on PATH — install it or use --merge-mode local"
            )
        for c in pr_cmds[:-1]:
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                return fail(f"{c[0]} failed: {r.stderr.strip()}")
    else:
        git("checkout", trunk)
        merged = git("merge", "--no-ff", branch, "-m", message, check=False)
        if merged.returncode != 0:
            git("merge", "--abort", check=False)
            git("checkout", branch)
            return fail(
                "merge conflict: resolve on the story branch, re-review the "
                "post-resolution diff, then run review again to re-baseline"
            )

    merged_plan = Path(".xp/plan.md").read_text()  # POST-merge: keeps trunk-side changes
    Path(".xp/plan.md").write_text(_flip_status(merged_plan, story_id))
    git("add", ".xp/plan.md")
    failed = []
    if merge_mode == "local":
        git("commit", "--amend", "--no-edit", "-q")  # plan flip rides the merge commit
        # merge_sha AFTER the amend: the pre-amend commit is on no ref and stops
        # resolving at gc, so a record holding it points at nothing.
        merge_sha = git("rev-parse", "HEAD").stdout.strip()
        failed = _finish_branch(branch, trunk)
    else:
        committed = git("commit", "-qm", f"{story_id} done", check=False)
        pushed = git("push", check=False)  # remote trunk must learn [done]
        merge_sha = git("rev-parse", "HEAD").stdout.strip()
        if committed.returncode != 0 or pushed.returncode != 0:
            failed.append("git commit + push .xp/plan.md")
    _delete_story_markers(story_id)
    _log_close(story_id, card, state["verdicts"], merge_sha)
    marker.unlink()
    print(
        f"{story_id} closed. Update the session digest (you are its sole writer);"
        " first line must be: # Session digest — written <ISO-ts> at <short-sha>"
    )
    if failed:
        # the merge HAS landed, so this is not a refusal (2) — but exiting 0
        # would make a hand-step invisible, which is what M1's done-when forbids
        print("\nincomplete — the merge landed, these did not. Re-run them:", file=sys.stderr)
        for c in failed:
            print(f"  {c}", file=sys.stderr)
        return 3
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
    s = sub.add_parser("story")
    s.add_argument("story_id")
    s.add_argument("action", choices=["review", "land"])
    s.add_argument("--merge-mode", choices=["pr", "local"], default="pr")
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
    if a.action == "review":
        return cmd_review(a.story_id, a.dry_run)
    return cmd_land(a.story_id, a.merge_mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
