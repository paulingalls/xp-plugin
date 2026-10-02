"""Completed execution credentials, distinct from historical stage labels."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(story_id, value=None, judgment=None):
    from handoff import _write, handoff_state
    from work import data_root

    state = handoff_state(data_root(), story_id) or {}
    state.pop("completion", None)
    state.pop("completion_judgment", None)
    if value is not None:
        state["completion"] = value
    if judgment is not None:
        state["completion_judgment"] = judgment
    _write(data_root(), story_id, state)


def committed_contents():
    with tempfile.TemporaryDirectory(prefix="xp-completion-") as directory:
        environment = os.environ | {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.sparseCheckout=false",
            "-c",
            "core.splitIndex=false",
            "-c",
            "core.ignorestat=false",
        ]
        try:
            subprocess.run(
                [*command, "read-tree", "HEAD"],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            diff = subprocess.run(
                [
                    *command,
                    "diff",
                    "--name-only",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--ignore-submodules=none",
                    "HEAD",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            raise OSError(error.stderr.strip()) from error
        if diff.stdout:
            raise ValueError(f"tracked executor bytes differ from HEAD: {diff.stdout.strip()}")


def measure(plan):
    from handback import tree_state
    from plan_confirmation import repository_fingerprint

    head, dirty = tree_state(Path.cwd())
    if dirty:
        raise ValueError("completed tree is dirty")
    committed_contents()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    return head, tree, repository_fingerprint(plan)


def gates(card):
    from work import config_block_value

    lines = card.splitlines()
    return {
        "tier": config_block_value("tests", "story"),
        "config": config_block_value("tests"),
        "verify": [line for line in lines if line.startswith(("Verify:", "Verify reads:"))],
    }


def capture(story_id, start, accepted, tier, executed):
    from plan_acceptance import artifact_problem
    from plan_confirmation import evidence_path
    from plan_review import card_for
    from ready import card_growth, credential
    from work import card_digest, ready_marker_path

    if not accepted or tier[0] != "passed":
        return
    if problem := artifact_problem(accepted):
        raise ValueError(problem)
    card = card_for(story_id)
    minted = credential(ready_marker_path(story_id))
    if (
        not minted
        or minted["digest"] != accepted["digest"]
        or (card_digest(card) != accepted["digest"] and not card_growth(accepted["after"], card))
    ):
        raise ValueError("completed card changed since accepted review")
    plan = Path(accepted["plan"])
    head, tree, fingerprint = measure(plan)
    if (head, tree, fingerprint) != executed:
        raise ValueError("tree moved during story tier")
    if head == start:
        raise ValueError("completed executor has no own commit")
    gate = gates(card)
    if gate["tier"] != tier[1]:
        raise ValueError("story tier changed during execution")
    value = {
        "version": 1,
        "story_id": story_id,
        "start_head": start,
        "head": head,
        "tree": tree,
        "repository": str(Path.cwd().resolve()),
        "fingerprint": fingerprint,
        "acceptance": accepted,
        "card": card,
        "card_digest": card_digest(card),
        "credential": minted,
        "plan": plan.read_text(),
        "findings": Path(accepted["findings"]).read_text(),
        "review_evidence": json.loads(evidence_path(accepted["findings"]).read_text()),
        "gates": gate,
    }
    if (
        measure(plan) != (head, tree, fingerprint)
        or card_for(story_id) != card
        or credential(ready_marker_path(story_id)) != minted
        or gates(card) != gate
        or artifact_problem(accepted)
    ):
        raise ValueError("completed tree or gates moved before publication")
    save(story_id, value)


def validate(story_id, prior, accepted):
    """Return a bound completion or a named conservative evidence limit."""
    from plan_acceptance import artifact_problem
    from plan_confirmation import evidence_path, prior_binding
    from ready import card_growth
    from work import card_digest

    value = prior.get("completion")
    if value is None:
        return None, "completed executor evidence is absent"
    try:
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value["version"] != 1
        ):
            raise ValueError("completion shape/version is invalid")
        original = value["acceptance"]
        prior_binding(original, Path(original["plan"]))
        if value["story_id"] != story_id or original["story_id"] != story_id:
            raise ValueError("completion story binding changed")
        if value["repository"] != str(Path.cwd().resolve()):
            raise ValueError("completion repository binding changed")
        for key in ("start_head", "head", "tree"):
            size = 40
            if (
                not isinstance(value[key], str)
                or len(value[key]) != size
                or any(c not in "0123456789abcdef" for c in value[key])
            ):
                raise ValueError(f"completion {key} is invalid")
        if value["start_head"] == value["head"]:
            raise ValueError("completion has no own executor commit")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", value["start_head"], value["head"]],
            check=True,
            capture_output=True,
        )
        if card_digest(value["card"]) != value["card_digest"] or (
            card_digest(value["card"]) != original["digest"]
            and not card_growth(original["after"], value["card"])
        ):
            raise ValueError("completion implemented card binding changed")
        if (
            value["credential"]["digest"] != original["digest"]
            or len(value["credential"].get("amendments", [])) != original["amendment_count"]
        ):
            raise ValueError("completion amendment binding changed")
        for key in ("plan", "findings"):
            if (
                not isinstance(value[key], str)
                or hashlib.sha256(value[key].encode()).hexdigest() != original[key + "_identity"]
            ):
                raise ValueError(f"completion {key} binding changed")
        evidence = value["review_evidence"]
        if (
            evidence != json.loads(evidence_path(original["findings"]).read_text())
            or evidence["version"] != 1
            or evidence["acceptance"] != original
            or evidence["credential_digest"] != original["digest"]
        ):
            raise ValueError("completion prior review evidence changed")
        gate = value["gates"]
        if (
            not isinstance(gate, dict)
            or not isinstance(gate["tier"], str)
            or gate["tier"] in ("", "EDIT-ME")
            or not isinstance(gate["config"], dict)
            or not isinstance(gate["verify"], list)
        ):
            raise ValueError("completion passed tier evidence is invalid")
        if gate != gates(value["card"]):
            raise ValueError("completion gate declarations changed")
        if not accepted:
            raise ValueError("completion current acceptance is absent")
        if problem := artifact_problem(accepted):
            raise ValueError(problem)
        if accepted != original:
            judgment = prior.get("completion_judgment")
            if not judgment or judgment != {"completion": digest(value), "acceptance": accepted}:
                raise ValueError("completion accepted judgment binding changed")
            report = json.loads(evidence_path(accepted["findings"]).read_text())
            if report["acceptance"] != accepted or report["repository"] != value["fingerprint"]:
                raise ValueError("completion confirmation evidence changed")
            from plan_disposition import disposition_object, durable_disposition

            findings = Path(accepted["findings"]).read_text()
            decision, problem = disposition_object(findings)
            if (
                problem
                or decision.get("implementation") != "complete"
                or decision.get("decision") != "confirm"
                or durable_disposition(findings)[1]
            ):
                raise ValueError("completion lacks an unblocked implementation judgment")
        head, tree, fingerprint = measure(Path(accepted["plan"]))
        if (head, tree, fingerprint) != (value["head"], value["tree"], value["fingerprint"]):
            raise ValueError("completion HEAD/tree/content binding changed")
        return value, ""
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        return None, f"cannot reuse completed executor evidence: {error}"


def review_problem(story_id, expected):
    from handoff import handoff_state
    from plan_acceptance import latest
    from plan_confirmation import pending_amendment
    from plan_review import card_for
    from ready import credential
    from work import data_root, ready_marker_path

    prior, accepted, card, minted = expected
    now = handoff_state(data_root(), story_id) or {}
    value, problem = validate(story_id, now, accepted)
    if not value:
        return problem
    if (
        now.get("completion") != prior.get("completion")
        or now.get("completion_judgment") != prior.get("completion_judgment")
        or latest(story_id) != accepted
        or card_for(story_id) != card
        or credential(ready_marker_path(story_id)) != minted
        or pending_amendment(story_id)
        or review_limit(story_id)
    ):
        return "completed judgment moved at the diff-review boundary"
    return ""


def review_limit(story_id):
    from close import marker_path
    from handoff import handoff_state
    from overlap import unresolved_blocking
    from work import data_root

    reviewed = (handoff_state(data_root(), story_id) or {}).get("stages", {}).get(
        "reviewer"
    ) == "ran"
    path = marker_path(story_id)
    if not path.exists():
        return "prior diff-review evidence is absent; executor required" if reviewed else ""
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict) or (reviewed and not state.get("rounds")):
            return "prior diff-review evidence is incomplete; executor required"
        if unresolved_blocking(state):
            return "unresolved diff-review blockers require execution"
    except (OSError, ValueError, TypeError, AttributeError):
        return "prior diff-review evidence is unreadable; restore it before review"
    return ""


def reuse(story_id, prior, accepted, card):
    from plan_review import card_for
    from ready import credential
    from work import card_digest, ready_marker_path

    value, problem = validate(story_id, prior, accepted)
    if problem:
        return False, problem
    minted = credential(ready_marker_path(story_id))
    if (
        not minted
        or minted["digest"] != accepted["digest"]
        or (card_digest(card) != accepted["digest"] and card != value["card"])
        or card_for(story_id) != card
    ):
        return False, "completion current card/credential moved"
    if limit := review_limit(story_id):
        return False, limit
    current = gates(card)
    if current != value["gates"]:
        from handback import story_tier
        from review_launch import verify_on_reviewed_tree

        if (current["tier"], current["config"]) != (
            value["gates"]["tier"],
            value["gates"]["config"],
        ):
            tier = story_tier(Path.cwd())
            if tier[0] != "passed":
                save(story_id)
                raise ValueError(f"changed story tier {tier[0]}: {tier[1]!r}\n{tier[2]}")
        if current["verify"] != value["gates"]["verify"] and (
            problem := verify_on_reviewed_tree(story_id, card)
        ):
            save(story_id)
            raise ValueError(f"changed Verify failed: {problem}")
    from handoff import handoff_state
    from work import data_root

    now = handoff_state(data_root(), story_id) or {}
    intact, problem = validate(story_id, now, accepted)
    if (
        not intact
        or now.get("completion") != value
        or gates(card_for(story_id)) != current
        or credential(ready_marker_path(story_id)) != minted
    ):
        save(story_id)
        raise ValueError(problem or "completed judgment moved before diff review")
    return True, ""
