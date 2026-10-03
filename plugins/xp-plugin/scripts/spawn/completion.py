"""Select unfinished execution from actual run results in the story handoff."""

import subprocess
from pathlib import Path

from handoff import _write, handoff_state
from plan_acceptance import artifact_problem
from plan_confirmation import prior_binding, repository_fingerprint
from work import data_root, ready_marker_path

ORDER = ("executor", "story-tier", "reviewer")
RESULTS = ("pending", "running", "ran", "skipped", "blocked", "failed", "interrupted")


def inputs(story_id, card):
    from plan_acceptance import latest
    from plan_review import card_for
    from ready import credential, drift, plan_needs_replan
    from work import config_block_value

    accepted = latest(story_id)
    if accepted:
        prior_binding(accepted, Path(accepted["plan"]))
        if problem := artifact_problem(accepted):
            raise ValueError(problem)
    current = credential(ready_marker_path(story_id))
    if not current or card_for(story_id) != card:
        raise ValueError("executor declaration moved; inspect the card and resume")
    if accepted and plan_needs_replan(story_id, {}):
        raise ValueError("scope amended before execution; resume to run planning")
    if problem := drift(story_id, card):
        raise ValueError(problem)
    plan = Path(accepted["plan"]) if accepted else data_root() / "plans" / f"{story_id}.plan.md"
    fingerprint = repository_fingerprint(plan, tier_owned=True)
    return {
        "work": fingerprint["components"],
        "review": {
            key: accepted[key]
            for key in ("plan", "plan_identity", "findings", "findings_identity", "digest")
        }
        if accepted
        else None,
        "scope": len(current.get("amendments", [])),
        "tier": config_block_value("tests", "story"),
        "verify": [
            line for line in card.splitlines() if line.startswith(("Verify:", "Verify reads:"))
        ],
    }


def validate(story_id, prior):
    checkpoint = prior.get("checkpoint")
    if checkpoint is None:
        return {}
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("version") != 1
        or type(checkpoint.get("version")) is not int
        or checkpoint.get("story_id") != story_id
        or checkpoint.get("repository") != str(Path.cwd().resolve())
        or not isinstance(checkpoint.get("results"), dict)
    ):
        raise ValueError(
            "execution checkpoint binding is invalid; preserve evidence and restore the "
            "checkpoint before resuming executor"
        )
    results = checkpoint["results"]
    for stage, value in results.items():
        if stage not in ORDER or not isinstance(value, dict) or value.get("result") not in RESULTS:
            raise ValueError(
                f"invalid execution stage result {stage}; restore its checkpoint before resuming"
            )
        key = "output" if value["result"] in ("ran", "skipped") else "input"
        if value["result"] in RESULTS and (
            not isinstance(value.get(key), dict)
            or set(value[key]) != {"work", "review", "scope", "tier", "verify"}
        ):
            raise ValueError(
                f"missing execution stage evidence for {stage}; restore its checkpoint "
                f"before resuming"
            )
    return results


def next_stage(story_id, prior, current):
    results = validate(story_id, prior)
    sequence = prior.get("checkpoint", {}).get("review_sequence")
    if sequence:
        from review_sequence import check_reports

        check_reports(sequence)
        if sequence["status"] in ("blocked", "incomplete"):
            raise ValueError(
                f"lead handoff: {sequence.get('problem', 'incomplete review')}; "
                f"inspect work then explicitly run close.py review"
            )
        if sequence["status"] in ("validation", "validation-red", "awaiting-disposition"):
            return "reviewer"
    executor = results.get("executor", {})
    if executor.get("result") != "ran" or prior.get("stages", {}).get("executor") != "ran":
        return "executor"
    baseline = next(
        (
            results[name]["output"]
            for name in reversed(ORDER)
            if results.get(name, {}).get("result") in ("ran", "skipped")
        ),
        executor["output"],
    )
    if any(current[key] != baseline[key] for key in ("work", "review", "scope")):
        return "executor"
    reviewed = results.get("reviewer", {})
    if reviewed.get("result") == "blocked" and current["verify"] == reviewed["input"]["verify"]:
        raise ValueError("lead owns blocking review findings; explicitly review corrected work")
    tier = results.get("story-tier", {})
    if tier.get("result") in ("failed", "blocked"):
        return "executor"
    if tier.get("result") not in ("ran", "skipped") or current["tier"] != tier["output"]["tier"]:
        return "story-tier"
    return "reviewer"


def record(story_id, stage, result, snapshot):
    if stage not in ORDER or result not in RESULTS:
        raise ValueError(f"invalid execution result {stage}={result}")
    state = handoff_state(data_root(), story_id)
    if state is None:
        raise ValueError("handoff became unreadable; preserve it before resuming")
    state = state or {}
    validate(story_id, state)
    checkpoint = state.setdefault(
        "checkpoint",
        {
            "version": 1,
            "story_id": story_id,
            "repository": str(Path.cwd().resolve()),
            "results": {},
        },
    )
    results = checkpoint["results"]
    for later in ORDER[ORDER.index(stage) + 1 :]:
        results.pop(later, None)
        state.get("stages", {}).pop(later, None)
    results[stage] = {
        "result": result,
        "output" if result in ("ran", "skipped") else "input": snapshot,
    }
    state.setdefault("stages", {})[stage] = result
    _write(data_root(), story_id, state)


def committed_contents():
    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="xp-execution-") as directory:
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


def same_inputs(before, after):
    if any(before[key] != after[key] for key in before if key != "work"):
        return False
    old, new = before["work"], after["work"]
    if any(old[key] != new[key] for key in old if key != "contents"):
        return False
    current = {entry[0]: entry[1:] for entry in new["contents"]}
    return all(current.get(entry[0]) == entry[1:] for entry in old["contents"])
