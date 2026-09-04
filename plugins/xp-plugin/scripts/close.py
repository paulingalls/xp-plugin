#!/usr/bin/env python3
"""Story review records judgment; story land runs gates and moves refs without spawning."""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
from bookkeep import render_prior_rounds
from env import sprint_branch
from lifecycle import declared_commands as verify_commands
from work import (
    chdir_repo_root,
    data_root,
    missing_plan_refusal,
    plan_path,
    strip_comment,
    work_entries_since,
)

FREE_ID = re.compile(r"free-(\d{4}-\d\d-\d\d-(.+))")


def unrecorded_notice(paths: list[Path], salvage: str) -> str:
    """What a relaunched review is about to unlink, for every noun. A round's
    artifacts exist at the CURRENT round only when a review ran and recorded none —
    salvage's own precondition — so issue #44's suggested recovery, review again,
    deletes exactly what salvage would have recorded. A notice and not a refusal: a
    reviewer that died before writing a usable report leaves the same artifacts and
    salvage cannot record those either, so refusing would deadlock the pair.
    """
    if not (left := [str(p) for p in paths if p.exists()]):
        return ""
    return (
        f"an unrecorded review left {', '.join(left)}, which this run DELETES —"
        f" `{salvage}` records it instead"
    )


def sprint_unrecorded_notice(sprint_id: str, round_n: int) -> str:
    """The sprint noun's stage keys are not known until the legs run, so it looks by
    round rather than by name — the same round salvage globs for."""
    stale = f"{glob.escape(sprint_id)}.*.round-{round_n}.*"
    doomed = (data_root() / "reports" / "sprint").glob(stale)
    return unrecorded_notice(sorted(doomed), f"close.py sprint {sprint_id} salvage")


def fail(msg: str) -> "int":
    print(msg, file=sys.stderr)
    return 2


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def salvage_dirty_refusal() -> str:
    dirty = git("status", "--porcelain").stdout.strip()
    if not dirty:
        return ""
    return (
        "the working tree may contain a dead reviewer's uninspected work; read it"
        " before committing or discarding it, then retry salvage with a clean tree;"
        " uncommitted:\n  " + dirty
    )


def story_card(plan: str, story_id: str) -> tuple[str, str]:
    lines = plan.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"#### {story_id} ")), None)
    if start is None:
        raise KeyError(f"{story_id} not found in the plan")
    if any(ln.startswith(f"#### {story_id} ") for ln in lines[start + 1 :]):
        raise KeyError(
            f"{story_id} appears more than once in the plan — readers pick the first"
            " card and the status flip rewrites the last, so delete or rename one"
        )
    rest = range(start + 1, len(lines))
    end = next((i for i in rest if lines[i].startswith(("# ", "## ", "### ", "#### "))), len(lines))
    card = "".join(lines[start:end])
    if "[" not in lines[start]:
        raise KeyError(f"{story_id} header has no [status] bracket in the plan")
    status = lines[start].rsplit("[", 1)[1].rstrip().rstrip("]")
    return card, status


def leg(story_id: str) -> tuple[str, str]:
    free = FREE_ID.fullmatch(story_id)
    return (f"free {free.group(2)}", free.group(2)) if free else (f"story {story_id}", "")


def config_flat(key: str) -> str:
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    for ln in cfg.read_text().splitlines():
        if ln.startswith(f"{key}:"):
            return strip_comment(ln).split(":", 1)[1].strip()
    return ""


def config_has(key: str) -> bool:
    cfg = Path(".xp/config.yml")
    return cfg.exists() and any(ln.startswith(f"{key}:") for ln in cfg.read_text().splitlines())


def integration_target() -> str:
    if config_flat("release") == "sprint":
        if config_has("sprint_branch"):
            raise SystemExit(
                fail(
                    "refused: remove sprint_branch: from .xp/config.yml, THEN record"
                    " this clone's branch with `close.py sprint <id> start` — without"
                    " that record every story merge falls back to the default branch"
                )
            )
        branch = sprint_branch()
        if branch:
            ok = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
            if ok.returncode != 0:
                print(
                    f"recorded sprint branch refs/heads/{branch} does not exist —"
                    " refusing to fall back to the default branch (a fresh clone must"
                    " open its sprint, not silently merge to trunk)",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            return branch
    return default_branch()


def default_branch() -> str:
    """`trunk:` overrides git's default; a missing configured branch never falls back."""
    if name := config_flat("trunk"):
        if git("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode:
            raise SystemExit(
                fail(
                    f"refused: trunk: {name} in .xp/config.yml, but refs/heads/{name}"
                    f" does not exist — create it, or drop the key to release to git's default"
                )
            )
        return name
    head = git("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    if head.returncode == 0:
        return head.stdout.strip().rsplit("/", 1)[1]
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode == 0:
            return name
    raise SystemExit(fail("no main/master branch found and origin/HEAD unset"))


def origin_trunk_sha(trunk: str) -> str | None:
    """Fetch the PR-mode ref; local mode guards the local trunk instead."""
    if not git("remote", check=False).stdout.strip():
        return None
    git("fetch", "-q", "origin", trunk, check=False)
    r = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{trunk}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def marker_path(story_id: str) -> Path:
    p = data_root() / "markers" / f"{story_id}.close.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def build_bundle(card: str, base: str, report: Path, prior: str = "", notice: str = "") -> str:
    import review  # function-local: spawn -> close -> review would close a cycle

    base_epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    sections = [
        ("Your charter", review.charter()),
        ("Your report", f"REPORT_PATH: {report}\nPATCH_PATH: {review.patch_path(report)}"),
        ("Story card", card),
        *([("Before you start", notice)] if notice else []),
        ("Earlier rounds of THIS review", prior or "none — you are round 1"),
        ("Cumulative diff", git("diff", f"{base}..HEAD").stdout),
        ("work.md entries filed during the story", work_entries_since(base_epoch) or "none"),
        ("JUDGMENT", _read(str(review.PLUGIN_ROOT / "JUDGMENT.md"))),
        ("VALUES", _read(str(Path(__file__).parent.parent / "VALUES.md"))),
        ("Constraints", _read(".xp/constraints.md")),
        ("System context", _read(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _preflight(story_id: str, action: str, dry_run: bool = False) -> tuple[str, str, str]:
    if action != "salvage" and git("status", "--porcelain").stdout.strip():
        return "", "", "refused: working tree is dirty — commit or stash first"
    _noun, free_slug = leg(story_id)
    card, trunk = "", default_branch() if free_slug else integration_target()
    if not plan_path().exists():
        return "", "", f"refused: {missing_plan_refusal()}"
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return "", "", f"refused: {e.args[0]}"
    # Only a PREVIEW: free.cmd_review mints and flips before every real review, so a
    # live one arriving here [planned] came in under the story noun, and reviewing it
    # spends a round on a card nothing committed to.
    previewable = dry_run and free_slug and action == "review" and status in ("planned", "ready")
    if status != "in-progress" and not previewable:
        return "", "", f"refused: {story_id} is [{status}], {action} requires [in-progress]"
    try:
        verify_commands(story_id, card)
    except ValueError as e:
        return "", "", str(e)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in (trunk, default_branch()):
        return (
            "",
            "",
            f"refused: close from a story branch, not {branch} — a self-merge is a no-op"
            " that records the verdict nowhere",
        )
    return card, trunk, ""


def verify_on_reviewed_tree(story_id: str, card: str) -> str:
    """Run Verify on the reviewed diff; land separately protects the merged tree."""
    import overlap  # a cycle at module level: it imports close

    red = overlap.run_checks(verify_commands(story_id, card)[1], None, " on the reviewed tree")
    return red.removeprefix("refused: ")


def _record_round(
    story_id: str, card: str, path: Path, marker: Path, state: dict, at: dict, salvage=False
) -> int:
    """Share review and salvage guards; `at` is the tree the launch marker names."""
    import review

    head = at["head"]
    report, err = review.read_report(path) if salvage else ({}, "")
    if err:
        return fail(review.stamp(path, review.abort_text(head, err, salvage=salvage)))
    motion = review.check_reviewer_motion(
        head, marker, at["digest"], card, story_id, at.get("moved", ""), salvage=salvage
    )
    if motion:
        return fail(review.stamp(path, motion))
    if not salvage:
        report, err = review.read_report(path)
        if err:
            return fail(review.stamp(path, review.abort_text(head, err)))
    if err := review.apply_patch(path, card):
        return fail(review.stamp(path, review.abort_text(head, err, salvage=salvage)))
    verify_err = verify_on_reviewed_tree(story_id, card)
    if verify_err and not report["blocking"]:
        at.update(verify_red=verify_err, verify_head=git("rev-parse", "HEAD").stdout.strip())
        review.launch_marker(story_id).write_text(json.dumps(at))
        return fail(review.stamp(path, review.abort_text(head, verify_err, salvage=salvage)))
    kept = "The round IS recorded, and it names this tree — a reset here orphans it."
    refusal = review.abort_text(head, verify_err, kept, salvage=salvage) if verify_err else ""
    review.stamp(path, refusal)
    if err := review.write_reviewer_diff(path, head, at.get("noun", leg(story_id)[0])):
        return fail(review.stamp(path, err))  # already a whole refusal, prefix and all
    review.write_round(
        marker,
        state,
        report,
        reviewed_head=head,
        shown_sha=git("rev-parse", "HEAD").stdout.strip(),
        review_base=at["base"],
        branch=git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
    )
    review.launch_marker(story_id).unlink(missing_ok=True)
    return fail(refusal) if refusal else 0


def cmd_review(story_id: str, dry_run: bool = False) -> int:
    import review

    card, trunk, err = _preflight(story_id, "review", dry_run)
    if err:
        return fail(err)
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    if not dry_run:  # a preview must not delete the findings of a refused round
        doomed = [path, review.patch_path(path)]
        if left := unrecorded_notice(doomed, f"close.py {leg(story_id)[0]} salvage"):
            print("warning: " + left, file=sys.stderr)
        for doomed_path in doomed:
            doomed_path.unlink(missing_ok=True)
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    at = {"head": head, "digest": review.marker_digest(marker), "base": base, "card": card}
    at["noun"] = leg(story_id)[0]
    prior = render_prior_rounds(state.get("rounds", []))
    notices = [review.plan_review_notice(story_id)]
    notice = "\n".join(n for n in notices if n)
    if notice:
        print("warning: " + notice, file=sys.stderr)
    bundle = build_bundle(card, base, path, prior, notice)
    if not dry_run:
        review.launch_marker(story_id).write_text(json.dumps(at))
    result, err = review.run(bundle, Path.cwd(), dry_run, card=card, noun=at["noun"])
    if dry_run:
        return fail("refused: " + err) if err else 0
    if err:  # crash, timeout, absent binary — it may still have committed first
        return fail(review.stamp(path, review.abort_text(head, err)))
    print(result)
    return _record_round(story_id, card, path, marker, state, at)


def cmd_salvage(story_id: str) -> int:
    """Record a killed reviewer's patch and report, never reviewer commits."""
    import review

    _card, _trunk, err = _preflight(story_id, "salvage")
    if err:
        return fail(err)
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    launch = review.launch_marker(story_id)
    if not launch.exists():
        # Two states, so this must LOOK rather than list what it would have read:
        # `not readable — delete it` sends the lead here with the round's own
        # artifacts still on disk, and "nothing was left behind" is a lie there.
        left = ", ".join(str(p) for p in (path, review.patch_path(path)) if p.exists())
        return fail(
            f"refused: no unrecorded review for {story_id} — {launch} names the tree a"
            " killed reviewer was launched against, and salvage records no round it"
            " cannot bind to one. "
            + (
                f"{left} outlived it and belongs to no tree; copy it, then review"
                if left
                else f"Nor is {path} or {review.patch_path(path)} on disk. Run review"
            )
        )
    try:
        at = json.loads(launch.read_text())
    except ValueError as e:
        return fail(f"refused: {launch} is not readable ({e}) — delete it and review again")
    at["moved"] = (
        f"HEAD is no longer {at['head'][:8]}, the tree the killed review was launched"
        " against. Either the reviewer committed, which no reviewer leg may do, or you"
        " did since the kill — a reviewer runs with the git credentials stripped, so"
        " authorship says YOU either way. Reset to that sha, or review again"
    )
    # at["card"] and never the fresh card _preflight returns: the marker's copy is what
    # the reviewer was shown, and a card edited between the kill and the salvage would
    # otherwise widen what a dead reviewer is recorded as having been allowed to touch.
    return _record_round(story_id, at["card"], path, marker, state, at, salvage=True)


def _read(path: str) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else f"(missing: {path})"


def cmd_land(story_id: str, merge_mode: str, dry_run: bool) -> int:
    sys.path[:0] = [str(Path(__file__).parent / d) for d in ("close", "spawn")]
    import land

    return land.cmd_land(story_id, merge_mode, dry_run)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sp = sub.add_parser("sprint")
    sp.add_argument("sprint_id")
    sp.add_argument(
        "action", choices=["start", "review", "salvage", "land", "post-merge", "milestone-done"]
    )
    sp.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("free")
    f.add_argument("slug")
    f.add_argument("action", choices=["start", "review", "salvage", "land", "post-merge"])
    f.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("story")
    s.add_argument("story_id")
    s.add_argument("action", choices=["review", "salvage", "land"])
    # Derived: PR mode cannot integrate into a recorded sprint branch.
    s.add_argument("--merge-mode", choices=["pr", "local"], default=None)
    s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    # Unknown roles fail safe; this bounds the injected close path, not forged env.
    role = os.environ.get("XP_ROLE", "lead")
    if role != "lead":
        return fail(
            f"refused: XP_ROLE={role!r} — only the lead may close. You hand back a green"
            " Verify; the lead owns the judgment gap and the merge"
        )
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if a.kind == "free":
        import free

        if a.action == "start":
            return free.cmd_start(a.slug)
        if a.action == "review":
            return free.cmd_review(a.slug, a.dry_run)
        if a.action == "salvage":
            return free.cmd_salvage(a.slug)
        if a.action == "land":
            return free.cmd_land(a.slug, a.dry_run)
        return free.cmd_post_merge(a.slug)
    if a.kind == "sprint":
        import sprint_close

        if a.action == "start":
            return sprint_close.cmd_start(a.sprint_id)
        if a.action == "review":
            return sprint_close.cmd_review(a.sprint_id, a.dry_run)
        if a.action == "salvage":
            return sprint_close.cmd_salvage(a.sprint_id)
        if a.action == "land":
            return sprint_close.cmd_land(a.sprint_id, a.dry_run)
        if a.action == "milestone-done":
            return sprint_close.milestone.cmd_done(a.sprint_id)
        return sprint_close.cmd_post_merge(a.sprint_id)
    if a.action == "review":
        return cmd_review(a.story_id, a.dry_run)
    if a.action == "salvage":
        return cmd_salvage(a.story_id)
    mode = a.merge_mode or ("local" if integration_target() != default_branch() else "pr")
    return cmd_land(a.story_id, mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
