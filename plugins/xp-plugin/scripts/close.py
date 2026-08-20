#!/usr/bin/env python3
"""Story-close pipeline: mechanical steps scripted, judgment left to the lead.

Two invocations, one judgment gap between them:
  close.py story <id> start     -> preflight, emit the review bundle
  (lead spawns the story-reviewer, fixes or files findings)
  close.py story <id> reviewed --verdict "VERDICT: ..." -> Verify, merge, bookkeep

Gates here are advisory lane-keeping (constraints.md #5); the hard property
(reviewer spawned by the pipeline itself) arrives with the Sprint-2 spawn CLI.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import data_root


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


def cmd_start(story_id: str) -> int:
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — commit or stash first")
    plan = Path(".xp/plan.md").read_text()
    try:
        card, status = story_card(plan, story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if status != "in-progress":
        return fail(f"refused: {story_id} is [{status}], start requires [in-progress]")
    trunk = integration_target()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in (trunk, default_branch()):
        return fail(
            f"refused: close from a story branch, not {branch} — a self-merge is a no-op"
            " that records the verdict nowhere"
        )
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    diff = git("diff", f"{base}..HEAD").stdout
    base_epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    sections = [
        ("Story card", card),
        ("Cumulative diff", diff),
        ("work.md entries filed during the story", work_entries_since(base_epoch) or "none"),
        ("VALUES", _read_first("VALUES.md", "plugins/xp-plugin/VALUES.md")),
        ("Constraints", _read_first(".xp/constraints.md")),
        ("System context", _read_first(".xp/system.md")),
    ]
    print("# Review bundle — hand to the story-reviewer\n")
    for title, body in sections:
        print(f"## {title}\n\n{body}\n")
    marker_path(story_id).write_text(
        json.dumps(
            {
                "reviewed_sha": git("rev-parse", "HEAD").stdout.strip(),
                "trunk_sha": git("rev-parse", f"refs/heads/{trunk}").stdout.strip(),
                "origin_trunk_sha": origin_trunk_sha(trunk),
            }
        )
    )
    return 0


def _read_first(*candidates: str) -> str:
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p.read_text()
    return f"(missing: {candidates[0]})"


def cmd_reviewed(story_id: str, verdict: str, merge_mode: str, dry_run: bool) -> int:
    if not verdict.strip():
        return fail("refused: --verdict text is required — a gate that clears must record content")
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — Verify must judge the tree that merges")
    marker = marker_path(story_id)
    if not marker.exists():
        return fail(f"refused: no close in progress for {story_id} — run start first")
    state = json.loads(marker.read_text())
    trunk = integration_target()
    if merge_mode == "pr" and trunk != default_branch():
        return fail(
            f"refused: release: sprint stories close with --merge-mode local into {trunk};"
            " the PR to main happens at sprint close"
        )
    head = git("rev-parse", "HEAD").stdout.strip()
    if head != state["reviewed_sha"]:
        print(git("diff", f"{state['reviewed_sha']}..HEAD").stdout)
        return fail(
            "drift: HEAD moved since review — delta above goes back to the reviewer,"
            " then run start again to re-baseline"
        )
    moved = (
        origin_trunk_sha(trunk) != state.get("origin_trunk_sha")
        if merge_mode == "pr"
        else git("rev-parse", f"refs/heads/{trunk}").stdout.strip() != state.get("trunk_sha")
    )
    if moved:
        return fail(
            f"refused: {trunk} moved since start — the merged tree would differ from"
            " what was reviewed; run start again to re-baseline"
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
                "post-resolution diff, then run start again to re-baseline"
            )

    merged_plan = Path(".xp/plan.md").read_text()  # POST-merge: keeps trunk-side changes
    Path(".xp/plan.md").write_text(_flip_status(merged_plan, story_id))
    git("add", ".xp/plan.md")
    if merge_mode == "local":
        git("commit", "--amend", "--no-edit", "-q")  # plan flip rides the merge commit
    else:
        committed = git("commit", "-qm", f"{story_id} done", check=False)
        pushed = git("push", check=False)  # remote trunk must learn [done]
        if committed.returncode != 0 or pushed.returncode != 0:
            print(
                "plan-flip bookkeeping incomplete — commit/push .xp/plan.md manually",
                file=sys.stderr,
            )
    marker.unlink()
    print(f"{story_id} closed. Update the session digest (you are its sole writer).")
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
    s.add_argument("action", choices=["start", "reviewed"])
    s.add_argument("--verdict", default=None)
    s.add_argument("--merge-mode", choices=["pr", "local"], default="pr")
    s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.action == "start":
        return cmd_start(a.story_id)
    return cmd_reviewed(a.story_id, a.verdict or "", a.merge_mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
