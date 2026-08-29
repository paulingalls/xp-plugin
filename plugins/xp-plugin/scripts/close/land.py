"""The shared story land guards and bookkeeping."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import bookkeep
import close
import lifecycle as lc
import overlap
import ready
import review
import work
from release import next_version, refuse_unbumpable


def cmd_land(story_id: str, merge_mode: str, dry_run: bool, free_slug: str = "") -> int:
    if close.git("status", "--porcelain").stdout.strip():
        return close.fail("refused: working tree is dirty — Verify must judge the tree that merges")
    marker = close.marker_path(story_id)
    if not marker.exists():
        return close.fail(f"refused: no close in progress for {story_id} — run review first")
    state = json.loads(marker.read_text())
    free = bool(free_slug)
    trunk = close.default_branch() if free else close.integration_target()
    if not free and merge_mode == "pr" and trunk != close.default_branch():
        return close.fail(
            f"refused: release: sprint stories close with --merge-mode local into {trunk};"
            " the PR to trunk happens at sprint close"
        )
    head = close.git("rev-parse", "HEAD").stdout.strip()
    base = close.git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    key = f"free {free_slug}" if free else f"story {story_id}"
    if err := overlap.land_refusal(state, key, base):
        return close.fail(err)
    rounds = state["rounds"]
    ref = overlap.merge_source(trunk, merge_mode)
    files = overlap.overlapping(ref, base)
    gates = [f for f in files if f in overlap.GATE_FILES]
    blocked = files if trunk == close.default_branch() else gates
    if blocked:
        return close.fail(overlap.collision(ref, blocked))
    pending = overlap.unmerged(ref)

    held = ""
    if not free:
        held, err = bookkeep.held_trunk_tree(trunk)
        if err:
            return close.fail(err)
    minted = work.ready_marker_path(story_id).exists()
    text = work.plan_path().read_text() if work.plan_path().exists() else ""
    card, status = "", ""
    # A minted free card reached review, so losing it cannot become card-less mode.
    if not free or minted or f"#### {story_id} " in text:
        if not text:
            return close.fail(f"refused: {work.missing_plan_refusal()}")
        try:
            card, status = close.story_card(text, story_id)
        except KeyError as e:
            return close.fail(f"refused: {e.args[0]}")
    if card:
        if status != "in-progress":
            return close.fail(f"refused: {story_id} is [{status}], land requires [in-progress]")
        rerun = f"Put the heading back to [planned] and run `close.py free {free_slug} review`."
        if drift := ready.drift(story_id, card, rerun if free else ""):
            return close.fail(drift)
        try:
            raw, verify = close.verify_commands(story_id, card)
        except ValueError as e:
            return close.fail(str(e))
    else:
        raw, verify = "", []
    tier_key = "story"
    tier = work.config_block_value("tests", tier_key)
    branch = close.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    verdict = bookkeep.render_merge_body(rounds)
    version = next_version("patch", ref) if free else ""
    if free and not version:
        return refuse_unbumpable(ref)
    message = f"Merge {branch} ({story_id})\n\n{verdict}\n"
    title = f"free {free_slug} — {version}" if free else story_id
    pr_cmds = [["git", "push", "-u", "origin", branch]]
    pr_cmds.append(
        ["gh", "pr", "create"]
        + (["--base", trunk] if free else [])
        + ["--title", title, "--body", verdict]
    )
    if not free:
        pr_cmds.append(["gh", "pr", "merge", "--merge", "--delete-branch", "--body", verdict])
    pr_sync = [
        ["git", "fetch", "-q", "origin"],
        ["git", "checkout", "-q", trunk],
        ["git", "merge", "--ff-only", f"origin/{trunk}"],
    ]
    pr_bookkeep = [["git", "push", "origin", trunk]]
    pr_steps = (pr_cmds, pr_sync, pr_bookkeep)
    if dry_run:
        if free:
            for command in pr_cmds:
                print(" ".join(command))
            print(f"(first the story tier; then `close.py free {free_slug} post-merge`)")
            return 0
        print(
            bookkeep.render_land_preview(raw, tier, merge_mode, branch, trunk, pr_steps, pending),
            end="",
        )
        return 0
    if red := overlap.gates(ref, verify, tier_key, pending):
        return close.fail(red)
    if not free and (red := lc.run(close.config_flat(lc.KEY), "story-close", story_id)):
        return close.fail(red)

    review.disclose(state, head, review.diff_path(review.report_path(story_id, len(rounds))))
    if free:
        if not shutil.which("gh"):
            return close.fail(
                "refused: free land opens a PR — install the gh CLI, or open it by hand"
            )
        for command in pr_cmds:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                return close.fail(f"{command[0]} failed: {result.stderr.strip()}")
        print(bookkeep.render_noted(rounds), end="")
        print(
            f"PR open against {trunk} for {version}. After it merges:"
            f" `close.py free {free_slug} post-merge`"
        )
        return 0

    story_tree = str(Path.cwd())
    if merge_mode == "pr":
        if not shutil.which("gh"):
            return close.fail(
                "refused: pr mode needs the gh CLI on PATH — install it or use --merge-mode local"
            )
        for c in pr_cmds:
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                return close.fail(f"{c[0]} failed: {r.stderr.strip()}")
        if held:
            os.chdir(held)
    else:
        os.chdir(held) if held else close.git("checkout", trunk)
        merged = close.git("merge", "--no-ff", branch, "-m", message, check=False)
        if merged.returncode != 0:
            close.git("merge", "--abort", check=False)
            close.git("checkout", branch)
            return close.fail(
                "merge conflict: resolve on the story branch, re-review the "
                "post-resolution diff, then run review again to re-baseline"
            )

    print(bookkeep.render_noted(rounds), end="")
    failed = []
    if files and (err := overlap.report_merge(story_id, files)):
        failed.append(err)
    if merge_mode == "pr":
        for c in pr_sync:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
        merge_sha = close.git("rev-parse", f"refs/remotes/origin/{trunk}").stdout.strip()
    if not work.flip_card(story_id, "in-progress", "done"):
        failed.append(f"flip {story_id} to [done] in {work.plan_path()}")
    if merge_mode == "local":
        merge_sha = close.git("rev-parse", "HEAD").stdout.strip()
        if bool(close.git("remote", check=False).stdout.strip()) and (
            close.git("push", "origin", trunk, check=False).returncode != 0
        ):
            failed.append(f"git push origin {trunk}")
    else:
        for c in pr_bookkeep:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
    failed += bookkeep.remove_story_checkout(
        story_tree if held else "", branch, close.config_flat("teardown_timeout")
    )
    bookkeep.delete_story_markers(story_id)
    bookkeep.log_close(story_id, card, rounds, merge_sha)
    marker.unlink()
    if bookkeep.report_incomplete(failed):
        return 3
    print(
        f"{story_id} closed. REPLACE the session digest (you are its sole writer);"
        " first line must be: # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0
