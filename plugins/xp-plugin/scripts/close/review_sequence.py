"""One-pass solution review stored in the authoritative execution checkpoint."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spawn"))

import close
import review
from bookkeep import fork_point
from completion import inputs
from handoff import _write, handoff_state
from work import data_root


def load(story_id):
    state = handoff_state(data_root(), story_id)
    if state is None:
        raise ValueError("unreadable handoff; restore its preserved bytes")
    return (state or {}).get("checkpoint", {}).get("review_sequence")


def save(story_id, sequence):
    state = handoff_state(data_root(), story_id)
    if state is None:
        raise ValueError("unreadable handoff; restore its preserved bytes")
    state = state or {}
    checkpoint = state.setdefault(
        "checkpoint",
        {
            "version": 1,
            "story_id": story_id,
            "repository": str(Path.cwd().resolve()),
            "results": {},
        },
    )
    previous = checkpoint.get("review_sequence")
    if previous and previous.get("id") != sequence.get("id"):
        checkpoint.setdefault("review_history", []).append(previous)
    checkpoint["review_sequence"] = sequence
    _write(data_root(), story_id, state)


def measure(story_id, card):
    return {
        "head": close.git("rev-parse", "HEAD").stdout.strip(),
        "tree": close.git("write-tree").stdout.strip(),
        "inputs": inputs(story_id, card),
    }


def problem(story_id, sequence, stage, why, kind="blocked"):
    sequence.update(status=kind, problem=f"{stage}: {why}", producer=stage)
    save(story_id, sequence)
    return close.fail(
        f"refused: {sequence['problem']}. Work and reports retained. Lead: "
        f"inspect and correct, then `xp.py {close.leg(story_id)[0]} review`."
    )


def binding(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_reports(sequence):
    for name, stage in sequence["stages"].items():
        if stage["status"] == "completed" and binding(Path(stage["path"])) != stage["identity"]:
            raise ValueError(f"{name} report changed; restore its bound bytes at {stage['path']}")


def stage(story_id, card, sequence, name, correction=False):
    previous = sequence["stages"].get(name, {})
    attempt = previous.get("attempt", 0) + 1
    root = data_root() / "reports"
    root.mkdir(parents=True, exist_ok=True)
    path = (
        review.report_path(story_id, sequence["round"])
        if name == "solution" and attempt == 1
        else root / f"{story_id}.round-{sequence['round']}.{name}-{attempt}.json"
    )
    while path.exists():
        attempt += 1
        path = root / f"{story_id}.round-{sequence['round']}.{name}-{attempt}.json"
    before = measure(story_id, card)
    marker = close.marker_path(story_id)
    digest = review.marker_digest(marker)
    item = {
        "status": "running",
        "attempt": attempt,
        "path": str(path),
        "log": str(data_root() / "logs" / (path.stem + ".log")),
        "before": before,
        "prior_attempts": previous.get("prior_attempts", []) + ([previous] if previous else []),
    }
    sequence["stages"][name] = item
    sequence["status"] = "running"
    save(story_id, sequence)
    if name == "solution":
        marker_state = json.loads(marker.read_text()) if marker.exists() else {}
        from bookkeep import render_prior_rounds

        notice = review.plan_review_notice(story_id)
        if notice:
            print(notice, file=sys.stderr)
        prompt = close.build_bundle(
            card,
            sequence["base"],
            path,
            render_prior_rounds(marker_state.get("rounds", [])),
            notice,
        )
    else:
        charter = (
            "Read VALUES and JUDGMENT. Fix only the supplied authorized findings. "
            "Use red-green-refactor, run the card Verify and configured story tier, then "
            "commit through normal Git hooks using the repository identity. "
            "Never bypass hooks or change the card/close marker. Preserve failed work. "
            "Write JSON with blocking findings; optional fixed, dropped and debt explain decisions."
            if name == "fixer"
            else "Read-only narrow closure: check these fixes and concrete regressions. "
            "Do not reopen general design review. Write JSON with blocking findings."
        )
        prompt = f"## Your charter\n{charter}\n## Story card\n{card}\n"
        prompt += "## Completed solution findings and fix evidence\n" + json.dumps(
            sequence["stages"]
        )
        prompt += f"\nREPORT_PATH: {path}\n"
        for title, authority in close.review_authority_sections():
            prompt += f"\n## {title}\n{authority}\n"
        prompt += f"\n## Fix diff\n{close.git('diff', sequence['start']['head'], 'HEAD').stdout}"
    if correction:
        prompt += (
            "\nCorrect only the incomplete report using retained work and logs. "
            "Do not edit or commit again. Prior producer attempt:\n" + json.dumps(previous)
        )
    prompt += f"\nSTAGE: {name}\n"
    from review_cancel import card_changed
    from teammate_tee import ReviewCancelled

    try:
        result, error = review.run(
            prompt,
            Path.cwd(),
            card=card,
            role=name if name in ("fixer", "closer") and not correction else "reviewer",
            noun=close.leg(story_id)[0],
            cancel=card_changed(story_id, card),
            log_id=path.stem,
        )
    except ReviewCancelled as cancelled:
        item["status"] = "failed"
        work = close.git("status", "--porcelain").stdout.strip()
        commits = close.git("log", "--oneline", before["head"] + "..HEAD").stdout.strip()
        return problem(
            story_id,
            sequence,
            name,
            f"CANCELLED: card changed; log {cancelled.log}; "
            f"retained work {work}; commits {commits}",
        )
    print(result)
    try:
        after = measure(story_id, card)
    except ValueError as changed:
        item["status"] = "failed"
        return problem(story_id, sequence, name, str(changed))
    item["after"] = after
    sequence["output"] = after
    if name != "fixer" or correction:
        motion = review.check_reviewer_motion(before["head"], marker, digest, card, story_id)
        if after != before:
            motion = motion or "read-only stage changed its source/index/runtime inputs"
    else:
        motion = ""
        if close.git("status", "--porcelain").stdout.strip():
            motion = "fixer left uncommitted work; inspect and commit the retained tree"
        elif before["head"] == after["head"]:
            motion = "fixer committed no correction"
        elif close.git(
            "merge-base", "--is-ancestor", before["head"], after["head"], check=False
        ).returncode:
            motion = "fixer rewrote the solution ancestry"
        elif review.marker_digest(marker) != digest or review.card_now(story_id) != card:
            motion = "fixer changed its card or close marker"
    if name == "fixer" and not correction and not motion:
        from completion import committed_contents
        from review_scope import declared_files

        committed_contents()
        touched = close.git(
            "diff", "--name-only", "--no-renames", before["head"], after["head"]
        ).stdout.splitlines()
        if any(path.startswith(".xp/") and path not in declared_files(card) for path in touched):
            motion = "fixer committed an undeclared .xp path; lead must inspect the retained commit"
    if motion or error:
        item["status"] = "failed"
        return problem(story_id, sequence, name, motion or error)
    report, error = review.read_report(path, stage=name)
    if error:
        item["status"] = "incomplete"
        return problem(story_id, sequence, name, f"{error}; report {path}", "incomplete")
    item.update(status="completed", report=report, identity=binding(path))
    save(story_id, sequence)
    if report["blocking"] and name != "solution":
        return problem(story_id, sequence, name, "; ".join(report["blocking"]))
    return 0


def run(story_id, card, trunk, dry_run=False, explicit=True):
    from review_validation import validate

    if dry_run:
        base, error = fork_point(trunk)
        if error:
            return close.fail(error)
        _, error = review.run(
            close.build_bundle(card, base, data_root() / "reports/preview.json"),
            Path.cwd(),
            True,
            card=card,
        )
        return close.fail(error) if error else 0
    current = measure(story_id, card)
    sequence = load(story_id)
    reuse = (
        sequence
        and sequence["card"] == card
        and sequence["output"] == current
        and not (explicit and sequence["status"] == "completed")
    )
    if reuse:
        check_reports(sequence)
        if sequence["status"] == "completed" and not explicit:
            return 0
        if sequence["status"] == "blocked":
            return close.fail(
                f"refused: lead handoff: {sequence['problem']}; "
                "commit correction then explicitly review"
            )
        if sequence["status"] == "incomplete":
            if not explicit:
                return close.fail(
                    f"refused: lead must correct {sequence['producer']} output with "
                    f"`xp.py {close.leg(story_id)[0]} review`"
                )
            if rc := stage(story_id, card, sequence, sequence["producer"], correction=True):
                return rc
        if sequence["status"] in ("validation", "validation-red", "awaiting-disposition"):
            return validate(story_id, card, sequence)
    else:
        if not explicit and sequence and sequence["status"] != "completed":
            return close.fail(
                "refused: reviewed inputs moved; lead must explicitly review corrected work"
            )
        base, refusal = fork_point(trunk)
        if refusal:
            return close.fail(refusal)
        marker = close.marker_path(story_id)
        rounds = json.loads(marker.read_text()).get("rounds", []) if marker.exists() else []
        import uuid

        sequence = {
            "id": uuid.uuid4().hex,
            "status": "running",
            "card": card,
            "base": base,
            "start": current,
            "output": current,
            "round": len(rounds) + 1,
            "stages": {},
            "validation": [],
        }
        if dry_run:
            return (
                close.fail(error)
                if (
                    error := review.run(
                        close.build_bundle(
                            card, base, review.report_path(story_id, sequence["round"])
                        ),
                        Path.cwd(),
                        True,
                        card=card,
                    )[1]
                )
                else 0
            )
        save(story_id, sequence)
    for name in ("solution", "fixer", "closer"):
        prior = sequence["stages"].get(name, {})
        if prior.get("status") in ("completed", "skipped"):
            continue
        if prior.get("status") == "running":
            return problem(
                story_id,
                sequence,
                name,
                "interrupted producer; inspect its report and retained work",
                "incomplete",
            )
        if name != "solution" and not sequence["stages"]["solution"]["report"]["actionable"]:
            sequence["stages"][name] = {"status": "skipped"}
            save(story_id, sequence)
            continue
        if rc := stage(story_id, card, sequence, name):
            return rc
    solution = sequence["stages"]["solution"]["report"]
    reports = [
        item["report"] for item in sequence["stages"].values() if item["status"] == "completed"
    ]
    from review_report import aggregate

    report = aggregate(reports)
    report["blocking"] = solution["blocking"]
    marker = close.marker_path(story_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    if not any(r.get("sequence_round") == sequence["round"] for r in state.get("rounds", [])):
        review.write_round(
            marker,
            state,
            report,
            reviewed_head=sequence["start"]["head"],
            shown_sha=sequence["output"]["head"],
            review_base=sequence["base"],
            branch=close.git("branch", "--show-current").stdout.strip(),
            sequence_round=sequence["round"],
        )
    sequence["marker_identity"] = review.marker_digest(marker)
    if solution["blocking"]:
        return problem(story_id, sequence, "solution", "; ".join(solution["blocking"]))
    sequence["status"] = "validation"
    save(story_id, sequence)
    return validate(story_id, card, sequence)


def locked(story_id, action, held=None):
    import resume

    owner = held is None
    if owner:
        held, refusal = resume.acquire(data_root(), story_id)
        if refusal:
            return close.fail(refusal)
    elif not resume.owns(held, data_root(), story_id):
        return close.fail("refused: invalid launch lock ownership")
    try:
        return action()
    except (OSError, ValueError, KeyError) as error:
        return close.fail(f"refused: review evidence: {error}; preserve work and ask the lead")
    finally:
        if owner:
            held.close()
