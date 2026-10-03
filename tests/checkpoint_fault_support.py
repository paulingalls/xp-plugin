"""Faults applied only to an installed plugin copy, against unchanged guarantees."""

from test_completed_executor_preview import (
    test_invalid_checkpoint_preview_and_live_refuse_without_launch,
)

FAULTS = {
    "work": (
        "scripts/spawn/completion.py",
        'if any(current[key] != baseline[key] for key in ("work", "review", "scope")):',
        "if False:",
        "external",
        "hidden",
    ),
    "ignored": (
        "scripts/spawn/completion.py",
        'if any(current[key] != baseline[key] for key in ("work", "review", "scope")):',
        "if False:",
        "external",
        "ignored",
    ),
    "state": (
        "scripts/spawn/completion.py",
        'or checkpoint.get("story_id") != story_id',
        "or False",
        "state",
        "binding",
    ),
    "result": (
        "scripts/spawn/completion.py",
        "if stage not in ORDER or not isinstance(value, dict) "
        'or value.get("result") not in RESULTS:',
        "if False:",
        "state",
        "result",
    ),
    "publication": (
        "scripts/spawn/execution.py",
        'publish("executor", "ran", snapshot())',
        'publish("executor", "running", snapshot())',
        "interruption",
        None,
    ),
    "tier-motion": (
        "scripts/spawn/execution.py",
        "if not same_inputs(before, after):",
        "if False:",
        "motion",
        None,
    ),
    "scope": (
        "scripts/spawn/ready.py",
        'return bool(current and len(current.get("amendments", [])) > count)',
        "return False",
        "scope",
        None,
    ),
    "owner": (
        "scripts/spawn/execution.py",
        "stage = planning_stage(api, story_id, prior, planned)",
        'stage = "planner"',
        "owner",
        None,
    ),
    "missing": (
        "scripts/spawn/resume.py",
        'if kind == "NEVER SPAWNED" and tree.is_dir():',
        "if False:",
        "refusal",
        "missing",
    ),
    "truncated": (
        "scripts/spawn/handoff.py",
        "except (OSError, ValueError):\n        return None",
        'except (OSError, ValueError):\n        return {"state": "STOPPED"}',
        "refusal",
        "truncated",
    ),
    "evidence": (
        "scripts/spawn/completion.py",
        'if value["result"] in RESULTS and (',
        "if False and (",
        "state",
        "evidence",
    ),
    "review-red": (
        "scripts/spawn/completion.py",
        'if reviewed.get("result") == "blocked" and '
        'current["verify"] == reviewed["input"]["verify"]:',
        "if False:",
        "review-red",
        None,
    ),
    "checkout": (
        "scripts/spawn/resume.py",
        "if actual.returncode or actual.stdout.strip() != branch:",
        "if False:",
        "refusal",
        "branch",
    ),
    "artifact": (
        "scripts/plan_acceptance.py",
        'if hashlib.sha256(contents).hexdigest() != record[kind + "_identity"]:',
        "if False:",
        "external",
        "findings",
    ),
    "submodule": (
        "scripts/spawn/completion.py",
        'if any(current[key] != baseline[key] for key in ("work", "review", "scope")):',
        "if False:",
        "submodule",
        None,
    ),
    "role": (
        "scripts/spawn/handoff.py",
        "Complete the card in this worktree. Use predecessor diagnostics as evidence. ",
        "Your assignment: run spawn.py resume story-042. ",
        "role",
        None,
    ),
    "lock": (
        "scripts/spawn/resume.py",
        "fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "pass",
        "lock",
        None,
    ),
    "preview": (
        "scripts/spawn/execution.py",
        "stage = next_stage(story_id, prior, inputs(story_id, card))",
        'stage = "executor"',
        "preview",
        None,
    ),
}


def guarantee(root, scenario, parameter):
    import test_completed_executor_preview as preview
    import test_completed_executor_resume as resume
    import test_story_forward_progress as forward

    if scenario == "external":
        forward.test_external_inputs_invalidate_only_affected_stages(root, parameter)
    elif scenario == "state":
        test_invalid_checkpoint_preview_and_live_refuse_without_launch(root, parameter)
    elif scenario == "interruption":
        forward.test_interrupted_stage_resumes_only_unfinished_work(root, "story-tier")
    elif scenario == "motion":
        resume.test_tier_motion_cannot_publish_success(root)
    elif scenario == "scope":
        forward.test_scope_amendment_returns_to_planning(root)
    elif scenario == "owner":
        forward.test_stage_owned_changes_advance(root)
    elif scenario == "preview":
        preview.test_completed_executor_preview_matches_live_resume(root, "claude", False)

    elif scenario == "review-red":
        resume.test_failed_acceptance_requires_execution_before_retry(root)
    elif scenario == "refusal":
        forward.test_refusal_preserves_work_without_success(root, parameter)
    elif scenario == "submodule":
        forward.test_submodule_runtime_motion_invalidates_executor(root)
    elif scenario in ("lock", "role"):
        import pytest
        import spawn_helpers
        import test_spawn_resume as takeover
        import test_spawn_resume_recovery as recovery

        forward.installed_launch(root)
        script = root / "cache/xp-plugin/fixture/scripts/spawn.py"
        with pytest.MonkeyPatch.context() as patch:
            for module in (spawn_helpers, takeover, recovery):
                patch.setattr(module, "SPAWN", script)
            if scenario == "lock":
                takeover.TestResume().test_a_second_resume_refuses_while_the_first_holds_the_story(
                    root
                )
            else:
                recovery.test_lead_recovery_is_not_an_executor_assignment(root)
