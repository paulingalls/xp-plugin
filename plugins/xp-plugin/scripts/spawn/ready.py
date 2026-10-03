import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import fail, story_card, verify_commands
from handoff import marker_path as handoff_marker_path
from review_scope import FIELD_START, declared_files
from verify_receipt import reads as verify_reads
from work import (
    card_digest,
    card_lines,
    chdir_repo_root,
    data_root,
    edit_plan,
    flip_status,
    missing_plan_refusal,
    plan_path,
    ready_marker_path,
)

AMEND = "Run `spawn.py amend {} --reason '<why this declaration changed>'`."
REMINT = "Run `spawn.py {}` to capture the approved card and begin planning."
DOC = "Capture the approved card; accepted review or reasoned amendment updates it."


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
        from plan_acceptance import valid_records

        valid &= valid_records(minted) if isinstance(minted, dict) else False
        return minted if valid else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def current_digest(story_id: str) -> str | None:
    current = credential(ready_marker_path(story_id))
    return current.get("digest") if current else None


def plan_needs_replan(story_id: str, handoff: dict) -> bool:
    from plan_acceptance import latest

    current = credential(ready_marker_path(story_id))
    accepted = latest(story_id)
    count = accepted.get("amendment_count", 0) if accepted else 0
    return bool(current and len(current.get("amendments", [])) > count)


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
            (i for i in range(start + 1, len(lines)) if FIELD_START.match(lines[i])),
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
    from plan_acceptance import binding_problem

    if not plan_needs_replan(sid, {}) and (problem := binding_problem(sid)):
        return problem
    if minted.get("digest") == card_digest(card):
        return ""
    if growth := card_growth(minted["card"], card):
        print(f"{sid} card grew — {growth}")
        return ""
    from plan_acceptance import interrupted_problem

    if problem := interrupted_problem(sid, card, minted):
        return problem
    diff = card_diff(minted["card"], card)
    return f"refused: {sid} was edited after its plan review:\n{diff}\n{AMEND.format(sid)}"


def amend(story_id: str, reason: str) -> int:
    if not reason.strip():
        return fail("refused: amend requires --reason")
    result = 0

    def update(text):
        nonlocal result
        if not plan_path().exists():
            raise FileNotFoundError(missing_plan_refusal())
        result = _amend_locked(story_id, reason, text)
        return text

    try:
        edit_plan(update)
    except OSError as error:
        return fail(f"refused: cannot amend {story_id}: {error}; repair it and retry amend")
    return result


def _amend_locked(story_id: str, reason: str, text: str) -> int:
    try:
        card, status = story_card(text, story_id)
    except (KeyError, OSError) as e:
        why = missing_plan_refusal() if isinstance(e, OSError) else e.args[0]
        return fail(f"refused: {why}")
    if status not in {"planned", "ready", "in-progress"}:
        return fail(
            f"refused: {story_id} is [{status}], amend requires [planned], [ready] or [in-progress]"
        )
    try:
        verify_commands(story_id, card)
        verify_reads(card)
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
    history = [*history, {"reason": reason, "card": prior, "after": card}]
    payload = (previous or {}) | {"digest": card_digest(card), "card": card, "amendments": history}
    payload.setdefault("minted_card", prior)
    marker.write_text(json.dumps(payload, ensure_ascii=False))
    print(f"{story_id} amended — reason: {reason}\n{card_diff(prior, card)}")
    return 0


def capture(story_id: str, make_ready: bool = False) -> int:
    result = 0

    def update(text):
        nonlocal result
        try:
            card, status = story_card(text, story_id)
            if status not in {"planned", "ready"}:
                raise ValueError(f"{story_id} is [{status}]; launch requires [planned] or [ready]")
            if make_ready and progressed(story_id):
                raise ValueError(f"{story_id} already spawned. {AMEND.format(story_id)}")
            declared_files(card)
            verify_commands(story_id, card)
            verify_reads(card)
            marker = ready_marker_path(story_id)
            if marker.exists():
                if problem := drift(story_id, card):
                    raise ValueError(problem)
            else:
                if progressed(story_id):
                    raise ValueError(f"{story_id} already spawned. {AMEND.format(story_id)}")
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(json.dumps({"digest": card_digest(card), "card": card}))
            if make_ready and status == "planned":
                return flip_status(text, f"#### {story_id} ", "planned", "ready")
        except (KeyError, ValueError) as error:
            result = fail(f"refused: {error}")
        return text

    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        edit_plan(update)
    except OSError as error:
        return fail(f"refused: cannot capture {story_id}: {error}; repair it and retry launch")
    if not result:
        print(f"{story_id} approved card captured — next run `spawn.py {story_id}`")
    return result


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
    return capture(args.story_id, make_ready=True)
