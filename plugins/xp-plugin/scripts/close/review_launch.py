"""Prepare the review artifacts before a reviewer launch."""

import json
import sys

import preflight
import review
from review_artifacts import notice, rotate_story


def check_preflight(dry_run):
    import close

    raw = close.config_flat("preflight")
    if dry_run:
        _raw, _commands, error = preflight.prepare(raw)
        if raw and not error:
            print(preflight.preview(raw))
        return error
    return preflight.check(raw)


def prepare(story_id, dry_run, marker, noun):
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.report_path(story_id, len(state.get("rounds", [])) + 1)
    launch = review.launch_marker(story_id)
    if not dry_run:
        moves = rotate_story(path, review.patch_path(path), launch)
        if left := notice(moves, f"close.py {noun} salvage"):
            print("warning: " + left, file=sys.stderr)
    return state, path, launch
