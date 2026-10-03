"""Evidence-bound amendment confirmation through the existing review owner."""

import contextlib
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from plan_acceptance import atomic_json, identity, receipt_path
from plan_disposition import disposition_object, durable_disposition
from work import card_digest, data_root, ready_marker_path


def evidence_path(out):
    return Path(out).with_suffix(".evidence.json")


def metadata_identity(path):
    status = path.lstat()
    if stat.S_ISDIR(status.st_mode):
        return content_identity(path)
    value = json.dumps([status.st_size, status.st_mtime_ns, status.st_ino]).encode()
    return status.st_mode, hashlib.sha256(value).hexdigest()


def content_identity(path):
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        value = os.fsencode(os.readlink(path))
    elif stat.S_ISREG(mode):
        value = path.read_bytes()
    elif stat.S_ISDIR(mode):
        # Git exposes a submodule or embedded repository as one directory entry.
        # Its administrative .git file/directory is not reviewed source evidence.
        value = json.dumps(
            [
                (os.fsencode(p.name).hex(), content_identity(p))
                for p in sorted(path.iterdir())
                if p.name != ".git"
            ]
        ).encode()
    else:
        raise OSError(f"cannot measure file kind at {path}; inspect before replanning")
    return mode, hashlib.sha256(value).hexdigest()


def repository_fingerprint(plan_file):
    root = Path.cwd().resolve()
    excluded = Path(plan_file).resolve()
    relative = str(excluded.relative_to(root)) if excluded.is_relative_to(root) else None
    paths = [".", f":(exclude,literal){relative}"] if relative else ["."]

    def git(*args):
        result = subprocess.run(
            ["git", "-c", "diff.autoRefreshIndex=false", *args], capture_output=True
        )
        if result.returncode:
            raise OSError(result.stderr.decode(errors="replace"))
        return result.stdout

    measured = {
        "head": git("rev-parse", "HEAD").hex(),
        "index": git("ls-files", "--stage", "-z", "--", *paths).hex(),
        "staged": git(
            "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "--", *paths
        ).hex(),
        "worktree": git("diff", "--binary", "--no-ext-diff", "--no-textconv", "--", *paths).hex(),
    }
    tracked = git("ls-files", "-z", "--", *paths).split(b"\0")
    untracked = git("ls-files", "--others", "-z", "--", *paths).split(b"\0")
    ignored = set(
        git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *paths).split(
            b"\0"
        )
    )
    contents = []
    for name in sorted(set(tracked + untracked) - {b""}):
        path = root / os.fsdecode(name)
        try:
            # Ignored trees (node_modules) hold ~10^5 files; opening each costs minutes
            # under endpoint scanning, so a rewrite is caught by its metadata instead.
            mode, digest = (metadata_identity if name in ignored else content_identity)(path)
        except FileNotFoundError:
            contents.append([name.hex(), "absent"])
            continue
        contents.append([name.hex(), mode, digest])
    measured["contents"] = contents
    return {
        "repository": str(root),
        "components": measured,
        "identity": hashlib.sha256(
            json.dumps({"repository": str(root), **measured}, sort_keys=True).encode()
        ).hexdigest(),
    }


def record_evidence(record, fingerprint):
    from ready import credential

    minted = credential(ready_marker_path(record["story_id"]))
    if not minted or minted["digest"] not in (record["digest"], record["prior_digest"]):
        raise ValueError("credential moved before evidence publication")
    atomic_json(
        evidence_path(record["findings"]),
        {
            "version": 1,
            "acceptance": record,
            "repository": fingerprint,
            "amendment_count": record["amendment_count"],
            "credential_digest": record["digest"],
        },
    )


def preserve(story_id, plan_file):
    """Copy before any writer; identical retries reuse immutable snapshots."""
    parent = data_root() / "plans"
    paths = {Path(plan_file)} | {
        p for p in parent.glob(f"{story_id}.*") if p.is_file() and p.suffix != ".part"
    }
    entries, contents = [], {}
    for path in sorted(paths):
        if not path.exists():
            entries.append({"source": str(path), "state": "missing"})
            continue
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        entries.append({"source": str(path), "identity": digest, "state": "preserved"})
        contents[digest] = body
    key = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    target = parent / f"{story_id}.predecessors" / key
    target.mkdir(parents=True, exist_ok=True)
    for digest, body in contents.items():
        path = target / digest
        if path.exists():
            if path.read_bytes() != body:
                raise ValueError(f"predecessor snapshot changed: restore {path}")
        else:
            with path.open("xb") as handle:
                handle.write(body)
    manifest = target / "manifest.json"
    for entry in entries:
        if entry["state"] == "preserved":
            entry["snapshot"] = str(target / entry["identity"])
    if manifest.exists():
        if json.loads(manifest.read_text()) != entries:
            raise ValueError(f"predecessor manifest changed: restore {manifest}")
    else:
        manifest.write_text(json.dumps(entries))
    from handoff import _write, handoff_state

    state = handoff_state(data_root(), story_id) or {}
    state["predecessors"] = list(dict.fromkeys([*state.get("predecessors", []), str(manifest)]))
    _write(data_root(), story_id, state)
    return manifest


def prior_binding(record, plan_file):
    if Path(record["plan"]).resolve() != Path(plan_file).resolve():
        raise ValueError("accepted draft path binding changed")
    if json.loads(receipt_path(Path(record["findings"])).read_text()) != record:
        raise ValueError("acceptance receipt binding changed")
    if Path(record["candidate"]).read_text() != record["after"]:
        raise ValueError("reviewed card candidate binding changed")


def eligibility(story_id, prior, plan_file):
    """Return mode, bundle, reason: confirm, fallback or refuse."""
    from plan_acceptance import latest
    from ready import card_diff, credential

    minted = credential(ready_marker_path(story_id))
    record = latest(story_id)
    if not minted:
        return "refuse", None, "ready credential unreadable; restore it before resuming"
    if not record:
        return (
            "fallback",
            None,
            "legacy-unbound review has no acceptance; planner and full review required",
        )
    if record["digest"] == minted["digest"] and not pending_amendment(story_id):
        return "unchanged", None, ""
    try:
        prior_binding(record, plan_file)
        findings = Path(record["findings"]).read_text()
        if identity(Path(record["findings"])) != record["findings_identity"]:
            raise ValueError("accepted findings changed")
        outcome, problem = durable_disposition(findings)
        if outcome == "failed":
            raise ValueError(problem)
    except (OSError, UnicodeError, ValueError) as error:
        return (
            "refuse",
            None,
            f"cannot reuse authoritative findings: {error}; restore {record['findings']}",
        )
    try:
        draft = Path(plan_file).read_text()
        if not draft.strip():
            raise ValueError("empty draft")
        if identity(Path(plan_file)) != record["plan_identity"]:
            return "refuse", None, f"accepted draft changed; restore {plan_file} before resuming"
    except (OSError, UnicodeError, ValueError) as error:
        return "fallback", None, f"cannot reuse draft: {error}; planner and full review required"
    try:
        evidence_file = evidence_path(record["findings"])
        if prior.get("plan_review_evidence_identity") != identity(evidence_file):
            raise ValueError("repository evidence identity changed or unbound")
        evidence = json.loads(evidence_file.read_text())
        if evidence["version"] != 1 or evidence["acceptance"] != record:
            raise ValueError("evidence binding/version mismatch")
        if evidence["credential_digest"] != record["digest"]:
            raise ValueError("prior credential binding mismatch")
        if (
            prior.get("plan_review_identity") != record["findings_identity"]
            or prior.get("plan_reviewed_card") != record["digest"]
        ):
            raise ValueError("handoff acceptance binding mismatch")
        from plan_review import card_for

        if card_digest(card_for(story_id)) != minted["digest"]:
            raise ValueError("current card is not credentialed")
        fingerprint = repository_fingerprint(plan_file)
        from completion import review_limit, validate

        completed, limit = validate(story_id, prior, record)
        if completed and (limit := review_limit(story_id)):
            completed = None
        baseline = completed["fingerprint"] if completed else evidence["repository"]
        if fingerprint != baseline:
            raise ValueError(limit or "repository evidence changed")
        chain = minted.get("amendments", [])[evidence["amendment_count"] :]
        current = record["after"]
        if not chain:
            raise ValueError("no explicit amendment chain")
        for amendment in chain:
            if card_digest(amendment["card"]) != card_digest(current):
                raise ValueError("amendment chain gap")
            current = amendment["after"]
        if card_digest(current) != minted["digest"]:
            raise ValueError("amendment chain does not reach current credential")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        return "fallback", None, f"cannot reuse evidence: {error}; planner and full review required"
    bundle = {
        "completion": completed,
        "record": record,
        "minted": minted,
        "fingerprint": fingerprint,
        "prior_card": record["after"],
        "current_card": minted["card"],
        "amendments": chain,
        "delta": card_diff(record["after"], minted["card"]),
        "findings": findings,
        "evidence": evidence,
        "evidence_identity": identity(evidence_file),
    }
    return "confirm", bundle, ""


def confirmation_decision(findings):
    report, problem = disposition_object(findings)
    if problem:
        return "", problem
    decision = report.get("decision")
    if decision not in ("confirm", "replan"):
        return "", "confirmation requires explicit decision confirm or replan; repair and resume"
    summary = report.get("summary")
    if decision == "replan" and (not isinstance(summary, str) or not summary.strip()):
        return (
            "",
            "replan requires an explanation of why the existing plan cannot serve the amendment",
        )
    return decision, ""


def recheck(story_id, plan_file, context):
    from ready import credential

    if credential(ready_marker_path(story_id)) != context["minted"]:
        raise ValueError("credential changed during confirmation; inspect amendment and resume")
    from plan_review import card_for

    if card_for(story_id) != context["current_card"]:
        raise ValueError("card changed during confirmation; inspect amendment and resume")
    if context.get("completion"):
        from handoff import handoff_state

        if (handoff_state(data_root(), story_id) or {}).get("completion") != context["completion"]:
            raise ValueError("completion evidence changed during confirmation")
    record = context["record"]
    prior_binding(record, plan_file)
    if identity(Path(record["findings"])) != record["findings_identity"]:
        raise ValueError("prior findings changed during confirmation; restore them before resuming")
    if identity(evidence_path(record["findings"])) != context["evidence_identity"]:
        raise ValueError("prior evidence changed during confirmation; restore it before resuming")
    if repository_fingerprint(plan_file) != context["fingerprint"]:
        raise ValueError(
            "repository changed during confirmation; inspect and restore before resuming"
        )


def run(story_id, plan_file, context):
    import plan_review
    import review

    manifest = preserve(story_id, plan_file)
    parent = data_root() / "plans"
    number = 1
    while any(parent.glob(f"{story_id}.confirmation-{number}.*")):
        number += 1
    out = parent / f"{story_id}.confirmation-{number}.md"
    marker = plan_review.incomplete_marker(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "kind": "confirmation",
                "findings": str(out),
                "state": "PLAN CONFIRMATION DID NOT COMPLETE",
                "next": f"run spawn.py resume {story_id}",
            }
        )
    )
    prior = (
        "CONFIRMATION_MODE: amendment\n"
        "Judge the exact amendment/ruling against the preserved plan; apply an authorized answer "
        "to the draft or explicitly require replan. Preserve justified edits and reasons. "
        "New reserved choices block, and silent/corrupting defects remain in your authority.\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + f"\nImmutable predecessor manifest: {manifest}\n"
    )
    charter = review.charter("plan-reviewer")
    if not charter:
        return plan_review.fail("restore the empty plan-reviewer charter"), "failed"
    import re

    def mode_example(match):
        report = json.loads(match.group(1))
        return "```json\n" + json.dumps(report | {"decision": "confirm"}) + "\n```"

    charter = re.sub(r"```json\n(.*?)```", mode_example, charter, flags=re.S)
    result = plan_review._run_review(
        story_id,
        plan_file,
        charter,
        plan_file.read_text(),
        plan_review.card_for(story_id),
        out,
        False,
        prior,
        True,
        confirmation=context,
    )

    if context.get("completion") and result[0] == 0 and result[1] != "replan":
        from completion import digest, save

        report, problem = disposition_object(out.read_text())
        implementation = report.get("implementation") if not problem else None
        if "implementation" in report and implementation not in ("complete", "requires-execution"):
            return plan_review.ReviewResult(
                plan_review.fail("invalid implementation judgment; repair and resume"),
                "failed",
                result.acceptance,
            )
        if implementation == "complete":
            if not isinstance(report.get("summary"), str) or not report["summary"].strip():
                return plan_review.ReviewResult(
                    plan_review.fail(
                        "complete implementation judgment requires a summary; repair and resume"
                    ),
                    "failed",
                    result.acceptance,
                )
            value = context["completion"]
            if repository_fingerprint(plan_file) != context["fingerprint"]:
                return plan_review.ReviewResult(
                    plan_review.fail("completed tree moved after confirmation; inspect and resume"),
                    "failed",
                    result.acceptance,
                )
            from handoff import handoff_state

            if (handoff_state(data_root(), story_id) or {}).get("completion") != value:
                return plan_review.ReviewResult(
                    plan_review.fail("completion moved after confirmation; inspect and resume"),
                    "failed",
                    result.acceptance,
                )
            save(story_id, value, {"completion": digest(value), "acceptance": result.acceptance})
    return result


def execution_problem(record):
    from handoff import handoff_state

    try:
        handoff = handoff_state(data_root(), record["story_id"]) or {}
        if identity(evidence_path(record["findings"])) != handoff.get(
            "plan_review_evidence_identity"
        ):
            raise ValueError("published evidence identity changed")
        evidence = json.loads(evidence_path(record["findings"]).read_text())
        if evidence["acceptance"] != record:
            raise ValueError("acceptance evidence binding changed")
        if repository_fingerprint(Path(record["plan"])) != evidence["repository"]:
            raise ValueError("repository moved after plan review")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f"cannot certify reviewed evidence: {error}; restore evidence and resume"
    return ""


def pending_amendment(story_id):
    from plan_acceptance import latest
    from ready import credential

    record = latest(story_id)
    minted = credential(ready_marker_path(story_id))
    if not record or not minted:
        return False
    count = record.get("amendment_count")
    try:
        if count is None:
            count = json.loads(evidence_path(record["findings"]).read_text())["amendment_count"]
        return len(minted.get("amendments", [])) > count
    except (OSError, ValueError, KeyError, TypeError):
        return bool(minted.get("amendments"))


def publication_problem(record):
    if "repository_identity" not in record:
        return ""
    try:
        evidence = json.loads(evidence_path(record["findings"]).read_text())
        if evidence["acceptance"] != record:
            raise ValueError("measured acceptance binding changed")
        with contextlib.chdir(evidence["repository"]["repository"]):
            fingerprint = repository_fingerprint(Path(record["plan"]))
        if (
            fingerprint["identity"] != record["repository_identity"]
            or fingerprint != evidence["repository"]
        ):
            raise ValueError("repository moved since measured plan review")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f"cannot publish measured plan review: {error}; restore the measured tree/artifacts"
    return ""
