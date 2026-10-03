"""Bind a completed foreground review to its exact declaration and artifacts."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "spawn"))

import env as env
from plan_writer import CardEditRefusal, apply_card, validate_candidate
from work import card_digest, card_title, edit_plan, plan_path, ready_marker_path


def identity(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def protected(card: str) -> tuple:
    from review_scope import FIELD_START

    fields, active = [], False
    for line in card.splitlines():
        if FIELD_START.match(line):
            active = line.startswith(("Executor:", "Decision:"))
        if active and line.strip():
            fields.append(line)
    return card_title(card), tuple(fields)


def candidate_path(out: Path) -> Path:
    return out.with_suffix(".card.md").resolve()


def receipt_path(out: Path) -> Path:
    return out.with_suffix(".acceptance.json").resolve()


def prepare(
    story_id: str,
    before: str,
    candidate: Path,
    plan: Path,
    out: Path,
    repository_identity: str = "",
) -> dict:
    from close import story_card
    from ready import credential

    _before, status = story_card(before, story_id)
    after = validate_candidate(story_id, status, candidate, story_card)
    if protected(before) != protected(after):
        raise CardEditRefusal(
            "title, Executor and Decision are reserved; restore them in the "
            "candidate and report the choice in human_question"
        )
    minted = credential(ready_marker_path(story_id))
    if minted is None:
        raise CardEditRefusal(
            "the ready credential is unreadable; restore it before accepting this round"
        )
    if minted["digest"] != card_digest(before):
        from ready import card_growth

        if not card_growth(minted["card"], before):
            raise CardEditRefusal(
                "the review read an uncredentialed declaration; amend before reviewing"
            )
    record = {
        "story_id": story_id,
        "before": before,
        "after": after,
        "status": status,
        "prior_digest": minted["digest"],
        "digest": card_digest(after),
        "candidate": str(candidate),
        "plan": str(plan.resolve()),
        "findings": str(out.resolve()),
        "plan_identity": identity(plan),
        "findings_identity": identity(out),
        "amendment_count": len(minted.get("amendments", [])),
    }
    if repository_identity:
        record["repository_identity"] = repository_identity
    atomic_json(receipt_path(out), record)
    return record


def publish(story_id: str, record: dict) -> None:
    from close import story_card
    from ready import credential

    if record["story_id"] != story_id:
        raise CardEditRefusal("the acceptance belongs to another story; use its recorded story id")
    from plan_confirmation import publication_problem

    if problem := publication_problem(record):
        raise CardEditRefusal(problem)
    marker = ready_marker_path(story_id)
    minted = credential(marker)
    if minted is None or minted.get("digest") != record["prior_digest"]:
        raise CardEditRefusal(
            "the credential changed since this review; restore the recorded "
            "credential before re-applying this round"
        )
    for kind in ("plan", "findings"):
        if identity(Path(record[kind])) != record[kind + "_identity"]:
            raise CardEditRefusal(
                f"the recorded {kind} changed; restore that round's bytes before re-applying"
            )
    candidate = Path(record["candidate"])
    if candidate.read_text() != record["after"]:
        raise CardEditRefusal(
            "the recorded candidate changed; restore that round's candidate before re-applying"
        )
    current, _ = story_card(plan_path().read_text(), story_id)
    expected = record["after"] if current == record["after"] else record["before"]
    apply_card(
        story_id,
        card_digest(expected),
        record["status"],
        candidate,
        story_card,
        card_digest,
        edit_plan,
        expected_card=expected,
    )

    def bind(text):
        if problem := publication_problem(record):
            raise CardEditRefusal(problem)
        current, _ = story_card(text, story_id)
        if current != record["after"]:
            raise CardEditRefusal(
                "the accepted card changed before credential publication; restore "
                "the recorded candidate and re-apply this round"
            )
        if credential(marker) != minted:
            raise CardEditRefusal(
                "the credential changed before publication; inspect the concurrent amendment"
            )
        updated = minted | {"digest": record["digest"], "card": record["after"]}
        updated.setdefault("minted_card", minted["card"])
        updated["review_acceptances"] = [*minted.get("review_acceptances", []), record]
        atomic_json(marker, updated)
        return text

    edit_plan(bind)


def valid_records(minted: dict) -> bool:
    records = minted.get("review_acceptances", [])
    keys = (
        "story_id",
        "before",
        "after",
        "status",
        "prior_digest",
        "digest",
        "candidate",
        "plan",
        "findings",
        "plan_identity",
        "findings_identity",
    )
    return (
        isinstance(records, list)
        and all(
            isinstance(record, dict)
            and all(isinstance(record.get(key), str) for key in keys)
            and record["digest"] == card_digest(record["after"])
            for record in records
        )
        and isinstance(minted.get("minted_card", ""), str)
    )


def latest(story_id: str) -> dict | None:
    from ready import credential

    minted = credential(ready_marker_path(story_id))
    records = minted.get("review_acceptances", []) if minted else []
    return records[-1] if records else None


def artifact_problem(record: dict) -> str:
    from plan_disposition import durable_disposition

    findings = ""
    for kind in ("plan", "findings"):
        contents = Path(record[kind]).read_bytes()
        if hashlib.sha256(contents).hexdigest() != record[kind + "_identity"]:
            return (
                f"refused: accepted {kind} changed after plan review; "
                f"restore {record[kind]} or amend and resume {record['story_id']}"
            )
        if kind == "findings":
            findings = contents.decode()
    _outcome, problem = durable_disposition(findings)
    if problem:
        return (
            f"refused: accepted plan review at {record['findings']}: {problem}; "
            "answer in the card, amend, then resume"
        )
    return ""


def binding_problem(story_id: str) -> str:
    try:
        record = latest(story_id)
        if record:
            from ready import current_digest

            if record["digest"] != current_digest(story_id):
                return ""
            return artifact_problem(record)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return (
            f"refused: unreadable review acceptance for {story_id}: {error}; "
            f"restore its recorded artifacts before resuming"
        )
    return ""


def provenance(story_id: str) -> str:
    from ready import card_diff, credential

    minted = credential(ready_marker_path(story_id)) or {}
    parts = []
    for record in minted.get("review_acceptances", []):
        if record["before"] != record["after"]:
            source = Path(record["findings"])
            preserved = [
                str(path)
                for path in source.parent.glob(f"{story_id}.superseded-*.round-*.md")
                if identity(path) == record["findings_identity"]
            ]
            archive = f"; preserved at {', '.join(preserved)}" if preserved else ""
            parts.append(
                f"card corrected by plan review — source: {record['findings']} "
                f"({record['findings_identity']}){archive}\n"
                + card_diff(record["before"], record["after"])
            )
    return "\n".join(parts)


def main() -> int:
    import argparse

    from work import chdir_repo_root

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story_id")
    parser.add_argument(
        "findings", type=Path, help="completed round whose recorded candidate needs re-application"
    )
    args = parser.parse_args()
    if not chdir_repo_root():
        return 2
    try:
        record = json.loads(receipt_path(args.findings).read_text())
        publish(args.story_id, record)
    except (OSError, ValueError, KeyError, CardEditRefusal) as error:
        print(f"refused: cannot re-apply completed review: {error}", file=sys.stderr)
        return 2
    return 0


def interrupted_problem(story_id: str, card: str, minted: dict) -> str:
    import shlex

    from work import data_root

    for path in (data_root() / "plans").glob(f"{story_id}.*.acceptance.json"):
        try:
            record = json.loads(path.read_text())
            if record["after"] == card and record["prior_digest"] == minted["digest"]:
                command = shlex.join(
                    [sys.executable, str(Path(__file__).resolve()), story_id, record["findings"]]
                )
                return (
                    f"refused: interrupted review acceptance; restore its recorded "
                    f"artifacts and re-apply the completed round with `{command}`"
                )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return ""


def restore_handoff(root: Path, story_id: str, prior: dict) -> bool:
    from handoff import effective_review, mark_plan_reviewed, mark_stage
    from plan_review import incomplete_marker

    effective = effective_review(root, story_id, prior)
    if effective == prior:
        return False
    mark_plan_reviewed(root, story_id, effective["plan_reviewed_card"])
    outcome = effective["stages"]["plan-reviewer"]
    mark_stage(root, story_id, "plan-reviewer", outcome)
    if outcome == "ran":
        incomplete_marker(story_id).unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    sys.exit(main())
