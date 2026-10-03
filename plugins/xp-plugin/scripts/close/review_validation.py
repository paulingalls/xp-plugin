"""Retain validation attempts and bind the lead's red/green disposition."""

import json
import os
from pathlib import Path

import close
import review
import verify_log
import verify_receipt
from review_sequence import binding, check_reports, load, locked, measure, save
from work import data_root


def validate(story_id, card, sequence):
    check_reports(sequence)
    if measure(story_id, card) != sequence["output"]:
        return close.fail(
            "refused: validation inputs moved; lead must explicitly review corrected work"
        )
    if review.marker_digest(close.marker_path(story_id)) != sequence["marker_identity"]:
        return close.fail("refused: close marker changed after completed review")
    root = data_root() / "logs/verify"
    before = set(root.glob(verify_log.prefix(story_id) + "*")) if root.exists() else set()
    baseline = sequence.setdefault("validation_baseline", sorted(str(p) for p in before))
    known = {attempt["path"] for attempt in sequence["validation"]} | set(baseline)
    for path in sorted(before):
        if str(path) in known:
            continue
        manifest = json.loads((path / "run.json").read_text())
        if manifest["status"] in verify_log.ACTIVE:
            continue
        if (
            manifest.get("head") != sequence["output"]["head"]
            or manifest.get("tree") != sequence["output"]["tree"]
            or manifest.get("phase") != "review"
        ):
            raise ValueError(f"validation evidence does not match reviewed inputs: {path}")
        error = (
            verify_log.refusal(path, manifest, " on the reviewed tree")
            if manifest["status"] != "passed"
            else ""
        )
        sequence["validation"].append(
            {"path": str(path), "identity": binding(path / "run.json"), "error": error}
        )
    sequence["status"] = "validation"
    save(story_id, sequence)
    raw, commands = close.verify_commands(story_id, card)
    error = verify_receipt.record(story_id, card, raw, commands)
    attempts = sorted(set(root.glob(verify_log.prefix(story_id) + "*")) - before)
    for path in attempts:
        sequence["validation"].append(
            {
                "path": str(path),
                "identity": binding(path / "run.json") if (path / "run.json").exists() else None,
                "error": error,
            }
        )
    if error and not attempts:
        sequence["validation"].append({"path": None, "identity": None, "error": error})
    if error:
        sequence.update(status="validation-red", problem=error)
        save(story_id, sequence)
        return close.fail(error)
    if any(item["error"] for item in sequence["validation"]):
        sequence["status"] = "awaiting-disposition"
        save(story_id, sequence)
        return close.fail(
            f"refused: green retry retains earlier red; lead must run `xp.py "
            f'{close.leg(story_id)[0]} acknowledge-validation --reason "<observed cause>"`'
        )
    sequence["status"] = "completed"
    save(story_id, sequence)
    return 0


def acknowledge(story_id, reason):
    def action():
        sequence = load(story_id)
        if os.environ.get("XP_ROLE", "lead") != "lead" or not reason.strip():
            return close.fail("refused: lead disposition requires a nonempty reason")
        if not sequence or sequence["status"] != "awaiting-disposition":
            return close.fail("refused: no same-tree red and green retry awaiting lead disposition")
        card, _ = close.story_card(close.plan_path().read_text(), story_id)
        if card != sequence["card"] or measure(story_id, card) != sequence["output"]:
            return close.fail("refused: disposition card, commands or reviewed tree moved")
        check_reports(sequence)
        if review.marker_digest(close.marker_path(story_id)) != sequence["marker_identity"]:
            return close.fail("refused: disposition close marker moved")
        from overlap import unresolved_blocking

        if unresolved_blocking(json.loads(close.marker_path(story_id).read_text())):
            return close.fail("refused: disposition cannot clear review findings")
        for attempt in sequence["validation"]:
            if attempt["path"] is None and attempt["error"]:
                continue
            path = Path(attempt["path"]) / "run.json"
            if not attempt["identity"] or binding(path) != attempt["identity"]:
                return close.fail("refused: disposition validation evidence missing or changed")
        if not sequence["validation"] or sequence["validation"][-1]["error"]:
            return close.fail("refused: disposition has no green retry")
        sequence.update(
            status="completed",
            disposition={
                "reason": reason,
                "attempts": sequence["validation"],
                "output": sequence["output"],
            },
        )
        save(story_id, sequence)
        return 0

    return locked(story_id, action)
