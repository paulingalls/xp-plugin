"""Coordinate reviewed-plan and executor stages in the story worktree."""


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
    prior_stages = prior_handoff.get("stages", {})
    replan = api.ready().plan_needs_replan(story_id, prior_handoff)
    review_only = (
        bool(accepted)
        and prior_stages.get("plan-reviewer") == "blocked"
        and prior_handoff.get("plan_reviewed_card") == api.ready().current_digest(story_id)
    )
    confirmed = False
    reviewed_now = False
    if planned and replan:
        import plan_confirmation

        with api.contextlib.chdir(tree):
            mode, context, problem = plan_confirmation.eligibility(
                story_id, prior_handoff, api.draft_path(api.data_root(), story_id)
            )
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
    if (
        planned
        and not confirmed
        and ((replan and not review_only) or prior_stages.get("planner") != "ran")
    ):
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
    if accepted and accepted["digest"] != api.ready().current_digest(story_id):
        return stop(f"declaration amended after review; run `spawn.py resume {story_id}`", 0)
    if accepted:
        try:
            if problem := artifact_problem(accepted):
                return stop(problem, 0)
        except (OSError, ValueError, KeyError) as error:
            return stop(f"cannot read this round's accepted artifacts: {error}", 0)
    multifile = len(api.declared_files(card)) > 1
    reviewed = bool(accepted) or multifile
    harness, model, effort = api.resolve_role("executor", card, override)
    sandbox, problem = api.resolve_codex_sandbox(harness, api.config_flat("codex_sandbox"))
    if problem or (problem := api.missing_harness(harness)):
        return stop(problem, 0)
    argv = api.agent_argv(harness, model, effort, "stream-json", sandbox)
    # Use the predecessor state; mark_handoff now describes this run.
    if replan:
        handoff = api.inheritance(api.data_root(), story_id, inherited_state, multifile=reviewed)
        if resuming and tree.is_dir():
            handoff += api.resume().inherited_evidence(tree, trunk)
    findings, problem = api.handoff_io.current_findings(api.data_root(), story_id, reviewed)
    if problem:
        api.mark_stage(api.data_root(), story_id, "plan-reviewer", "failed")
        return stop(problem, 0)
    if findings:
        outcome, problem = api.handoff_io.current_disposition(findings)
        if problem:
            api.mark_stage(api.data_root(), story_id, "plan-reviewer", outcome)
            return stop(problem, 0)
    prompt = api.executor_prompt(
        card, story_id, handoff, api.PLUGIN_ROOT, api.PLUGIN_ROOT, reviewed, findings
    )
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
