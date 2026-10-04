"""A sprint: review its slate, open its branch, review its diff by angle, land it, tag it."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xpcore import bundle, cards, gitx, hooks, launch, release
from xpcore.config import (
    clear_sprint_branch,
    data_root,
    fail,
    plugin_root,
    record_sprint_branch,
    refuse,
    repo_root,
    sprint_branch_name,
    trunk,
)
from xpcore.land import pull_request


def sprint_dir(sprint_id) -> Path:
    return data_root() / "sprints" / (str(sprint_id).lstrip("0") or "0")


def on_branch(branch: str, root: Path) -> None:
    current = gitx.current_branch(root)
    if current != branch:
        refuse(f"{root} is on {current or 'a detached HEAD'}, not {branch}; `git switch {branch}`")
    if gitx.is_dirty(root):
        refuse(f"{root} has uncommitted changes; commit or discard them, then run again")


def agent(role: str, text: str, root: Path, log_id: str, out: Path) -> Path:
    """The agent may write `out` itself; if it did not, its final answer is the file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = launch.run_agent(role, text, root, log_id)
    if result.returncode:
        fail(f"{role} exited {result.returncode}; read {launch.log_path(log_id)}")
    if not out.is_file():
        out.write_text(result.stdout.rstrip() + "\n")
    return out


def cmd_sprint_plan(args) -> int:
    slate, root = cards.sprint_slate(args.id), repo_root()
    out = sprint_dir(args.id) / "slate-review.md"
    if args.dry_run:
        print(f"would run the plan reviewer over Sprint {args.id}'s slate into {out}")
        return 0
    out.unlink(missing_ok=True)
    text = bundle.prompt(
        "plan-reviewer",
        card=slate,
        extra="Review this sprint slate as a whole: the cards together, not one card.",
        paths={"FINDINGS_PATH": str(out)},
    )
    agent("plan-reviewer", text, root, f"{sprint_branch_name(args.id)}-plan-reviewer", out)
    print(out.read_text(), end="")
    cut = f"git switch -c {sprint_branch_name(args.id)} {trunk()}"
    print(f"slate review: {out}. Correct the slate, then `{cut}`")
    return 0


def cmd_sprint_open(args) -> int:
    branch, root, main = sprint_branch_name(args.id), repo_root(), trunk()
    cards.sprint_slate(args.id)
    on_branch(branch, root)
    tip = gitx.git("rev-parse", main, cwd=root)
    if gitx.fork_point(branch, main, root) != tip:
        refuse(f"{branch} is not cut from {main}'s head; `git rebase {main}` it, then open")
    if args.dry_run:
        print(f"would record {branch} as the open sprint branch")
        return 0
    record_sprint_branch(branch)
    print(f"Sprint {args.id} open on {branch}; spawn its stories with `xp.py story <id>`")
    return 0


def next_round(folder: Path) -> int:
    rounds = [int(p.name.split(".")[0][7:]) for p in folder.glob("review-*.*.md")]
    return max(rounds, default=0) + 1


def cmd_sprint_review(args) -> int:
    branch, root, main = sprint_branch_name(args.id), repo_root(), trunk()
    on_branch(branch, root)
    angles = sorted((plugin_root() / "angles").glob("*.md"))
    if not angles:
        refuse(f"no angle files in {plugin_root() / 'angles'}; reinstall the plugin")
    diff, log = gitx.diff_range(main, "HEAD", root), gitx.log_range(main, "HEAD", root)
    if not diff:
        refuse(f"{branch} has no changes since {main}; land stories on it first")
    folder = sprint_dir(args.id)
    n = next_round(folder)
    outs = {a: folder / f"review-{n}.{a.stem}.md" for a in angles}
    if args.dry_run:
        print(f"would review {main}..{branch} by {', '.join(a.stem for a in angles)}, then fix")
        return 0
    slate = cards.sprint_slate(args.id)

    def review(angle: Path) -> Path:
        extra = f"Commits:\n{log}\n\nDiff {main}..{branch}:\n{diff}"
        out = {"FINDINGS_PATH": str(outs[angle])}
        text = bundle.prompt(
            "reviewer", card=slate, angle=angle.read_text(), extra=extra, paths=out
        )
        return agent("reviewer", text, root, f"{branch}-reviewer-{n}-{angle.stem}", outs[angle])

    with ThreadPoolExecutor(max_workers=len(angles)) as pool:
        try:
            written = list(pool.map(review, angles))
        except BaseException:
            launch.kill_live()
            raise
    findings = "\n\n".join(f"## {p.name}\n\n{p.read_text()}" for p in written)
    extra = f"You are on {branch} at {root}. Fix what these findings warrant and commit."
    handback, log_id = folder / f"handback-{n}.md", f"{branch}-executor-{n}"
    paths = {"HANDBACK_PATH": str(handback)}
    text = bundle.prompt("executor", card=slate, findings=findings, extra=extra, paths=paths)
    result = launch.run_agent("executor", text, root, log_id)
    for path in written:
        body = [ln for ln in path.read_text().splitlines() if ln.strip()]
        print(f"{path}: {len(body)} lines; {body[0] if body else 'empty'}")
    print(f"handback: {handback}{'' if handback.is_file() else ' (not written)'}")
    if result.returncode:
        print(f"failed: the executor exited {result.returncode}; read {launch.log_path(log_id)}")
        return 1
    print(f"executor done; judge what it left open, then `xp.py sprint land {args.id}`")
    return 0


def green_hook(root: Path, log_id: str) -> None:
    if rc := hooks.run_sprint_hook(root, log_id):
        refuse(f"the sprint hook exited {rc}; read {hooks.log_path(log_id)}, fix, run again")


def trial_hook(root: Path, main: str, log_id: str) -> str:
    """The sprint hook on trunk merged in; returns the tree it tested."""
    try:
        if conflict := gitx.trial_merge(root, main):
            refuse(f"{main} does not merge cleanly:\n{conflict}\nmerge {main} in, resolve, land")
        tree = gitx.git("write-tree", cwd=root)
        green_hook(root, log_id)
    finally:
        gitx.abort_merge(root)
    return tree


def no_open_cards(sprint_id) -> None:
    slate = cards.read_cards(cards.sprint_slate(sprint_id))
    if open_cards := [c.id for c in slate if c.status == "in-progress"]:
        refuse(f"{', '.join(open_cards)} still in-progress; land or retire them, then run again")


def cmd_sprint_land(args) -> int:
    branch, root, main = sprint_branch_name(args.id), repo_root(), trunk()
    on_branch(branch, root)
    no_open_cards(args.id)
    version = release.version_wall("minor")
    hooks.sprint_hook(root)
    if args.dry_run:
        print(f"would trial-merge {main}, run the sprint hook, push {branch}, open a PR")
        return 0
    tree = trial_hook(root, main, f"{branch}-sprint-hook")
    land_json = sprint_dir(args.id) / "land.json"
    land_json.parent.mkdir(parents=True, exist_ok=True)
    land_json.write_text(json.dumps({"tested_tree": tree, "version": version}) + "\n")
    name = f"Release v{version}" if version else f"Sprint {args.id}"
    after = f"{name} is ready; after it merges, pull {main} and run"
    reviews = sorted(p.name for p in sprint_dir(args.id).glob("review-*.md"))
    body = f"{name}.\n\nReviews:\n" + "".join(f"- {r}\n" for r in reviews)
    after += f" `xp.py sprint post-merge {args.id}`"
    pull_request(branch, main, root, after, title=f"Sprint {args.id}", body=body)
    return 0


def merged(branch: str, root: Path, main: str) -> None:
    how = gitx.merged_how(branch, "HEAD", root) if gitx.branch_exists(branch, root) else ""
    if not how:
        refuse(
            f"{branch} is not merged into {main}; if the PR was squash- or rebase-merged, its"
            f" commits are not on {main}; this plugin supports that but prefers merge commits."
            f" Merge its PR, pull {main}, run again"
        )
    if how == "squash":
        print(f"{branch} was squash-merged; merge commits are preferred, so history shows it")


def cmd_sprint_post_merge(args) -> int:
    branch, root, main = sprint_branch_name(args.id), repo_root(), trunk()
    on_branch(main, root)
    merged(branch, root, main)
    no_open_cards(args.id)
    land_json = sprint_dir(args.id) / "land.json"
    if not land_json.is_file():
        refuse(f"no {land_json}; run `xp.py sprint land {args.id}` first")
    tested = json.loads(land_json.read_text())["tested_tree"]
    # A rerun after the tag: the hook passed and the wall held before it was made.
    tagged = release.tag_at_head(root) if release.versioning() else ""
    version = tagged.removeprefix("v") or release.version_wall("minor")
    changed = not tagged and gitx.git("rev-parse", "HEAD^{tree}", cwd=root) != tested
    if args.dry_run:
        rerun = "rerun the sprint hook, " if changed else ""
        make = f"tag v{version}, " if version and not tagged else ""
        print(f"would {rerun}{make}write release.json, delete {branch}")
        return 0
    if tagged:
        print(f"{tagged} already marks {main}'s head; finishing its release")
    elif changed:
        print(f"{main}'s tree differs from what land tested; running the sprint hook")
        green_hook(root, f"{branch}-sprint-hook")
    else:
        print("the merged tree is the one land tested; the sprint hook does not rerun")
    if version and not tagged:
        release.tag(version)
    if not (sprint_dir(args.id) / "release.json").is_file():
        release.write_release_record(sprint_dir(args.id).name, version, gitx.head(root))
    clear_sprint_branch()
    gitx.git("branch", "-D", branch, cwd=root)
    print(f"Sprint {args.id} released{release.tag_note(version)}")
    return 0
