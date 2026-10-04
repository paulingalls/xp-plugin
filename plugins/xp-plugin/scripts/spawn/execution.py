"""Run concrete story stages from the existing authoritative handoff."""


class FindingsRefusal(ValueError):
    def __init__(self, message, result="failed"):
        super().__init__(message)
        self.result = result


def run(
    api,
    story_id,
    card,
    tree,
    handoff,
    inherited_state,
    multifile,
    resuming,
    trunk,
    handed_over,
    harness,
    argv,
    stop,
    stage_line,
    held,
    override="",
):
    from plan_acceptance import latest, restore_handoff
    from plan_writer import CardEditRefusal

    prior = inherited_state or {}
    try:
        restore_handoff(api.data_root(), story_id, prior)
        prior = api.handoff_state(api.data_root(), story_id) or {}
        planned = multifile or bool(latest(story_id))
        with api.contextlib.chdir(tree):
            stage = planning_stage(api, story_id, prior, planned)
    except FindingsRefusal as error:
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", error.result)
        return stop(str(error), 0)
    except (OSError, ValueError, CardEditRefusal) as error:
        return stop(f"cannot recover plan review: {error}; preserve artifacts and resume", 0)
    api.mark_handoff(api.data_root(), story_id)
    if stage == "planner":
        if api.ready().plan_needs_replan(story_id, prior):
            from plan_confirmation import preserve

            try:
                with api.contextlib.chdir(tree):
                    preserve(story_id, api.draft_path(api.data_root(), story_id))
            except (OSError, ValueError) as error:
                return stop(
                    f"cannot preserve predecessor: {error}; restore snapshots and resume", 0
                )
            if problem := api.handoff_io.archive_replanned_rounds(story_id, prior):
                return stop(problem, 0)
        api.mark_stage(api.data_root(), story_id, "planner", "running")
        try:
            rc, why = api.stages.run_planner(story_id, card, tree, handoff)
        except (OSError, ValueError) as error:
            rc, why = 2, f"cannot check planner source: {error}; inspect retained work and resume"
        if rc:
            api.mark_stage(api.data_root(), story_id, "planner", "failed")
            return stop(why, 0)
        api.mark_stage(api.data_root(), story_id, "planner", "ran")
        stage = "plan-reviewer"
    if stage == "plan-reviewer":
        import plan_review

        if prior.get("stages", {}).get("plan-reviewer") == "ran" and not latest(story_id):
            from plan_confirmation import preserve

            try:
                with api.contextlib.chdir(tree):
                    preserve(story_id, api.draft_path(api.data_root(), story_id))
            except (OSError, ValueError) as error:
                return stop(
                    f"cannot preserve predecessor: {error}; restore snapshots and resume", 0
                )

        api.mark_stage(api.data_root(), story_id, "plan-reviewer", "running")
        with api.contextlib.chdir(tree):
            result = plan_review.run_foreground(story_id, api.draft_path(api.data_root(), story_id))
        rc, outcome = result
        accepted = getattr(result, "acceptance", None) or latest(story_id)
        if accepted:
            api.handoff_io.mark_plan_reviewed(
                api.data_root(), story_id, api.ready().current_digest(story_id), accepted
            )
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", outcome)
        if rc:
            why = (
                api.handoff_io.blocked_problem(api.data_root(), story_id)
                if outcome == "blocked"
                else f"execution plan review {outcome}; read its findings and resume"
            )
            return stop(why, 0)
    elif not planned:
        api.mark_stage(api.data_root(), story_id, "planner", "skipped")
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", "skipped")
    card, _ = api.story_card(api.plan_path().read_text(), story_id)
    if problem := api.ready().drift(story_id, card):
        return stop(problem, 0)
    try:
        harness, argv, prompt = prepare(api, story_id, card, handoff, override=override)
        from completion import inputs, next_stage

        with api.contextlib.chdir(tree):
            current = inputs(story_id, card)
            stage = next_stage(story_id, prior, current) if resuming else "executor"
    except FindingsRefusal as error:
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", error.result)
        return stop(str(error), 0)
    except (OSError, ValueError, KeyError) as error:
        return stop(str(error), 0)
    report, warning = api.profile_report(card, prompt, handoff)
    print(report)
    if warning:
        print(warning, file=api.sys.stderr)
    try:
        with api.contextlib.chdir(tree):
            refreshed = inputs(story_id, card)
            stage = next_stage(story_id, prior, refreshed) if resuming else "executor"
        return execute(
            api,
            story_id,
            card,
            tree,
            harness,
            argv,
            prompt,
            stage,
            handed_over,
            resuming,
            stop,
            stage_line,
            held,
        )
    except (OSError, ValueError, KeyError) as error:
        return stop(f"execution result cannot be published: {error}; preserve work and resume", 0)


def execute(
    api,
    story_id,
    card,
    tree,
    harness,
    argv,
    prompt,
    stage,
    handed_over,
    resuming,
    stop,
    stage_line,
    held,
):
    from completion import committed_contents, inputs, record, same_inputs

    def snapshot():
        current_card, _ = api.story_card(api.plan_path().read_text(), story_id)
        with api.contextlib.chdir(tree):
            return inputs(story_id, current_card)

    def publish(name, result, value):
        with api.contextlib.chdir(tree):
            record(story_id, name, result, value)

    for attempt in range(2):
        if stage == "executor":
            publish("executor", "running", snapshot())
            rc = api.run_teammate(argv, tree, prompt, story_id, api.data_root(), harness)
            log = api.data_root() / "logs" / f"{story_id}-executor.log"
            problem = api.unclean_teammate_result(
                tree,
                handed_over,
                story_id,
                resuming,
                "harness-death" if rc else "terminal-stop",
                log,
                attempt > 0,
            )
            if rc or problem:
                publish("executor", "interrupted" if rc else "failed", snapshot())
                return stop(problem or f"executor harness failed; inspect {log}", rc)
            try:
                with api.contextlib.chdir(tree):
                    committed_contents()
                publish("executor", "ran", snapshot())
            except (OSError, ValueError) as error:
                return stop(f"cannot publish executor result: {error}; inspect and resume", 0)
            stage = "story-tier"
        if stage == "story-tier":
            before = snapshot()
            from git_source import tracked_state

            with api.contextlib.chdir(tree):
                boundary = tracked_state()
            publish("story-tier", "running", before)
            result, command, output = api.story_tier(tree)
            after = snapshot()
            with api.contextlib.chdir(tree):
                moved = tracked_state() != boundary
            if not same_inputs(before, after) or moved:
                publish("story-tier", "failed", after)
                return stop("story tier inputs moved while it ran; inspect work and resume", 0)
            if result == "unavailable":
                print(
                    f"no story tier ran in {tree}: tests.story is "
                    f"{'unset' if not command else 'EDIT-ME'}"
                )
                publish("story-tier", "skipped", after)
                break
            if result == "passed":
                publish("story-tier", "ran", after)
                break
            publish("story-tier", "failed", after)
            if attempt or result == "unrunnable":
                return stop(
                    f"story tier {result}: {command!r} in {tree}. Output "
                    f"tail:\n{output}\nRepair with `spawn.py resume {story_id}`",
                    0,
                )
            handed_over = api.tree_state(tree)
            prompt += (
                f"\n## Story tier failure\n\nFix the configured story tier "
                f"`{command}` and commit. Output tail:\n{output}\n"
            )
            stage = "executor"
        else:
            break
    return api.stages.finish_story(tree, story_id, stop, stage_line, held)


def prepare(api, story_id, card, handoff, state=None, override=""):
    from plan_acceptance import artifact_problem, latest

    if state is None:
        state = api.handoff_state(api.data_root(), story_id) or {}
    accepted = latest(story_id)
    if accepted and accepted["digest"] != api.ready().current_digest(story_id):
        raise ValueError(f"declaration amended after review; run `spawn.py resume {story_id}`")
    if accepted:
        try:
            from pathlib import Path

            from plan_confirmation import prior_binding

            prior_binding(accepted, Path(accepted["plan"]))
            problem = artifact_problem(accepted)
        except (OSError, ValueError, KeyError) as error:
            raise ValueError(f"cannot read this round's accepted artifacts: {error}") from error
        if problem:
            raise ValueError(problem)
    multifile = len(api.declared_files(card)) > 1
    reviewed = bool(accepted) or multifile
    harness, model, effort = api.resolve_role("executor", card, override)
    sandbox, problem = api.resolve_codex_sandbox(harness, api.config_flat("codex_sandbox"))
    if problem or (problem := api.missing_harness(harness)):
        raise ValueError(problem)
    argv = api.agent_argv(harness, model, effort, "stream-json", sandbox)
    findings, problem = api.handoff_io.current_findings(api.data_root(), story_id, reviewed, state)
    if problem:
        raise FindingsRefusal(problem)
    if (
        findings
        and accepted
        and (
            str(findings.resolve()) != accepted["findings"]
            or (
                state is not None
                and state.get("plan_review_identity") != accepted["findings_identity"]
            )
        )
    ):
        raise ValueError(
            f"refused: current findings do not match accepted plan review; "
            f"restore {accepted['findings']} or amend and resume {story_id}"
        )
    if findings:
        outcome, problem = api.handoff_io.current_disposition(findings)
        if problem:
            raise FindingsRefusal(problem, outcome)
    prompt = api.executor_prompt(
        card, story_id, handoff, api.PLUGIN_ROOT, api.PLUGIN_ROOT, reviewed, findings
    )
    return harness, argv, prompt


def planning_stage(api, story_id, prior, planned):
    if api.ready().plan_needs_replan(story_id, prior):
        return "planner"
    if not planned:
        return "executor"
    stages = prior.get("stages", {})
    from plan_acceptance import latest

    if stages.get("plan-reviewer") == "ran" and not latest(story_id):
        findings, problem = api.handoff_io.current_findings(api.data_root(), story_id, True, prior)
        if problem:
            raise ValueError(problem)
        if findings:
            outcome, problem = api.handoff_io.current_disposition(findings)
            if problem:
                raise FindingsRefusal(problem, outcome)
        return "plan-reviewer"
    if stages.get("planner") != "ran":
        return "planner"
    if stages.get("plan-reviewer") != "ran":
        return "plan-reviewer"
    return "executor"


def preview(api, story_id, card, tree, handoff, prior, multifile, resuming, override):
    from plan_acceptance import latest
    from plan_writer import CardEditRefusal

    if resuming and (
        problem := api.resume().validate(
            api.data_root(), story_id, tree, api.story_branch(card, story_id)
        )
    ):
        return api.fail(problem)
    try:
        prior = api.handoff_io.effective_review(api.data_root(), story_id, prior or {})
        with api.contextlib.chdir(tree if resuming else api.Path.cwd()):
            stage = planning_stage(api, story_id, prior, multifile or bool(latest(story_id)))
            if stage == "executor":
                _harness, argv, prompt = prepare(api, story_id, card, handoff, prior, override)
                if resuming:
                    from completion import inputs, next_stage

                    stage = next_stage(story_id, prior, inputs(story_id, card))
        print(f"Next stage: {stage}.")
        if stage in ("planner", "plan-reviewer"):
            print("Future plan-review findings and executor inputs are not yet available.")
        elif stage != "executor":
            print(
                "executor: reuse recorded result; independent diff review and post-review "
                "Verify follow."
            )
        else:
            from teammate_tee import launch_argv

            report, warning = api.profile_report(card, prompt, handoff)
            print(report)
            if warning:
                print(warning, file=api.sys.stderr)
            print(" ".join(launch_argv(argv, tree, widen_git=True)))
            print(prompt)
        return 0
    except (OSError, ValueError, KeyError, CardEditRefusal) as error:
        return api.fail(str(error))
