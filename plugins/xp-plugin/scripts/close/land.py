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
import verify_receipt
import work
from release import (
    VERSIONING_OFF_TEXT,
    next_version,
    refuse_unbumpable,
    trunk_version_refusal,
    version_files,
    version_only_paths,
    version_refusal,
    versioning_mode,
)
from repair import land_red_path
from review_artifacts import story_sidecars
from review_scope import declared_files
from timing import Span


def cmd_land(story_id: str, merge_mode: str, dry_run: bool) -> int:
    if close.git("status", "--porcelain").stdout.strip():
        return close.fail("refused: working tree is dirty — Verify must judge the tree that merges")
    marker = close.marker_path(story_id)
    launch_paths = [review.launch_marker(story_id), *story_sidecars(story_id)]
    for launch in (path for path in launch_paths if path.exists()):
        # Distinct states stay distinct: salvage refuses when this file is
        # unreadable, and land reading the same file may not answer it with
        # "no unrecorded review".
        try:
            unrecorded = json.loads(launch.read_text())
            verify_red = unrecorded.get("verify_red", "")
        except (OSError, ValueError, AttributeError) as e:
            return close.fail(
                f"refused: {launch} is not readable ({e}) — it is the only record of a"
                " review no round covers, so land cannot tell a completed round whose"
                " Verify redded from a review that never ran. Delete it and review again"
            )
        if verify_red:
            covered = False
            if launch != launch_paths[0] and marker.exists():
                state = json.loads(marker.read_text())
                verify_head = unrecorded.get("verify_head", unrecorded.get("head", ""))
                shown_sha = state.get("shown_sha", "")
                covered = (
                    bool(verify_head and shown_sha)
                    and not close.git(
                        "merge-base", "--is-ancestor", verify_head, shown_sha, check=False
                    ).returncode
                )
            if covered:
                continue
            verified = str(unrecorded.get("verify_head", unrecorded.get("head", "")))[:8]
            next_action = (
                f"fix it, then run `close.py {close.leg(story_id)[0]} repair`"
                if launch == launch_paths[0]
                else f"run `close.py {close.leg(story_id)[0]} salvage`, or review again"
            )
            return close.fail(
                f"refused: the review completed on tree {verified}, but {verify_red}."
                " THAT round is not recorded — any earlier one still is, and does not"
                f" cover this tree; {next_action}"
            )
    # launch_paths, not the sidecars alone: the CANONICAL marker is what a review
    # that never recorded leaves behind, and salvage reads it first.
    if queued := [path for path in launch_paths if path.exists()]:
        noun = close.leg(story_id)[0]
        return close.fail(
            f"refused: {len(queued)} unrecorded review round(s) are set aside at"
            f" {', '.join(str(p) for p in queued)} — `close.py {noun} salvage` records"
            " them. If salvage refuses because the"
            " recorded tree or marker moved, inspect the saved report and patch,"
            " explicitly accept that the round cannot enter the ledger, remove only"
            f" the named launch marker(s), then retry `close.py {noun} land`"
        )
    if not marker.exists():
        return close.fail(f"refused: no close in progress for {story_id} — run review first")
    state = json.loads(marker.read_text())
    noun, free_slug = close.leg(story_id)
    free = bool(free_slug)
    trunk = close.default_branch() if free else close.integration_target()
    if not free and merge_mode == "pr" and trunk != close.default_branch():
        return close.fail(
            f"refused: release: sprint stories close with --merge-mode local into {trunk};"
            " the PR to trunk happens at sprint close"
        )
    head = close.git("rev-parse", "HEAD").stdout.strip()
    base = close.git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    ref = overlap.merge_source(trunk, merge_mode)
    versioned = False
    version = ""
    names = []
    refusal = ""
    if free:
        versioned, refusal = versioning_mode()
        if versioned:
            version = next_version("patch", ref)
            names = version_files()
    candidates = set(names) - {"none"} if free and versioned else set()
    recorded = state.get("review_base")
    prior_exempt = set()
    if candidates and isinstance(recorded, str) and recorded != base:
        prior_exempt = version_only_paths(recorded, base, candidates) & version_only_paths(
            base, head, candidates
        )
    if err := overlap.land_refusal(state, noun, base, prior_exempt):
        return close.fail(err)
    if refusal:
        return close.fail(refusal)
    if free and versioned and not version:
        return refuse_unbumpable(ref)
    rounds = state["rounds"]
    if (
        free
        and versioned
        and names
        and names != ["none"]
        and (
            refusal := trunk_version_refusal(ref, version, names) or version_refusal(version, names)
        )
    ):
        return close.fail(refusal)
    fork_exempt = (
        version_only_paths(base, ref, candidates) & version_only_paths(base, head, candidates)
        if candidates
        else set()
    )
    files = overlap.overlapping(ref, base, fork_exempt)
    gate_hits = [f for f in files if f in overlap.GATE_FILES]
    blocked = files if trunk == close.default_branch() else gate_hits
    if blocked:
        return close.fail(overlap.collision(ref, blocked))
    pending = overlap.unmerged(ref)

    held = ""
    if not free:
        held, err = bookkeep.held_trunk_tree(trunk)
        if err:
            return close.fail(err)
    if not work.plan_path().exists():
        return close.fail(f"refused: {work.missing_plan_refusal()}")
    try:
        card, status = close.story_card(work.plan_path().read_text(), story_id)
    except KeyError as e:
        return close.fail(f"refused: {e.args[0]}")
    if status != "in-progress":
        return close.fail(f"refused: {story_id} is [{status}], land requires [in-progress]")
    if drift := ready.drift(story_id, card):
        return close.fail(drift)
    amended = json.loads(work.ready_marker_path(story_id).read_text()).get("amendments", [])
    for i, change in enumerate(amended):
        after = amended[i + 1]["card"] if i + 1 < len(amended) else card
        print(f"card amended — reason: {change['reason']}")
        print(ready.card_diff(change["card"], after))
    try:
        raw, verify = close.verify_commands(story_id, card)
        verify_receipt.reads(card)
    except ValueError as e:
        return close.fail(str(e))
    tier_key = "story"
    tier = work.config_block_value("tests", tier_key)
    branch = close.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    changed = set(
        close.git(
            "-c", "core.quotepath=off", "diff", "--no-renames", "--name-only", f"{base}..HEAD"
        ).stdout.splitlines()
    )
    try:
        declared = declared_files(card)
    except ValueError as e:
        return close.fail(str(e))
    exempt = set(names) if free and versioned else set()
    exempt.discard("none")
    beyond_map = sorted(changed - declared - exempt)
    protected = [path for path in beyond_map if path.startswith(".xp/")]
    files_beyond_map = [path for path in beyond_map if not path.startswith(".xp/")]
    if protected:
        paths = "\n".join(f"  {path}" for path in protected)
        return close.fail(
            f"refused: {story_id} changes `.xp/` paths its Files declaration does not"
            f" name:\n{paths}\nThese are the project's own artifacts, the one class land"
            f" still fences. Add them to Files. {ready.AMEND.format(story_id)}"
        )
    verdict = bookkeep.render_merge_body(rounds, story_id, files_beyond_map)
    message = f"Merge {branch} ({story_id})\n\n{verdict}\n"
    title = (f"{noun} — {version}" if version else noun) if free else story_id
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
        # A preview of a land that refuses is the refusal: listing steps it will
        # never take is the same lie in the other direction.
        if refusal := overlap.tier_refusal(tier, tier_key):
            return close.fail(refusal)
        if files_beyond_map:
            print("beyond the card's Files map — the merge body will name:")
            print("".join(f"  {path}\n" for path in files_beyond_map), end="")
        if free:
            print(f"would run: {tier}")
            for command in pr_cmds:
                print(" ".join(command))
            print(f"(then `close.py {noun} post-merge`)")
            if not versioned:
                print(VERSIONING_OFF_TEXT)
            return 0
        print(
            bookkeep.render_land_preview(raw, tier, merge_mode, branch, trunk, pr_steps, pending),
            end="",
        )
        return 0
    span = Span(work.data_root(), "story-land-gates", f"{story_id}: trial merge, Verify and tier")
    land_red = land_red_path(story_id)

    def record_red(kind: str, red: str) -> str:
        try:
            land_red.write_text(
                json.dumps(
                    {
                        "head": head,
                        "kind": kind,
                        "red": red,
                        "round_index": len(rounds),
                        "digest": review.marker_digest(marker),
                        "card": card,
                    }
                )
            )
        except OSError as exc:
            return f"refused: could not record land red at {land_red}: {exc} — run land again"
        return f"{red} — fix it, commit, then run `close.py {noun} repair`"

    try:
        red, _receipt = overlap.gates(
            ref,
            verify,
            tier_key,
            pending,
            measured_red=record_red,
            story_verify=lambda tree: verify_receipt.decide(story_id, card, raw, verify, tree),
        )
    except BaseException:
        span.finish("interrupted")
        raise
    span.finish("failed" if red else "passed")
    if red:
        return close.fail(red)
    if not free and (red := lc.run(close.config_flat(lc.KEY), "story-close", story_id)):
        return close.fail(red)

    review.disclose(state, head, lambda n: review.diff_path(review.report_path(story_id, n)))
    if free:
        if not shutil.which("gh"):
            return close.fail(
                "refused: free land opens a PR — install the gh CLI, or open it by hand"
            )
        for command in pr_cmds:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                return bookkeep.refuse_command(command, result)
        land_red.unlink(missing_ok=True)
        print(bookkeep.render_noted(rounds), end="")
        target = f" for {version}" if version else ""
        print(f"PR open against {trunk}{target}. After it merges: `close.py {noun} post-merge`")
        if not versioned:
            print(VERSIONING_OFF_TEXT)
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
                return bookkeep.refuse_command(c, r)
        if held:
            os.chdir(held)
    else:
        if held:
            os.chdir(held)
        elif (left := close.git("checkout", trunk, check=False)).returncode:
            return close.fail(
                f"cannot check out {trunk} to merge into: {left.stderr.strip()}"
                " — clear that, then run land again"
            )
        before_merge = close.git("rev-parse", "HEAD").stdout.strip()
        merged = close.git("merge", "--no-ff", branch, "-m", message, check=False)
        if merged.returncode != 0:
            unmerged = close.git("diff", "--name-only", "--diff-filter=U", check=False)
            close.git("merge", "--abort", check=False)
            if not held:
                close.git("checkout", branch, check=False)
            if unmerged.returncode == 0 and unmerged.stdout.strip():
                return close.fail(
                    "merge conflict: resolve on the story branch, re-review the "
                    "post-resolution diff, then run review again to re-baseline"
                )
            why = (merged.stderr or merged.stdout).strip()
            return close.fail(
                f"merge failed: {why}\nclear that, then run land again — nothing"
                " merged and HEAD did not move, so the recorded review still covers"
                " this tree"
            )

    print(bookkeep.render_noted(rounds), end="")
    failed = []
    dependencies = []
    retry = ""
    if files:
        overlap.report_merge(story_id, files)
    if merge_mode == "pr":
        for c in pr_sync:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
        merge_sha = close.git("rev-parse", f"refs/remotes/origin/{trunk}").stdout.strip()
    if not work.flip_card(story_id, "in-progress", "done"):
        failed.append(f"flip {story_id} to [done] in {work.plan_path()}")
    if merge_mode == "local":
        merge_sha = close.git("rev-parse", "HEAD").stdout.strip()
        if bool(close.git("remote", check=False).stdout.strip()):
            # The cause, not just the command: this is the only step here that
            # reaches the network, and a transient nobody can name (bug 07ee145d,
            # story-101's land) is one nobody can fix.
            pushed = close.git("push", "origin", trunk, check=False)
            if pushed.returncode != 0:
                why = (pushed.stderr or pushed.stdout).strip().replace("\n", " ")
                failed.append(f"git push origin {trunk} — {why[-300:]}")
                changed_by_merge = close.git(
                    "-c",
                    "core.quotepath=off",
                    "diff",
                    "--no-renames",
                    "--name-only",
                    before_merge,
                    "HEAD",
                ).stdout.splitlines()
                dependencies = bookkeep.dependency_paths(changed_by_merge)
                retry = f"git push origin {trunk}"
    else:
        for c in pr_bookkeep:
            if subprocess.run(c, capture_output=True, text=True).returncode != 0:
                failed.append(" ".join(c))
    failed += bookkeep.remove_story_checkout(
        story_tree if held else "", branch, close.config_flat("teardown_timeout")
    )
    bookkeep.delete_story_markers(story_id)
    bookkeep.log_close(story_id, card, rounds, merge_sha, files_beyond_map)
    marker.unlink()
    land_red.unlink(missing_ok=True)
    verify_receipt.path(story_id).unlink(missing_ok=True)
    if bookkeep.report_incomplete(failed, dependencies, str(Path.cwd()), retry):
        return 3
    print(
        f"{story_id} closed. REPLACE the session digest (you are its sole writer);"
        " first line must be: # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0
