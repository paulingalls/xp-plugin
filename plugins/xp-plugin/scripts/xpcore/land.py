"""Land a story on its sprint branch, or a free patch on trunk through a PR."""

import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from xpcore import cards, gitx, hooks, release
from xpcore.config import data_root, refuse, sprint_branch, trunk


def is_ancestor(ref: str, cwd) -> bool:
    argv = ["git", "merge-base", "--is-ancestor", ref, "HEAD"]
    return subprocess.run(argv, cwd=cwd, capture_output=True).returncode == 0


def lead_tree() -> Path:
    """The main worktree, wherever this runs from: it is the tree that holds the target."""
    first = gitx.git("worktree", "list", "--porcelain").splitlines()[0]
    return Path(first.removeprefix("worktree "))


def free_id(slug: str) -> str:
    return slug if slug.startswith("free-") else f"free-{slug}"


def worktree_of(card: cards.Card) -> tuple[Path, str]:
    path = data_root() / "worktrees" / card.id
    if not path.is_dir():
        refuse(f"no worktree at {path}; run `xp.py story {card.id}` (or free) to create it")
    branch = gitx.current_branch(path)
    if not branch:
        refuse(f"{path} is on a detached HEAD; switch it back to the story branch")
    return path, branch


def review_names(card_id: str) -> list[Path]:
    found = (data_root() / "stories" / card_id).glob("review-*.md")
    return sorted(found, key=lambda p: (len(p.stem), p.stem))


def merge_body(card: cards.Card, branch: str, base: str, cwd) -> str:
    reviews = review_names(card.id)
    lines = [f"{card.id}: {card.title}", ""]
    lines += [f"- {p.name}" for p in reviews] or ["- no review files"]
    since = max((p.stat().st_mtime for p in reviews), default=0.0)
    commits = gitx.git("log", "--reverse", "--format=%H %ct", f"{base}..{branch}", cwd=cwd)
    late = [sha for sha, ct in (c.split() for c in commits.splitlines()) if int(ct) > since]
    if late:
        tip = gitx.git("rev-parse", branch, cwd=cwd)
        lines += ["", f"unreviewed: {late[0][:10]}^..{tip[:10]}"]
    return "\n".join(lines) + "\n"


def warn_overlap(branch: str, target: str, cwd) -> None:
    base = gitx.fork_point(branch, target, cwd)
    both = set(gitx.changed_files(base, branch, cwd)) & set(gitx.changed_files(base, target, cwd))
    if both:
        print(f"warning: {target} also changed {', '.join(sorted(both))} since the fork")


def accept(card: cards.Card, path: Path, branch: str, target: str) -> None:
    commands = hooks.split_commands(card.acceptance)
    try:
        if conflict := gitx.trial_merge(path, target):
            refuse(
                f"{target} does not merge cleanly into {branch}:\n{conflict}\nmerge {target}"
                f" into {branch} in {path}, resolve, review again, then land"
            )
        rc = hooks.run_acceptance(commands, path, f"{card.id}-acceptance")
    finally:
        gitx.abort_merge(path)
    if rc:
        log = hooks.log_path(f"{card.id}-acceptance")
        refuse(
            f"Acceptance exited {rc} on {branch} merged with {target}; read {log},"
            " fix it on the story branch, then land again"
        )


def close(card: cards.Card, merge: str, path: Path, branch: str, lead: Path) -> None:
    cards.set_status(card.id, "done")
    date = datetime.now(timezone.utc).date().isoformat()
    with open(data_root() / "closes.jsonl", "a") as out:
        out.write(json.dumps({"id": card.id, "title": card.title, "merge": merge, "date": date}))
        out.write("\n")
    # The worktree before the branch: git will not delete a branch a worktree has out.
    gitx.worktree_remove(path, cwd=lead)
    gitx.git("branch", "-D", branch, cwd=lead)


def land(card_id: str, target: str, *, pr: bool, dry_run: bool) -> int:
    card = cards.find_card(card_id)
    if card.status != "in-progress":
        refuse(f"{card.id} is [{card.status}], not [in-progress]; only spawned work lands")
    path, branch = worktree_of(card)
    if gitx.is_dirty(path):
        refuse(f"{path} has uncommitted changes; commit or discard them, then land")
    if not target or not gitx.branch_exists(target, path):
        refuse(f"target branch {target or '(none)'} does not exist; open the sprint first")
    if not card.acceptance:
        refuse(f"{card.id} has no Acceptance: line; add the command that proves its ACs")
    lead = lead_tree()
    if not pr and (gitx.current_branch(lead) != target or gitx.is_dirty(lead)):
        refuse(f"{lead} must be on {target} and clean to merge into; switch or commit there")
    warn_overlap(branch, target, path)
    base = gitx.fork_point(branch, target, path)
    if dry_run:
        how = f"push {branch} and open a PR to {target}" if pr else f"merge into {target}"
        print(f"would trial-merge {target} into {branch}, run `{card.acceptance}`, then {how}")
        return 0
    accept(card, path, branch, target)
    if pr:
        after = f"after it merges, pull {target} and run `xp.py free post-merge {card.id}`"
        return pull_request(branch, target, path, after)
    body = merge_body(card, branch, base, lead)
    try:
        gitx.git("merge", "--no-ff", branch, "-m", body, cwd=lead)
    except gitx.GitError:
        gitx.abort_merge(lead)  # the target moved since the trial; leave its tree as found
        raise
    close(card, gitx.head(lead), path, branch, lead)
    print(f"{card.id} landed on {target}:\n{body}", end="")
    return 0


def pull_request(branch: str, target: str, cwd, after: str) -> int:
    gitx.git("push", "-u", "origin", branch, cwd=cwd)
    argv = ["gh", "pr", "create", "--base", target, "--head", branch, "--fill"]
    if not shutil.which("gh"):
        print(f"gh is not on PATH; open the PR by hand: {shlex.join(argv)}\n{after}")
        return 0
    if rc := subprocess.run(argv, cwd=cwd).returncode:
        print(f"gh exited {rc}; open the PR by hand, then {after}")
        return 1
    print(after)
    return 0


def cmd_story_land(args) -> int:
    return land(args.id, sprint_branch(), pr=False, dry_run=args.dry_run)


def cmd_free_land(args) -> int:
    return land(free_id(args.id), trunk(), pr=True, dry_run=args.dry_run)


def cmd_free_post_merge(args) -> int:
    card = cards.find_card(free_id(args.id))
    if card.status != "in-progress":
        refuse(f"{card.id} is [{card.status}], not [in-progress]; it was closed already")
    path, branch = worktree_of(card)
    if gitx.is_dirty(path):
        refuse(f"{path} has uncommitted changes; commit or discard them, then run again")
    lead, main = lead_tree(), trunk()
    if gitx.current_branch(lead) != main or gitx.is_dirty(lead):
        refuse(f"{lead} must be on {main} and clean; switch to {main} and pull")
    if not is_ancestor(branch, lead):
        refuse(f"{branch} is not merged into {main}; merge its PR, pull {main}, run again")
    version = release.version_wall("patch")
    if args.dry_run:
        print(f"would tag v{version}, close {card.id}, remove {path} and {branch}")
        return 0
    release.tag(version)
    close(card, gitx.head(lead), path, branch, lead)
    print(f"{card.id} closed; tagged v{version}. Push the tag: git push origin v{version}")
    return 0
