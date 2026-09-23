import argparse
import difflib
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import fail, git, leg, story_card, verify_commands
from handoff import marker_path as handoff_marker_path
from review_scope import declared_files
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
UNPARSABLE = "refused: {}. Repair the Files line in {}, then refresh {}."
REMINT = "Put the heading back to [planned] and run `spawn.py ready {}`."
DOC = "The plan-review credential: minted from [planned], amended only with a recorded reason."


def refresh_instruction(story_id: str) -> str:
    script = str(Path(__file__).parent.parent / "slate_review.py")
    command = shlex.join(["python3", script, story_id, "--refresh"])
    return (
        f"Finish all card edits. Refresh once: Run `{command}`. Then run"
        f" `spawn.py ready {story_id}`."
    )


def spawned(story_id: str) -> bool:
    return handoff_marker_path(data_root(), story_id).exists()


def progressed(story_id: str) -> bool:
    root = data_root()
    close = root / "markers" / f"{story_id}.close.json"
    return spawned(story_id) or close.exists()


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


def current_digest(story_id: str) -> str | None:
    current = credential(ready_marker_path(story_id))
    return current.get("digest") if current else None


def plan_needs_replan(story_id: str, handoff: dict) -> bool:
    result = handoff.get("stages", {}).get("plan-reviewer")
    if result == "blocked":
        return True
    if result != "ran":
        return False
    reviewed = handoff.get("plan_reviewed_card")
    if reviewed is None:
        current = credential(ready_marker_path(story_id))
        return bool(current and current.get("amendments"))
    return reviewed != current_digest(story_id)


def card_diff(reviewed: str, card: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            card_lines(reviewed), card_lines(card), "reviewed", "now", lineterm="", n=1
        )
    )


def card_growth(reviewed: str, card: str) -> str:
    old, new = card_lines(reviewed), card_lines(card)

    def fields(lines):
        files = [i for i, line in enumerate(lines) if line.startswith("Files:")]
        verify = [i for i, line in enumerate(lines) if line.startswith("Verify:")]
        if len(files) != 1 or len(verify) != 1:
            return None
        start = files[0]
        end = next(
            (i for i in range(start + 1, len(lines)) if re.match(r"[A-Za-z][A-Za-z ]*:", lines[i])),
            len(lines),
        )
        return set(range(start, end)), verify[0]

    before, after = fields(old), fields(new)
    if before is None or after is None:
        return ""
    old_files, old_verify = before
    new_files, new_verify = after

    def fixed(lines, files, verify):
        return [
            "<Files>" if i == min(files) else "<Verify>" if i == verify else line
            for i, line in enumerate(lines)
            if i not in files or i == min(files)
        ]

    if fixed(old, old_files, old_verify) != fixed(new, new_files, new_verify):
        return ""
    try:
        prior, current = declared_files(reviewed), declared_files(card)
    except ValueError:
        return ""
    added = current - prior
    files_changed = [old[i] for i in sorted(old_files)] != [new[i] for i in sorted(new_files)]
    if files_changed and (not prior < current or any(p.startswith(".xp/") for p in added)):
        return ""
    old_line, new_line = old[old_verify], new[new_verify]
    extended = new_line.startswith(old_line + " && ")
    if new_line != old_line and not extended:
        return ""
    verify_added = new_line.removeprefix(old_line + " && ") if extended else ""
    if not files_changed and not verify_added:
        return ""
    parts = [f"Files: {path}" for path in sorted(added)]
    if verify_added:
        parts.append(f"Verify: {verify_added}")
    return "; ".join(parts)


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
    if growth := card_growth(minted["card"], card):
        print(f"{sid} card grew — {growth}")
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
    # Once the story has progressed its Files line records what was BUILT: no refresher
    # can have credentialed a path the implementation discovered, and close.py land
    # names amend as the ONLY route to declare one. Before it, an added path that exists
    # at HEAD is a new claim about existing code and the receipt has to cover it.
    if not leg(story_id)[1] and (
        problem := check_refresh(
            story_id, card, require_digest=False, require_paths=not progressed(story_id)
        )
    ):
        return fail(problem)
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
    """The card refresh's story-scoped proof, outside the repository."""
    from slate_review import safe_story_id  # ONE traversal rule; a second copy only drifts

    return data_root() / "card-refreshes" / f"{safe_story_id(story_id)}.json"


def path_state(path: str) -> str | None:
    """Latest commit touching `path`, or None; working-tree edits do not count."""
    exists = git("cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0
    if not exists:
        return None
    pathspec = f":(literal){path}"
    sha = git("log", "-1", "--format=%H", "HEAD", "--", pathspec, check=False).stdout.strip()
    return sha or None


def write_refresh_receipt(story_id: str, card: str, changed: bool) -> str:
    """Record what the refresh covered, or return a refusal naming the bad entry."""
    try:
        declared = sorted(declared_files(card))
    except ValueError as error:
        return UNPARSABLE.format(error, plan_path(), story_id)
    path = refresh_receipt_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    files = {p: path_state(p) for p in declared}
    receipt = {
        "basis": "HEAD",
        "head": git("rev-parse", "HEAD", check=False).stdout.strip(),
        "digest": card_digest(card),
        "changed": changed,
        "files": files,
    }
    _write_refresh_receipt(path, receipt)
    return ""


def _write_refresh_receipt(path: Path, receipt: dict) -> None:
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False))
    temporary.replace(path)


def _load_refresh_receipt(story_id: str) -> tuple[Path | None, dict | None, str]:
    try:
        path = refresh_receipt_path(story_id)
    except ValueError as error:
        return None, None, f"{error}. {refresh_instruction(story_id)}"
    if not path.exists():
        return (
            path,
            None,
            f"refused: no card refresh has run for {story_id}. {refresh_instruction(story_id)}",
        )
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError):
        return path, None, f"refused: {path} is unreadable. {refresh_instruction(story_id)}"
    if not isinstance(receipt, dict) or not isinstance(receipt.get("files"), dict):
        return (
            path,
            None,
            f"refused: {path} is not a card refresh receipt. {refresh_instruction(story_id)}",
        )
    return path, receipt, ""


def refresh_path_receipt(story_id: str, card: str) -> tuple[dict | None, str]:
    _path, receipt, problem = _load_refresh_receipt(story_id)
    if problem:
        return None, problem
    try:
        paths = declared_files(card)
    except ValueError as error:
        return None, UNPARSABLE.format(error, plan_path(), story_id)
    files = receipt["files"].copy()
    for declared in paths:
        state = path_state(declared)
        if declared not in receipt["files"]:
            if state is not None:
                return None, (
                    f"refused: {story_id}'s card refresh receipt does not cover {declared}"
                    f" — it predates the path being declared. {refresh_instruction(story_id)}"
                )
            files[declared] = None
        elif state != receipt["files"][declared]:
            return None, (
                f"refused: {declared} changed since {story_id}'s card refresh"
                f" — the receipt no longer reflects HEAD. {refresh_instruction(story_id)}"
            )
    return receipt | {"files": files}, ""


def remint_refresh_receipt(story_id: str, card: str, receipt: dict) -> str:
    try:
        declared = sorted(declared_files(card))
        path = refresh_receipt_path(story_id)
    except ValueError as error:
        return UNPARSABLE.format(error, plan_path(), story_id)
    updated = receipt | {
        "digest": card_digest(card),
        "files": {name: receipt["files"][name] for name in declared},
        "reminted": True,
    }
    _write_refresh_receipt(path, updated)
    return ""


def check_refresh(
    story_id: str, card: str, require_digest: bool = True, require_paths: bool = True
) -> str:
    """Return a refusal unless the receipt matches this card and its paths."""
    _path, receipt, problem = _load_refresh_receipt(story_id)
    if problem:
        return problem
    if require_digest and receipt.get("digest") != card_digest(card):
        return (
            f"refused: {story_id}'s card refresh receipt does not match the current card"
            f" — it ran against different text. {refresh_instruction(story_id)}"
        )
    if not require_paths:
        return ""
    return refresh_path_receipt(story_id, card)[1]


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
    # Free cards are authored and reviewed on a fresh branch, never aged in a slate,
    # so the refresh gate is exempted by LANE — not by any caller's choice.
    return mint(args.story_id, require_refresh=not leg(args.story_id)[1])
