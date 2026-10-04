"""Select unfinished execution from actual run results in the story handoff."""

from pathlib import Path

from handoff import _write, handoff_state
from plan_acceptance import artifact_problem
from plan_confirmation import prior_binding
from work import data_root, ready_marker_path

ORDER = ("executor", "story-tier", "reviewer")
RESULTS = ("pending", "running", "ran", "skipped", "blocked", "failed", "interrupted")


def config_without_story():
    from work import strip_comment

    config = Path(".xp/config.yml")
    if not config.exists():
        return None
    retained = []
    inside = False
    for raw in config.read_text().splitlines(keepends=True):
        line = strip_comment(raw)
        if line.rstrip() == "tests:":
            inside = True
        elif inside and line.strip() and not line[:1].isspace():
            inside = False
        elif inside and ":" in line and line.strip().split(":", 1)[0] == "story":
            continue
        retained.append(raw)
    return "".join(retained)


def inputs(story_id, card, *, declaration_checked=False):
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
    if not declaration_checked and (problem := drift(story_id, card)):
        raise ValueError(problem)
    plan = Path(accepted["plan"]) if accepted else data_root() / "plans" / f"{story_id}.plan.md"
    from git_source import facts

    root = Path.cwd().resolve()
    excluded = (
        [str(plan.resolve().relative_to(root))] if plan.resolve().is_relative_to(root) else []
    )
    work = facts(excluded)
    work["config_without_story"] = config_without_story()
    return {
        "work": work,
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


def validate(story_id, prior, *, check_repository=True):
    checkpoint = prior.get("checkpoint")
    if checkpoint is None:
        return {}
    if isinstance(checkpoint, dict) and checkpoint.get("version") == 1:
        raise ValueError(
            "inventory checkpoint version 1 is retired; preserve this handoff and reports. "
            "Lead: inspect retained work and authorize a fresh run "
            "after preserving the predecessor; "
            "do not replay completed fixes to rebuild evidence"
        )
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("version") != 2
        or type(checkpoint.get("version")) is not int
        or checkpoint.get("story_id") != story_id
        or not isinstance(checkpoint.get("repository"), str)
        or (check_repository and checkpoint.get("repository") != str(Path.cwd().resolve()))
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
        if not sequence["output"]["inputs"]["work"]["clean"]:
            raise ValueError(
                "dirty reviewed baseline needs explicit lead review; work and reports retained"
            )
        if sequence["status"] in ("blocked", "incomplete") or any(
            item["status"] == "running" for item in sequence["stages"].values()
        ):
            from close import leg

            raise ValueError(
                f"lead handoff: {sequence.get('problem', 'incomplete review')}; "
                f"inspect work then explicitly run `xp.py {leg(story_id)[0]} review`"
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
    before_work, after_work = baseline["work"], current["work"]
    from git_source import git

    dirty = git("status", "--porcelain", "--ignore-submodules=untracked")
    same_work = (
        before_work == after_work and before_work["clean"] and after_work["clean"] and not dirty
    )
    if current["tier"] != baseline["tier"] and all(
        before_work[key] == after_work[key] for key in ("head", "tree", "config_without_story")
    ):
        from git_source import facts

        outside_config = facts([".xp/config.yml"])
        same_work = before_work["clean"] and outside_config["clean"]
    if not same_work or any(current[key] != baseline[key] for key in ("review", "scope")):
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
            "version": 2,
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
    from git_source import uncommitted

    if uncommitted():
        raise ValueError(
            "tracked executor bytes differ from HEAD; inspect Git diffs and hiding flags"
        )


def same_inputs(before, after):
    return before == after
