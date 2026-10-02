"""Coordinate reviewed-plan and executor stages in the story worktree."""


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
    from plan_acceptance import artifact_problem, latest

    accepted = latest(story_id)
    planned = multifile or bool(accepted)
    api.mark_handoff(api.data_root(), story_id)
    prior_handoff = inherited_state or {}
    from plan_acceptance import restore_handoff
    from plan_writer import CardEditRefusal

    try:
        if restore_handoff(api.data_root(), story_id, prior_handoff):
            prior_handoff = api.handoff_state(api.data_root(), story_id) or {}
    except (OSError, ValueError, CardEditRefusal) as error:
        return stop(f"cannot restore accepted plan review: {error}", 0)
    prior_stages, replan, review_only, mode, context, problem = select(
        api, story_id, tree, prior_handoff, planned
    )
    confirmed = False
    reviewed_now = False
    if planned and replan:
        import plan_confirmation

        with api.contextlib.chdir(tree):
            if problem:
                print(problem, file=api.sys.stderr)
            if mode == "refuse":
                return stop(problem, 0)
            if mode == "fallback":
                review_only = False
            if mode == "confirm":
                try:
                    result = plan_confirmation.run(
                        story_id, api.draft_path(api.data_root(), story_id), context
                    )
                except (OSError, ValueError) as error:
                    return stop(
                        f"cannot preserve/confirm predecessor: {error}; restore and resume", 0
                    )
                rc, outcome = result
                api.mark_stage(
                    api.data_root(),
                    story_id,
                    "plan-confirmation",
                    "ran" if outcome == "replan" else outcome,
                )
                accepted = getattr(result, "acceptance", None)
                if accepted:
                    api.handoff_io.mark_plan_reviewed(
                        api.data_root(), story_id, api.ready().current_digest(story_id), accepted
                    )
                if rc:
                    api.mark_stage(api.data_root(), story_id, "plan-reviewer", outcome)
                    why = (
                        api.handoff_io.blocked_problem(api.data_root(), story_id)
                        if outcome == "blocked"
                        else f"plan confirmation {outcome}; inspect its disposition and resume"
                    )
                    return stop(why, 0)
                confirmed = outcome != "replan"
                if confirmed:
                    replan = False
                else:
                    review_only = False
            elif (
                mode == "unchanged"
                and accepted
                and ".confirmation-" in accepted["findings"]
                and prior_stages.get("plan-reviewer") == "blocked"
            ):
                return stop(api.handoff_io.blocked_problem(api.data_root(), story_id), 0)
    if not confirmed and next_stage(planned, replan, review_only, prior_stages) == "planner":
        if replan:
            import plan_confirmation

            try:
                with api.contextlib.chdir(tree):
                    plan_confirmation.preserve(story_id, api.draft_path(api.data_root(), story_id))
            except (OSError, ValueError) as error:
                return stop(
                    f"cannot preserve predecessor before planner: {error}; restore and resume", 0
                )
        if problem := api.handoff_io.archive_replanned_rounds(story_id, prior_handoff):
            return stop(f"{problem}; repair preserved rounds before resuming", 0)
        current_state = api.handoff_state(api.data_root(), story_id) or {}
        inherited = prior_handoff | {"predecessors": current_state.get("predecessors", [])}
        handoff = api.inheritance(api.data_root(), story_id, inherited, multifile=True)
        rc, why = api.stages.run_planner(story_id, card, tree, handoff)
        # 0, because stop's code is the HARNESS rc: a stage that refused or blocked
        # for the human did not DIE, and saying so sends the lead to the wrong log.
        if rc:
            return stop(why, 0)
        api.mark_stage(api.data_root(), story_id, "planner", "ran")
    elif not planned:
        api.mark_stage(api.data_root(), story_id, "planner", "skipped")
    if planned and not confirmed and (replan or prior_stages.get("plan-reviewer") != "ran"):
        import plan_review

        with api.contextlib.chdir(tree):
            result = plan_review.run_foreground(story_id, api.draft_path(api.data_root(), story_id))
        rc, outcome = result
        reviewed_now = True
        accepted = getattr(result, "acceptance", None) or latest(story_id)
        if rc:
            if outcome == "capped":
                api.handoff_io.mark_plan_reviewed(
                    api.data_root(), story_id, api.ready().current_digest(story_id), accepted
                )
                findings, problem = api.handoff_io.current_findings(api.data_root(), story_id)
                if not problem and findings:
                    outcome, problem = api.handoff_io.current_disposition(findings)
                if problem:
                    return stop(f"execution plan review cap: {problem}", 0)
                if not accepted:
                    return stop(
                        "execution plan review reached its two-round cap; read and apply both"
                        f" dispositions, then run `spawn.py resume {story_id}`",
                        0,
                    )
                rc = 0
            if outcome == "blocked":
                api.handoff_io.mark_plan_reviewed(
                    api.data_root(), story_id, api.ready().current_digest(story_id), accepted
                )
            if rc:
                api.mark_stage(api.data_root(), story_id, "plan-reviewer", outcome)
            why = f"execution plan review {outcome}; read its disposition before resuming"
            if outcome == "blocked":
                why = api.handoff_io.blocked_problem(api.data_root(), story_id)
            if rc:
                return stop(why, 0)
        api.handoff_io.mark_plan_reviewed(
            api.data_root(), story_id, api.ready().current_digest(story_id), accepted
        )
    elif not planned:
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", "skipped")
    card, _status = api.story_card(api.plan_path().read_text(), story_id)
    if problem := api.ready().drift(story_id, card):
        return stop(problem, 0)
    if replan:
        handoff = api.inheritance(api.data_root(), story_id, inherited_state, multifile=True)
        if resuming and tree.is_dir():
            handoff += api.resume().inherited_evidence(tree, trunk)
    try:
        harness, argv, prompt = prepare(api, story_id, card, handoff, override=override)
    except FindingsRefusal as error:
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", error.result)
        return stop(str(error), 0)
    except (OSError, ValueError, KeyError) as error:
        return stop(str(error), 0)
    report, warning = api.profile_report(card, prompt, handoff)
    print(report)
    if warning:
        print(warning, file=api.sys.stderr)
    for attempt in range(2):
        if accepted:
            try:
                if problem := artifact_problem(accepted):
                    return stop(problem, 0)
                current, _ = api.story_card(api.plan_path().read_text(), story_id)
                if problem := api.ready().drift(story_id, current):
                    return stop(problem, 0)
                if accepted["digest"] != api.ready().current_digest(story_id):
                    return stop("card moved before executor; amend and resume", 0)
                if not attempt and (confirmed or reviewed_now):
                    from plan_confirmation import execution_problem

                    with api.contextlib.chdir(tree):
                        if problem := execution_problem(accepted):
                            api.mark_stage(api.data_root(), story_id, "plan-reviewer", "failed")
                            return stop(problem, 0)
            except (OSError, ValueError, KeyError) as error:
                return stop(f"cannot read accepted launch evidence: {error}; restore and resume", 0)
        rc = api.run_teammate(argv, tree, prompt, story_id, api.data_root(), harness)
        outcome = "terminal-stop" if rc == 0 else "harness-death"
        executor_log = api.data_root() / "logs" / f"{story_id}-executor.log"
        err = api.unclean_teammate_result(
            tree, handed_over, story_id, resuming, outcome, executor_log, attempt > 0
        )
        if err or rc:
            why = err or f"the teammate left a clean commit in {tree} before its harness failed"
            return stop(why, rc)
        api.mark_stage(api.data_root(), story_id, "executor", "ran")
        tier_state, tier_command, tier_output = api.story_tier(tree)
        if tier_state == "unavailable":
            reason = "unset" if not tier_command else "EDIT-ME"
            print(f"no story tier ran in {tree}: tests.story is {reason}")
            api.mark_stage(api.data_root(), story_id, "story-tier", "skipped")
            break
        if tier_state == "passed":
            api.mark_stage(api.data_root(), story_id, "story-tier", "ran")
            break
        api.mark_stage(api.data_root(), story_id, "story-tier", "failed")
        if attempt or tier_state == "unrunnable":
            return stop(
                f"story tier {tier_state}: {tier_command!r} in {tree}."
                f" Output tail:\n{tier_output}\n"
                f"Repair in that tree with `spawn.py resume {story_id}`",
                0,
            )
        handed_over = api.tree_state(tree)
        prompt += (
            "\n## Story tier failure\n\n"
            f"The configured story tier `{tier_command}` failed in {tree}."
            f" Fix it and commit before handing back. Output tail:\n{tier_output}\n"
        )
    return api.stages.finish_story(tree, story_id, stop, stage_line, held)


def prepare(api, story_id, card, handoff, state=None, override=""):
    from plan_acceptance import artifact_problem, latest

    accepted = latest(story_id)
    if accepted and accepted["digest"] != api.ready().current_digest(story_id):
        raise ValueError(f"declaration amended after review; run `spawn.py resume {story_id}`")
    if accepted:
        try:
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


def select(api, story_id, tree, prior, planned):
    stages = prior.get("stages", {})
    replan = api.ready().plan_needs_replan(story_id, prior)
    from plan_acceptance import latest

    review_only = (
        bool(latest(story_id))
        and stages.get("plan-reviewer") == "blocked"
        and prior.get("plan_reviewed_card") == api.ready().current_digest(story_id)
    )
    mode, context, problem = "unchanged", None, ""
    if planned and replan:
        import plan_confirmation

        with api.contextlib.chdir(tree):
            mode, context, problem = plan_confirmation.eligibility(
                story_id, prior, api.draft_path(api.data_root(), story_id)
            )
        if mode == "fallback":
            review_only = False
    return stages, replan, review_only, mode, context, problem


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
    except (OSError, ValueError, CardEditRefusal) as error:
        return api.fail(f"cannot restore accepted plan review: {error}")
    try:
        planned = resuming and (multifile or bool(latest(story_id)))
        stages, replan, review_only, mode, _context, problem = select(
            api, story_id, tree, prior, planned
        )
        if mode == "refuse":
            return api.fail(problem)
        if mode == "confirm":
            print("Next stage: plan-confirmation (confirm/replan/block awaits verdict).")
        elif next_stage(planned, replan, review_only, stages) == "planner":
            print("Next stages: planner, plan-reviewer.")
        elif next_stage(planned, replan, review_only, stages) == "plan-reviewer":
            print("Next stage: plan-reviewer (retained draft).")
        else:
            _harness, argv, prompt = prepare(api, story_id, card, handoff, prior, override)
            report, warning = api.profile_report(card, prompt, handoff)
            print(report)
            if warning:
                print(warning, file=api.sys.stderr)
            from teammate_tee import launch_argv

            print(" ".join(launch_argv(argv, tree, widen_git=True)))
            print(prompt)
            return 0
        if problem:
            print(problem)
        print("Future plan-review findings and executor inputs are not yet available.")
        return 0
    except (OSError, ValueError, KeyError) as error:
        return api.fail(str(error))


def next_stage(planned, replan, review_only, stages):
    if planned and ((replan and not review_only) or stages.get("planner") != "ran"):
        return "planner"
    if planned and (replan or stages.get("plan-reviewer") != "ran"):
        return "plan-reviewer"
    return "executor"
