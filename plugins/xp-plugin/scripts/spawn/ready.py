import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import fail, story_card, verify_commands
from handoff import marker_path as handoff_marker_path
from work import (
    card_digest,
    card_lines,
    chdir_repo_root,
    data_root,
    flip_card,
    missing_plan_refusal,
    plan_path,
    ready_marker_path,
)

AMEND = "Run `spawn.py amend {} --reason '<why this declaration changed>'`."
REMINT = "Put the heading back to [planned] and run `spawn.py ready {}`."


def credential(marker: Path) -> dict | None:
    try:
        minted = json.loads(marker.read_text())
        history = minted.get("amendments", []) if isinstance(minted, dict) else None
        valid = isinstance(minted, dict) and isinstance(minted.get("card"), str)
        valid &= isinstance(history, list) and all(
            isinstance(x, dict) and all(isinstance(x.get(k), str) for k in ("reason", "card"))
            for x in history
        )
        return minted if valid else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def card_diff(reviewed: str, card: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            card_lines(reviewed), card_lines(card), "reviewed", "now", lineterm="", n=1
        )
    )


def drift(sid: str, card: str) -> str:
    marker = ready_marker_path(sid)
    spawned = handoff_marker_path(data_root(), sid).exists()
    recovery = (AMEND if spawned else REMINT).format(sid)
    if not marker.exists():
        return f"refused: nothing minted it for {sid}; {marker} is absent. {recovery}"
    minted = credential(marker)
    if minted is None:
        return f"refused: {marker} is unreadable; nothing vouches for {sid}. {recovery}"
    if minted.get("digest") == card_digest(card):
        return ""
    diff = card_diff(minted["card"], card)
    return f"refused: {sid} was edited after its plan review:\n{diff}\n{AMEND.format(sid)}"


def amend(story_id: str, reason: str) -> int:
    if not reason.strip():
        return fail("refused: amend requires --reason")
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except (KeyError, OSError) as e:
        why = missing_plan_refusal() if isinstance(e, OSError) else e.args[0]
        return fail(f"refused: {why}")
    if status not in {"ready", "in-progress"}:
        return fail(f"refused: {story_id} is [{status}], amend requires [ready] or [in-progress]")
    try:
        verify_commands(story_id, card)
    except ValueError as e:
        return fail(str(e))
    marker = ready_marker_path(story_id)
    previous = credential(marker)
    if previous is None and not handoff_marker_path(data_root(), story_id).exists():
        return fail(f"refused: no reviewed card to amend. {REMINT.format(story_id)}")
    prior = previous["card"] if previous else "(credential absent)"
    if previous is None and marker.exists():
        prior = marker.read_text(errors="replace") or "(credential empty)"
    history = previous.get("amendments", []) if previous else []
    history = [*history, {"reason": reason, "card": prior}]
    payload = {"digest": card_digest(card), "card": card, "amendments": history}
    marker.write_text(json.dumps(payload, ensure_ascii=False))
    print(f"{story_id} amended — reason: {reason}\n{card_diff(prior, card)}")
    return 0


def mint(story_id: str) -> int:
    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if status != "planned":
        return fail(f"refused: {story_id} is [{status}]; ready mints only from [planned]")
    if handoff_marker_path(data_root(), story_id).exists():
        return fail(f"refused: {story_id} was already spawned. {AMEND.format(story_id)}")
    try:
        verify_commands(story_id, card)
    except ValueError as e:
        return fail(str(e) + " — fix it before the review, not after the story")
    digest = card_digest(card)
    marker = ready_marker_path(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"digest": digest, "card": card}, ensure_ascii=False))
    flip_card(story_id, "planned", "ready")
    print(f"{story_id} [planned] -> [ready], digest {digest} — next run `spawn.py {story_id}`")
    return 0


def main(argv: list[str], action: str = "ready") -> int:
    p = argparse.ArgumentParser(prog=f"spawn.py {action}", description=__doc__)
    p.add_argument("story_id")
    if action == "amend":
        p.add_argument("--reason", default="")
    args = p.parse_args(argv)
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return amend(args.story_id, args.reason) if action == "amend" else mint(args.story_id)
