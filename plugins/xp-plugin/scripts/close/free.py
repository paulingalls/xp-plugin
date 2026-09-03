"""A carded free branch and its distinct patch-release boundaries."""

import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "spawn"))
import bookkeep
import spawn
from close import config_flat, default_branch, fail, git, leg, marker_path, story_card
from work import data_root, flip_card, plan_path, ready_marker_path, slugify, user_ns

FREE = re.compile(r"[^/]+/free-(\d{4}-\d\d-\d\d-(.+))")


def branch_for(slug: str) -> str:
    return f"{user_ns()}/free-{datetime.date.today().isoformat()}-{slugify(slug)}"


def card_in_plan(key: str) -> bool:
    return plan_path().exists() and f"#### {key} " in plan_path().read_text()


def current_free(slug: str) -> tuple[str, str, str]:
    """(marker key, branch, refusal), read off HEAD rather than recomputed from
    today's date — a branch cut yesterday still lands today."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    m = FREE.fullmatch(branch)
    if not m or m.group(2) != slugify(slug):
        return (
            "",
            branch,
            (
                f"refused: on {branch}, which is not a free branch for {slug!r} — run this"
                f" from the branch `free start` cut, e.g. {branch_for(slug)}"
            ),
        )
    return f"free-{m.group(1)}", branch, ""


def cmd_start(slug: str) -> int:
    normalized = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    if slugify(slug) != normalized:
        return fail(
            f"refused: free slugs are limited to 20 characters — this would cut"
            f" branch {branch_for(slug)}; choose a shorter slug"
        )
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — commit or stash first")
    trunk = default_branch()
    if (branch := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) != trunk:
        return fail(
            f"refused: free start cuts off {trunk}, and you are on {branch} — a free"
            f" branch cut anywhere else carries that branch's unreleased work into a"
            f" patch release. `git checkout {trunk}` first"
        )
    new = branch_for(slug)
    if git("rev-parse", "--verify", "-q", f"refs/heads/{new}", check=False).returncode == 0:
        return fail(f"refused: branch {new} already exists")
    if (made := git("checkout", "-q", "-b", new, trunk, check=False)).returncode:
        return fail(f"git checkout -b failed: {made.stderr.strip()}")
    key = new.split("/", 1)[1]
    card = "card in the plan" if card_in_plan(key) else "card required, add it"
    print(
        f"{new} off {trunk} — {card}. Cut your release artifacts, then "
        f"`spawn.py ready {key}` before `close.py {leg(key)[0]} review`"
    )
    return 0


def cmd_review(slug: str, dry_run: bool) -> int:
    import close
    import ready

    key, _branch, err = current_free(slug)
    if err:
        return fail(err)
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — commit or stash first")
    if not card_in_plan(key):
        noun = leg(key)[0]
        return fail(
            f"refused: add `#### {key} — <title>   [planned]` with Context, Files, AC,"
            f" and Verify to {plan_path()}, then run `close.py {noun} review`"
        )
    if not dry_run:
        try:
            _card, status = story_card(plan_path().read_text(), key)
        except KeyError as e:  # the heading above is hand-written; a typo'd one is a refusal
            return fail(f"refused: {e.args[0]}")
        # the free lane is exempt from card refresh BY LANE, not by key shape: this
        # card was authored and reviewed on a branch cut minutes ago and never aged
        if status == "planned" and ready.mint(key, require_refresh=False):
            return 2
        if status in ("planned", "ready") and not flip_card(key, "ready", "in-progress"):
            return fail(f"refused: could not move {key} to [in-progress]")
    return close.cmd_review(key, dry_run)


def cmd_salvage(slug: str) -> int:
    import close

    key, _branch, err = current_free(slug)
    return fail(err) if err else close.cmd_salvage(key)


def cmd_land(slug: str, dry_run: bool) -> int:
    import close

    key, _branch, err = current_free(slug)
    return fail(err) if err else close.cmd_land(key, "pr", dry_run)


def cmd_post_merge(slug: str) -> int:
    import release

    pattern = f"free-????-??-??-{slugify(slug)}.close.json"
    matches = list((data_root() / "markers").glob(pattern))
    if len(matches) != 1:
        return fail(
            f"refused: expected one reviewed free release for {slug!r}, found {len(matches)}"
        )
    key = matches[0].name.removesuffix(".close.json")
    try:
        card, status = story_card(plan_path().read_text(), key)
    except (KeyError, OSError) as exc:
        return fail(f"refused: {key} not found in {plan_path()}: {exc}")
    if status != "in-progress":
        return fail(f"refused: {key} is [{status}], post-merge requires [in-progress]")
    if refusal := spawn.ready().drift(key, card):
        return fail(refusal)
    state = json.loads(matches[0].read_text())
    branch = str(state.get("branch", ""))
    result = release.cmd_post_merge(key, branch, "patch", False)
    if result:
        return result
    tree, spawned_branch, failed = bookkeep.story_worktree(spawn.worktree_path(key))
    if not flip_card(key, "in-progress", "done"):
        failed.append(f"flip {key} to [done] in {plan_path()}")
    failed += bookkeep.remove_story_checkout(tree, spawned_branch, config_flat("teardown_timeout"))
    failed += bookkeep.delete_story_branch(branch)
    bookkeep.delete_story_markers(key)
    ready_marker_path(key).unlink(missing_ok=True)
    marker_path(key).unlink(missing_ok=True)
    if bookkeep.report_incomplete(failed):
        return 3
    return 0
