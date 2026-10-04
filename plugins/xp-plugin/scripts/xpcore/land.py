"""Land a story on its sprint branch, or a free patch on trunk through a PR."""

import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from xpcore import cards, gitx, hooks, release
from xpcore.config import data_root, fail, refuse, sprint_branch, trunk
from xpcore.story import card_changes, last_reviewed, reviews, story_dir, worktree


def lead_tree() -> Path:
    """The main worktree, wherever this runs from: it is the tree that holds the target."""
    first = gitx.git("worktree", "list", "--porcelain").splitlines()[0]
    return Path(first.removeprefix("worktree "))


def free_id(slug: str) -> str:
    return slug if slug.startswith("free-") else f"free-{slug}"


def worktree_of(card: cards.Card) -> tuple[Path, str]:
    path = worktree(card.id)
    if not path.is_dir():
        refuse(f"no worktree at {path}; run `xp.py story {card.id}` (or free) to create it")
    branch = gitx.current_branch(path)
    if not branch:
        refuse(f"{path} is on a detached HEAD; switch it back to the story branch")
    return path, branch


def merge_body(card: cards.Card, branch: str, base: str, cwd) -> str:
    sdir = story_dir(card.id)
    lines = [f"{card.id}: {card.title}", ""]
    lines += [f"- {p.name}" for _, p in reviews(sdir)] or ["- no review files"]
    if card_changes(card):
        lines.append("- card changed since spawn")
    seen = last_reviewed(sdir)
    since = seen if seen and gitx.ref_exists(seen, cwd) else base
    if gitx.git("rev-list", branch, f"^{base}", f"^{since}", cwd=cwd):
        tip = gitx.git("rev-parse", branch, cwd=cwd)
        lines += ["", f"unreviewed: {since[:10]}..{tip[:10]}"]
    return "\n".join(lines) + "\n"


def merged_by(branch: str, target: str, cwd) -> str:
    """The merge on `target` whose later parent is `branch`'s tip, or "". Not mere ancestry:
    a branch with no commits is an ancestor of its target too."""
    tip = gitx.git("rev-parse", branch, cwd=cwd)
    merges = gitx.git("rev-list", "--merges", "--parents", f"{tip}..{target}", cwd=cwd)
    return next((m[0] for m in map(str.split, merges.splitlines()) if tip in m[2:]), "")


def warn_overlap(branch: str, target: str, cwd) -> None:
    base = gitx.fork_point(branch, target, cwd)
    both = set(gitx.changed_files(base, branch, cwd)) & set(gitx.changed_files(base, target, cwd))
    if both:
        print(f"warning: {target} also changed {', '.join(sorted(both))} since the fork")


def acceptance(card: cards.Card, cwd: Path, log_id: str, where: str, then: str) -> None:
    if rc := hooks.run_acceptance(card.acceptance, cwd, log_id):
        refuse(f"Acceptance exited {rc} on {where}; read {hooks.log_path(log_id)}, {then}")


def accept(card: cards.Card, path: Path, branch: str, target: str, sha: str) -> None:
    """Acceptance on `branch` with `sha`, the target's tip as land found it, merged in."""
    try:
        if conflict := gitx.trial_merge(path, sha):
            refuse(
                f"{target} does not merge cleanly into {branch}:\n{conflict}\nmerge {target}"
                f" into {branch} in {path}, resolve, review again, then land"
            )
        where, then = f"{branch} merged with {target}", "fix it on the branch, then land again"
        acceptance(card, path, f"{card.id}-acceptance", where, then)
    finally:
        gitx.abort_merge(path)


def fetched_trunk(target: str, path: Path) -> str:
    """The ref a PR will merge into: origin's trunk, fetched now, or the local one."""
    if "origin" not in gitx.git("remote", cwd=path).split():
        print(f"no remote named origin; trial-merging the local {target}")
        return target
    gitx.git("fetch", "origin", target, cwd=path)
    return f"origin/{target}"


def recorded_close(card_id: str) -> str:
    """The merge landed.jsonl recorded for `card_id`, or "": a close that got that far and
    then failed to flip the card has no worktree left for a rerun to find. Not closes.jsonl:
    0.x wrote that name in the same data root, in another shape."""
    path = data_root() / "landed.jsonl"
    lines = path.read_text().splitlines() if path.is_file() else []
    return next((r["merge"] for r in map(json.loads, lines) if r["id"] == card_id), "")


def finish_recorded(card: cards.Card) -> int:
    cards.set_status(card.id, "done")
    print(f"finished a previous land of {card.id}: it was recorded as closed; marked done")
    return 0


def close(card: cards.Card, merge: str, path: Path, branch: str, lead: Path) -> None:
    # The worktree before the branch: git will not delete a branch a worktree has out.
    gitx.worktree_remove(path, cwd=lead)
    gitx.git("branch", "-D", branch, cwd=lead)
    date = datetime.now(timezone.utc).date().isoformat()
    with open(data_root() / "landed.jsonl", "a") as out:
        out.write(json.dumps({"id": card.id, "title": card.title, "merge": merge, "date": date}))
        out.write("\n")
    # Last, so a close that failed above leaves the card in progress and a rerun finishes it.
    cards.set_status(card.id, "done")


def land(card_id: str, target: str, *, pr: bool, dry_run: bool) -> int:
    card = cards.find_card(card_id)
    if card.status != "in-progress":
        refuse(f"{card.id} is [{card.status}], not [in-progress]; only spawned work lands")
    if recorded_close(card.id):
        return finish_recorded(card)
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
    into = fetched_trunk(target, path) if pr and not dry_run else target
    base = gitx.fork_point(branch, into, path)
    if gitx.head(path) == base:
        if not pr and (merge := merged_by(branch, target, lead)):
            return finish(card, merge, path, branch, lead, dry_run)
        again = f"free {card.id.removeprefix('free-')}" if pr else f"story {card.id}"
        refuse(f"{card.id} has no commits on {branch}; run xp.py {again}")
    if pr:
        release.version_wall("patch", path)
    warn_overlap(branch, into, path)
    if dry_run:
        how = f"push {branch} and open a PR to {target}" if pr else f"merge into {target}"
        print(f"would trial-merge {into} into {branch}, run `{card.acceptance}`, then {how}")
        return 0
    sha = gitx.git("rev-parse", into, cwd=path)
    accept(card, path, branch, into, sha)
    body = merge_body(card, branch, base, lead)
    if diff := card_changes(card):
        print(f"{card.id}: card changed since spawn:\n{diff}")
    if pr:
        after = f"after it merges, pull {target} and run `xp.py free post-merge {card.id}`"
        return pull_request(branch, target, path, after, title=card.title, body=body)
    if gitx.git("rev-parse", target, cwd=lead) != sha:
        refuse(f"{target} moved during land; run xp.py story land {card.id} again")
    try:
        gitx.git("merge", "--no-ff", branch, "-m", body, cwd=lead)
    except gitx.GitError as exc:
        gitx.abort_merge(lead)  # a merge hook said no; leave the target's tree as found
        fail(f"{exc}; {target} is as it was, fix that and run xp.py story land {card.id} again")
    close(card, gitx.head(lead), path, branch, lead)
    print(f"{card.id} landed on {target}:\n{body}", end="")
    return 0


def finish(card: cards.Card, merge: str, path: Path, branch: str, lead: Path, dry: bool) -> int:
    if dry:
        print(f"would finish a previous land of {card.id}: close it after merge {merge[:10]}")
        return 0
    close(card, merge, path, branch, lead)
    print(f"finished a previous land of {card.id}: merge {merge[:10]} was in; closed it")
    return 0


def pull_request(branch: str, target: str, cwd, after: str, *, title=None, body=None) -> int:
    if "origin" not in gitx.git("remote", cwd=cwd).split():
        print(f"no remote named origin; push {branch}, open the PR to {target} by hand, {after}")
        return 0
    gitx.git("push", "-u", "origin", branch, cwd=cwd)
    argv = ["gh", "pr", "create", "--base", target, "--head", branch]
    argv += ["--fill"] if title is None else ["--title", title, "--body", body or ""]
    if not shutil.which("gh"):
        print(f"gh is not on PATH; open the PR by hand: {shlex.join(argv)}\n{after}")
        return 0
    if rc := subprocess.run(argv, cwd=cwd).returncode:
        fail(f"gh exited {rc}; {branch} is pushed, so open the PR by hand, then {after}")
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
    if recorded_close(card.id):
        return finish_recorded(card)
    path, branch = worktree_of(card)
    if gitx.is_dirty(path):
        refuse(f"{path} has uncommitted changes; commit or discard them, then run again")
    lead, main = lead_tree(), trunk()
    if gitx.current_branch(lead) != main or gitx.is_dirty(lead):
        refuse(f"{lead} must be on {main} and clean; switch to {main} and pull")
    how = gitx.merged_how(branch, "HEAD", lead)
    if not how:
        refuse(
            f"{branch} is not merged into {main}; merge its PR, pull {main}, run again; if the"
            f" PR was squash- or rebase-merged, its commits are not on {main}; this plugin"
            " supports that but prefers merge commits"
        )
    if how == "squash":
        print(f"{card.id} was squash-merged; its history is not on {main}; prefer merge commits")
    # A rerun after the tag but before close finished: the tag is this release's.
    tagged = release.tag_at_head(lead, release.tree_version(lead)) if release.versioning() else ""
    version = tagged.removeprefix("v") if tagged else release.version_wall("patch")
    if args.dry_run:
        make = f"tag v{version}, " if version and not tagged else ""
        print(f"would run `{card.acceptance}` on {main}, {make}close {card.id}")
        return 0
    where = f"{main} at {gitx.head(lead)[:10]}"
    then = f"commit the fix on {branch}, merge it to {main}, then run xp.py free post-merge"
    acceptance(card, lead, f"{card.id}-post-merge", where, f"{then} {args.id} again")
    if version and not tagged:
        release.tag(version)
    close(card, gitx.head(lead), path, branch, lead)
    print(f"{card.id} closed{release.tag_note(version)}")
    return 0
