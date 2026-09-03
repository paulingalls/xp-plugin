import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import fail, git, leg, story_card, verify_commands
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
DOC = "The plan-review credential: minted from [planned], amended only with a recorded reason."
REFRESH = f"Run `python3 {Path(__file__).parent.parent / 'slate_review.py'} {{}} --refresh`."


def progressed(story_id: str) -> bool:
    root = data_root()
    close = root / "markers" / f"{story_id}.close.json"
    return handoff_marker_path(root, story_id).exists() or close.exists()


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
    recovery = (AMEND if progressed(sid) else REMINT).format(sid)
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
    if previous is None and not progressed(story_id):
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


def refresh_receipt_path(story_id: str) -> Path:
    """Story-scoped, outside the repo — the card refresh's proof that it ran
    against a card ready is about to digest, distinct from never having run."""
    return data_root() / "card-refreshes" / f"{story_id}.json"


def path_state(path: str) -> str | None:
    """The SHA of the latest commit touching `path` at HEAD, or None if HEAD
    does not have it — committed state, never filesystem mtimes or working-tree
    contents, so an uncommitted local edit cannot forge or stale a receipt."""
    exists = git("cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0
    if not exists:
        return None
    sha = git("log", "-1", "--format=%H", "HEAD", "--", path, check=False).stdout.strip()
    return sha or None


def write_refresh_receipt(story_id: str, card: str, changed: bool) -> None:
    import review  # function-local: slate_review -> spawn -> ready would cycle

    path = refresh_receipt_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    files = {p: path_state(p) for p in sorted(review.declared_files(card))}
    receipt = {
        "head": git("rev-parse", "HEAD", check=False).stdout.strip(),
        "digest": card_digest(card),
        "changed": changed,
        "files": files,
    }
    path.write_text(json.dumps(receipt, ensure_ascii=False))


def check_refresh(story_id: str, card: str) -> str:
    """ "" when a card refresh ran against exactly this card and every path it
    declares still matches HEAD as the refresh last saw it; else the refusal."""
    import review

    path = refresh_receipt_path(story_id)
    if not path.exists():
        return f"refused: no card refresh has run for {story_id}. {REFRESH.format(story_id)}"
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError):
        return f"refused: {path} is unreadable. {REFRESH.format(story_id)}"
    if not isinstance(receipt, dict) or not isinstance(receipt.get("files"), dict):
        return f"refused: {path} is not a card refresh receipt. {REFRESH.format(story_id)}"
    if receipt.get("digest") != card_digest(card):
        return (
            f"refused: {story_id}'s card refresh receipt does not match the current card"
            f" — it ran against different text. {REFRESH.format(story_id)}"
        )
    for declared in review.declared_files(card):
        if declared not in receipt["files"]:
            return (
                f"refused: {story_id}'s card refresh receipt does not cover {declared}"
                f" — it predates the path being declared. {REFRESH.format(story_id)}"
            )
        if path_state(declared) != receipt["files"][declared]:
            return (
                f"refused: {declared} changed since {story_id}'s card refresh"
                f" — the receipt no longer reflects HEAD. {REFRESH.format(story_id)}"
            )
    return ""


def mint(story_id: str, require_refresh: bool) -> int:
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
    if require_refresh and (problem := check_refresh(story_id, card)):
        return fail(problem)
    digest = card_digest(card)
    marker = ready_marker_path(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"digest": digest, "card": card}, ensure_ascii=False))
    flip_card(story_id, "planned", "ready")
    print(f"{story_id} [planned] -> [ready], digest {digest} — next run `spawn.py {story_id}`")
    return 0


def main(argv: list[str], action: str = "ready") -> int:
    p = argparse.ArgumentParser(prog=f"spawn.py {action}", description=DOC)
    p.add_argument("story_id")
    if action == "amend":
        p.add_argument("--reason", default="", help="why this declaration changed — required")
    args = p.parse_args(argv)
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if action == "amend":
        return amend(args.story_id, args.reason)
    # exempt BY LANE, matching close/free.py's own mint: a free card is authored
    # and reviewed on a branch cut minutes ago and never ages in a slate, and one
    # operation must not answer two ways depending on which leg reached it
    return mint(args.story_id, require_refresh=not leg(args.story_id)[1])
