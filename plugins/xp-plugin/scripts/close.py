#!/usr/bin/env python3
"""Story review records judgment; story land runs gates and moves refs without spawning."""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
from bookkeep import render_prior_rounds
from env import sprint_branch
from work import (
    chdir_repo_root,
    data_root,
    missing_plan_refusal,
    plan_path,
    strip_comment,
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


def verify_commands(card: str) -> str:
    for ln in card.splitlines():
        if ln.startswith("Verify:"):
            return ln.removeprefix("Verify:").strip()
    return ""


def verify_refusal(story_id: str, card: str) -> str:
    """Why this card has no runnable Verify, or "". A LABEL with nothing after it
    is a different problem from no label, and saying "no Verify: line" about a
    card that visibly has one sends the author hunting for the wrong thing —
    they wrote the commands as bullets below it, which is what `AC:` looks like."""
    if verify_commands(card):
        return ""
    if any(ln.startswith("Verify:") for ln in card.splitlines()):
        return (
            f"refused: {story_id}'s Verify: line is empty — its commands must be on the"
            " SAME line as the label (`Verify: pytest -q ...`), not a list below it"
        )
    return f"refused: {story_id} has no Verify: line — an unverifiable story cannot close"


def config_flat(key: str) -> str:
    """A flat top-level `key: value` from .xp/config.yml."""
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
    """The recorded sprint branch under release: sprint, else the default."""
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
            # refs/heads explicitly: a tag with the same name wins plain rev-parse
            # and would freeze every guard on a ref that never moves
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
    """The trunk: where sprints land and releases are tagged.

    `trunk:` overrides git's own default, for a repo integrating on develop while
    origin/HEAD still names main — every caller here means the former. Absent-but-
    configured REFUSES rather than falling back, as the sprint branch does: silently
    releasing to main is the failure this key exists to prevent. Deliberately ONE
    branch; the develop->main release cut stays the project's own process.
    """
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
    """Fetched origin/<trunk> sha, or None without a remote. pr mode merges on
    origin; local mode merges the local trunk — each mode guards the ref it
    actually integrates (recording both at start, since mode is unknown then)."""
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
        # One greppable line: the charter explains the shape, this is the address.
        ("Your report", f"REPORT_PATH: {report}\nPATCH_PATH: {review.patch_path(report)}"),
        ("Story card", card or "none — this is a free branch; judge the diff itself"),
        *([("Before you start", notice)] if notice else []),
        ("Earlier rounds of THIS review", prior or "none — you are round 1"),
        ("Cumulative diff", git("diff", f"{base}..HEAD").stdout),
        ("work.md entries filed during the story", work_entries_since(base_epoch) or "none"),
        ("PROCESS", _read(str(review.PLUGIN_ROOT / "PROCESS.md"))),
        ("VALUES", _read(str(Path(__file__).parent.parent / "VALUES.md"))),
        ("Constraints", _read(".xp/constraints.md")),
        ("System context", _read(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _preflight(story_id: str, action: str, free: bool = False) -> tuple[str, str, str]:
    """(card, trunk, error) — the checks every review leg shares."""
    if git("status", "--porcelain").stdout.strip():
        return "", "", "refused: working tree is dirty — commit or stash first"
    card, trunk = "", default_branch() if free else integration_target()
    if free:
        if plan_path().exists() and f"#### {story_id} " in plan_path().read_text():
            try:
                card, status = story_card(plan_path().read_text(), story_id)
            except KeyError as e:
                return "", "", f"refused: {e.args[0]}"
            if status not in ("planned", "ready", "in-progress"):
                return "", "", f"refused: {story_id} is [{status}], {action} cannot use it"
    else:
        if not plan_path().exists():
            return "", "", f"refused: {missing_plan_refusal()}"
        try:
            card, status = story_card(plan_path().read_text(), story_id)
        except KeyError as e:
            return "", "", f"refused: {e.args[0]}"
        if status != "in-progress":
            return "", "", f"refused: {story_id} is [{status}], {action} requires [in-progress]"
    if card:
        try:  # 3e2ad94b: an annotated Verify line reached /bin/sh at LAND, post-review
            shlex.split(verify_commands(card))
        except ValueError as e:
            return "", "", f"refused: {story_id}'s Verify: line is not runnable ({e})"
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
    """Why the tree this round would certify fails its own Verify, or "".

    Otherwise `blocking: []` is the MODEL's word that Verify ran, and a reviewer
    whose sandbox could not reach a leg reports green in good faith (note
    1b45d1c7). land keeps its own call: that one protects the MERGE, this the
    DIFF. A card-less free diff declares no Verify, so there is none to run.
    """
    if not card:
        return ""
    if refusal := verify_refusal(story_id, card):
        return refusal.removeprefix("refused: ")
    import overlap  # a cycle at module level: it imports close

    red = overlap.run_one("Verify", verify_commands(card), " on the reviewed tree")
    return red.removeprefix("refused: ")


def _record_round(story_id: str, card: str, path: Path, marker: Path, state: dict, at: dict) -> int:
    """The guards and the bookkeeping both review and salvage run. `at` is what
    the leg was launched AGAINST, which salvage reads off the launch marker.
    Routing salvage through here is what closes the timeout door — it is the one
    path by which a reviewer that committed could reach a recorded round."""
    import review

    head = at["head"]
    motion = review.check_reviewer_motion(
        head, marker, at["digest"], card, story_id, at.get("moved", "")
    )
    if motion:
        return fail(review.stamp(path, motion))
    report, err = review.read_report(path)
    if err:
        return fail(review.stamp(path, review.abort_text(head, err)))
    if err := review.apply_patch(path, card):
        return fail(review.stamp(path, review.abort_text(head, err)))
    verify_err = verify_on_reviewed_tree(story_id, card)
    if verify_err and not report["blocking"]:
        return fail(review.stamp(path, review.abort_text(head, verify_err)))
    kept = "The round IS recorded, and it names this tree — a reset here orphans it."
    refusal = review.abort_text(head, verify_err, kept) if verify_err else ""
    review.stamp(path, refusal)
    if err := review.write_reviewer_diff(path, head, f"story {story_id}"):
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


def cmd_review(story_id: str, dry_run: bool = False, free: bool = False) -> int:
    import review

    card, trunk, err = _preflight(story_id, "review", free)
    if err:
        return fail(err)
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    if not dry_run:  # a preview must not delete the findings of a refused round
        path.unlink(missing_ok=True)
        review.patch_path(path).unlink(missing_ok=True)
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    at = {"head": head, "digest": review.marker_digest(marker), "base": base, "card": card}
    prior = render_prior_rounds(state.get("rounds", []))
    notices = [review.plan_review_notice(story_id)]
    if free and not card:
        changed = git("diff", "--numstat", f"{base}..HEAD").stdout.splitlines()
        lines = sum(int(n) for row in changed for n in row.split("\t")[:2] if n.isdigit())
        notices.append(
            f"card-less free diff is {lines} changed lines across {len(changed)} files;"
            " a card would add explicit scope, AC, and Verify"
        )
    notice = "\n".join(n for n in notices if n)
    if notice:
        print("warning: " + notice, file=sys.stderr)
    bundle = build_bundle(card, base, path, prior, notice)
    if not dry_run:
        review.launch_marker(story_id).write_text(json.dumps(at))
    result, err = review.run(bundle, Path.cwd(), dry_run, card=card)
    if dry_run:
        return 0
    if err:  # crash, timeout, absent binary — it may still have committed first
        return fail(review.stamp(path, review.abort_text(head, err)))
    # BEFORE any refusal below: a report the pipeline rejects still cost a full
    # review, and its findings exist nowhere else.
    print(result)
    return _record_round(story_id, card, path, marker, state, at)


def cmd_salvage(story_id: str) -> int:
    """Record the round a KILLED reviewer's own artifacts already earned — the
    patch and report it wrote, never its commits: reviewers have been read-only
    since v0.7.0, so salvaging commits names what our own guard refuses."""
    import review

    _card, _trunk, err = _preflight(story_id, "salvage")
    if err:
        return fail(err)
    launch = review.launch_marker(story_id)
    if not launch.exists():
        return fail(
            f"refused: no unrecorded review for {story_id} — salvage records what a"
            " killed reviewer already wrote, and nothing was left behind. Run review"
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
    marker = marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    return _record_round(story_id, at["card"], path, marker, state, at)


def _read(path: str) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else f"(missing: {path})"


def cmd_land(story_id: str, merge_mode: str, dry_run: bool, free_slug: str = "") -> int:
    sys.path[:0] = [str(Path(__file__).parent / d) for d in ("close", "spawn")]
    import land

    return land.cmd_land(story_id, merge_mode, dry_run, free_slug)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sp = sub.add_parser("sprint")
    sp.add_argument("sprint_id")
    sp.add_argument("action", choices=["start", "review", "land", "post-merge"])
    sp.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("free")
    f.add_argument("slug")
    f.add_argument("action", choices=["start", "review", "land", "post-merge"])
    f.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("story")
    s.add_argument("story_id")
    s.add_argument("action", choices=["review", "salvage", "land"])
    # DERIVED, not chosen: pr mode is refused whenever the integration target is not
    # the default branch, and `merge-mode` appeared in no shipped prose — so the
    # documented invocation was the one that refuses.
    s.add_argument("--merge-mode", choices=["pr", "local"], default=None)
    s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    # The gate the teammate profile only DECLARES: a self-close is
    # an unreviewed merge. Any non-lead role, so an unknown one fails safe. It bounds
    # the /story-close path, NOT a teammate who types XP_ROLE=lead.
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
        if a.action == "land":
            return free.cmd_land(a.slug, a.dry_run)
        return free.cmd_post_merge(a.slug)
    if a.kind == "sprint":
        import sprint_close

        if a.action == "start":
            return sprint_close.cmd_start(a.sprint_id)
        if a.action == "review":
            return sprint_close.cmd_review(a.sprint_id, a.dry_run)
        if a.action == "land":
            return sprint_close.cmd_land(a.sprint_id, a.dry_run)
        return sprint_close.cmd_post_merge(a.sprint_id)
    if a.action == "review":
        return cmd_review(a.story_id, a.dry_run)
    if a.action == "salvage":
        return cmd_salvage(a.story_id)
    mode = a.merge_mode or ("local" if integration_target() != default_branch() else "pr")
    return cmd_land(a.story_id, mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
