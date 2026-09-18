"""Recover an interrupted story review."""

import json

from review_artifacts import restore_story_queue, story_sidecar


def cmd_salvage(story_id: str, dry_run: bool = False) -> int:
    import close
    import review

    _card, _trunk, err = close._preflight(story_id, "salvage")
    if err:
        return close.fail(err)
    marker = close.marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    round_n = len(state.get("rounds", [])) + 1
    path = review.report_path(story_id, round_n)
    canonical = review.launch_marker(story_id)
    launch = canonical if canonical.exists() else story_sidecar(path)
    if not launch.exists():
        if dry_run:
            print(f"dry run: no launch marker for {story_id} — nothing was restored or recorded")
            return 0
        try:
            restore_story_queue(story_id, round_n)
        except FileExistsError as exc:
            return close.fail(f"refused: cannot restore queued review artifacts over {exc}")
        launch = canonical if canonical.exists() else story_sidecar(path)
    if not launch.exists():
        # Artifacts without a launch binding and a genuinely empty queue are distinct states.
        left = ", ".join(str(p) for p in (path, review.patch_path(path)) if p.exists())
        return close.fail(
            f"refused: no unrecorded review for {story_id} — {canonical} names the tree a"
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
    except ValueError as error:
        return close.fail(
            f"refused: {launch} is not readable ({error}) — delete it and review again"
        )
    current = close.git("rev-parse", "HEAD").stdout.strip()
    if at.get("applied_head") == current:
        at["close_authored_motion"] = True
        at["moved"] = (
            f"HEAD {current[:8]} is the patch commit close.py applied before the round"
            " refused. Keep and inspect it, repair the reported failure, then review again"
            " from the current tree"
        )
    else:
        at["moved"] = (
            f"HEAD is no longer {at['head'][:8]}, the tree the killed review was launched"
            " against. The motion happened outside close.py; review again from the current"
            " HEAD, or explicitly abandon that work by restoring the reviewed sha"
        )
    if dry_run:
        print(f"dry run: would record round {round_n} for {story_id} from {launch}")
        return 0
    # The launch card is the dead reviewer's scope; a later edit must not widen it.
    return close._record_round(story_id, at["card"], path, marker, state, at, launch, salvage=True)
