"""Atomic plan writes and one-card candidate application.

The refresher edits by shell and can hold no Python lock, so it is handed this
locked helper instead of having `ready`/`land` refuse while a refresh marker is
live. A refusal was rejected twice over: it serialises the parallel lanes the
process depends on, and it still leaves the refresher's own write unlocked --
it makes the collision loud without removing it.
"""

import fcntl
import os
import sys
from pathlib import Path


class CardEditRefusal(Exception):
    pass


def strip_lifecycle(plan: str) -> str:
    """A concurrent lane's locked `flip_card` moves nothing but a heading's [status],
    so comparing raw plan text reports every parallel story as outside motion and
    buries the sibling rewrite worth reading."""
    out = []
    for line in plan.splitlines(keepends=True):
        body = line.rstrip()
        if line.startswith("#") and body.endswith("]") and "[" in body:
            line = body[: body.rindex("[")].rstrip() + line[len(body) :]
        out.append(line)
    return "".join(out)


def locked_edit(path: Path, lock: Path, mutate) -> bool:
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        waited = False
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            owner = handle.read().strip() or "unknown"
            print(f"plan lock held by pid {owner}; waiting", file=sys.stderr, flush=True)
            waited = True
            fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        residue = handle.read().strip()
        if residue and not waited:
            print(
                f"plan lock owner pid {residue} was stale; recovered",
                file=sys.stderr,
                flush=True,
            )
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            text = path.read_text() if path.exists() else ""
            edited = mutate(text)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(edited)
            tmp.replace(path)
        finally:
            handle.seek(0)
            handle.truncate()
            handle.flush()
    return edited != text


def apply_card(
    story_id: str,
    expected_digest: str,
    expected_status: str,
    candidate_path: Path,
    story_card,
    card_digest,
    edit_plan,
) -> bool:
    if not candidate_path.is_absolute():
        raise CardEditRefusal("candidate path is not absolute")
    try:
        submitted = candidate_path.read_text()
        candidate, candidate_status = story_card(submitted, story_id)
    except (OSError, KeyError) as error:
        detail = error.args[0] if error.args else str(error)
        raise CardEditRefusal(
            f"candidate is not one parseable {story_id} card: {detail}"
        ) from error
    if candidate.rstrip() != submitted.rstrip():
        raise CardEditRefusal("candidate contains text outside its one story card")
    if candidate_status != expected_status:
        raise CardEditRefusal(
            f"candidate changed lifecycle [{expected_status}] to [{candidate_status}]"
        )

    def apply(current_plan: str) -> str:
        try:
            current, current_status = story_card(current_plan, story_id)
        except KeyError as error:
            raise CardEditRefusal(error.args[0]) from error
        if current_status != expected_status:
            raise CardEditRefusal(
                f"current lifecycle is [{current_status}], expected [{expected_status}]"
            )
        if card_digest(current) != expected_digest:
            raise CardEditRefusal("current card changed after the refresh read it")
        return current_plan.replace(current, candidate, 1)

    return edit_plan(apply)
