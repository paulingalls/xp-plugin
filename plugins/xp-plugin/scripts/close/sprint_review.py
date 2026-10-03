"""The sprint review leg: fanout, stage resume, round record."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import close as story_close
import overlap
import stages
from close import default_branch, fail, git
from release import next_version, refuse_unbumpable, version_files, version_refusal, versioning_mode
from review_artifacts import (
    notice as artifact_notice,
)
from review_artifacts import (
    rotate as rotate_artifacts,
)
from review_artifacts import sprint_paths
from review_report import aggregate, empty_report, normalize_report
from sprint_bundle import build

# `sprint_cards` and `_shown_diff` are imported FROM sprint_close, never the reverse:
# close/sprint_land.py and slate_review.py still read them out of that module, and a
# second home for either is the one-rule-two-implementations shape this repo keeps filing.
from sprint_close import _shown_diff, sprint_cards
from sprint_state import read_sprint_state, write_sprint_state
from teammate_tee import kill_live
from work import missing_plan_refusal, plan_path


def cmd_review(sprint_id: str, dry_run: bool) -> int:
    import review
    import sprint_review_resume

    marker, state, marker_error = read_sprint_state(sprint_id)
    if marker_error:
        return fail(marker_error)
    if state.get("running_producer"):
        return fail(
            f"refused: uncertain producer at {marker} — inspect saved reports/work and "
            "logs; salvage the interrupted round, then the lead must repair its "
            "running_producer state after confirming the producer has stopped"
        )
    rounds = state.get("rounds", [])
    if not isinstance(rounds, list):
        return fail(f"refused: unreadable rounds in {marker} — repair the marker before review")
    for number, raw in enumerate(rounds, 1):
        if error := normalize_report(raw)[1]:
            return fail(
                f"refused: unreadable round {number} in {marker}: {error} — repair it before review"
            )
    head = git("rev-parse", "HEAD").stdout.strip()
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty and (why := sprint_review_resume.dirty_fixer(rounds, head, sprint_id, review)):
        return fail(f"refused: {why}")
    if dirty:
        return fail("refused: working tree is dirty — commit or stash first")
    if rounds and head == rounds[-1].get("shown_sha", state.get("shown_sha")):
        last = rounds[-1]
        if last.get("blocking") and not last.get("incomplete"):
            return fail(
                "refused: the integration handoff needs the lead — inspect preserved "
                "reports/work, correct the solution, then explicitly review the delta"
            )
    plan = plan_path()
    if not plan.exists():
        return fail(f"refused: {missing_plan_refusal()}")
    trunk = default_branch()
    if (branch := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) == trunk:
        return fail(
            f"refused: review the sprint from its branch, not {branch} — the diff"
            " against the default branch would be empty and certify nothing"
        )
    if not (cards := sprint_cards(plan.read_text(), sprint_id)):
        return fail(f"refused: no `### Sprint {sprint_id}` section in {plan}")
    from review_scope import declared_files

    try:
        declared = declared_files(cards)
    except ValueError as exc:
        return fail(f"refused: {exc}")
    from env import sprint_branch, sprint_branch_name

    expected = sprint_branch_name(sprint_id)
    if branch != expected or sprint_branch() != expected:
        return fail(f"refused: sprint {sprint_id} review belongs on recorded branch {expected}")
    from bookkeep import fork_point

    base, stale = fork_point(trunk)
    if stale:
        return fail(stale)
    versioned, refusal = versioning_mode()
    if refusal:
        return fail(refusal)
    if versioned and (names := version_files()) and names != ["none"]:
        if not (version := next_version()):
            return refuse_unbumpable()
        if refusal := version_refusal(version, names):
            return fail(f"{refusal} — bump before the review")
    complete_n, reviewed_head, resume_round, why, refusal = sprint_review_resume.state(
        rounds, head, sprint_id, review, git
    )
    if refusal:  # `review` is the only command that runs one, so a refusal that names
        return fail(  # no way out of the round leaves the sprint with no next action
            f"refused: {refusal}; or discard the incomplete round by moving {marker}"
            " aside — it holds this sprint's recorded rounds and moving it forfeits"
            f" them — then `xp.py sprint {sprint_id} review` for a fresh fanout"
        )
    resume = resume_round is not None
    if not resume:
        from sprint_close import prepare_close

        if error := prepare_close(sprint_id, dry_run):
            return error
    review_base = resume_round.get("review_base", base) if resume else base
    discarded = next((r for r in reversed(rounds) if r.get("incomplete")), None)
    if not resume and discarded:
        names = ", ".join(discarded.get("stages", [])) or "no recorded stages"
        reason = why or "the recorded round is not resumable"
        print(
            f"warning: {reason} — opening a fresh round without reusing completed stages: {names}",
            file=sys.stderr,
        )
    round_n = len(rounds) if resume else len(rounds) + 1
    found, cap, charters, altitude, err = sprint_review_resume.inputs(complete_n, cards, stages)
    if err:
        return fail(err)
    authority = story_close.review_authority_sections()
    digest_before = review.marker_digest(marker)
    diff_base = rounds[complete_n - 1].get("shown_sha", state["shown_sha"]) if complete_n else ""
    if diff_base and (missing := _shown_diff(sprint_id, diff_base, head)[1]):
        return fail(missing)

    from finding_triage import render_triage
    from work import data_root

    evidence_errors = []
    render_triage(data_root(), evidence_errors)
    if evidence_errors:
        return fail("refused: " + "\n".join(evidence_errors))
    salvage_cmd = f"xp.py sprint {sprint_id} salvage"
    if not (dry_run or resume):
        moves = rotate_artifacts(sprint_paths(sprint_id, round_n))
        if left := artifact_notice(moves, salvage_cmd):
            print("warning: " + left, file=sys.stderr)

    ran, reports = [], []
    producer = ""
    prefix = (
        sprint_review_resume.Prefix(
            resume_round, review.read_report, review.sprint_report_path, sprint_id, round_n
        )
        if resume
        else None
    )

    def stop(err: str) -> int:
        err, notice = sprint_review_resume.stop(
            resume,
            dry_run,
            marker,
            round_n,
            err,
            reports,
            prefix,
            ran,
            reviewed_head,
            lambda: git("rev-parse", "HEAD").stdout.strip(),
            state,
            review,
            write_sprint_state,
            review_base,
            producer,
        )
        if notice:
            print(notice)
        return fail(err)

    def leg(
        stage: str,
        key: str,
        extra: list,
        charter: str = "",
        *,
        batch_head: str = "",
    ) -> tuple[dict, str]:
        nonlocal producer, digest_before
        correction = bool(resume and resume_round.get("producer") == key)
        if stage in ("fixer", "closer"):
            producer = key
        path = (
            data_root() / "reports" / "sprint" / f"{sprint_id}.{key}.round-{round_n}.json"
            if dry_run
            else review.sprint_report_path(sprint_id, key, round_n)
        )
        if not dry_run and (aside := rotate_artifacts([path, review.patch_path(path)])):
            print("warning: " + artifact_notice(aside, salvage_cmd), file=sys.stderr)
        excluded, trunk_range = set(), ""
        if diff_base:
            prior = next((r for r in reversed(rounds) if not r.get("incomplete")), {})
            eligible, trunk_range, _reason = overlap.trunk_only_paths(
                prior.get("review_base"),
                diff_base,
                git("rev-parse", "HEAD").stdout.strip(),
                trunk,
            )
            moved = overlap._files(f"{diff_base}..HEAD")
            excluded = eligible & moved
        bundle = build(
            sprint_id,
            cards,
            base,
            path,
            (
                (charter or charters[stage]) + "\nCorrect only this interrupted producer's report"
                " using preserved work and logs. "
                "Do not edit or commit again; report missing evidence honestly."
                if correction
                else charter or charters[stage]
            ),
            extra,
            authority,
            diff_base,
            excluded,
            trunk_range,
        )
        stage_head = batch_head or git("rev-parse", "HEAD").stdout.strip()
        role = "reviewer" if stage == "solution" or correction else stage
        if stage == "fixer" and not dry_run:
            write_sprint_state(marker, {"running_producer": key})
            digest_before = review.marker_digest(marker)
        result, err = review.run(
            bundle,
            Path.cwd(),
            dry_run,
            f"sprint {key}",
            cards if role else "",
            role,
            bool(role),
            noun=f"sprint {sprint_id}",
        )
        if dry_run:  # an EMPTY report, not a shapeless one: a preview walks
            empty = empty_report()
            empty["actionable"] = []
            return empty, review.abort_text(head, err) if err else ""
        report, report_err = review.read_report(
            path, stage="solution" if stage == "verifier" else stage
        )
        if not report_err and not batch_head:
            ran.append(key)
            reports.append(report)
        if stage == "fixer" and not dry_run:
            producer_motion = review.marker_digest(marker) != digest_before
            write_sprint_state(marker, {}, remove=("running_producer",))
            digest_before = review.marker_digest(marker)
            if producer_motion:
                err = err or "fixer moved the close marker; lead must inspect preserved evidence"
        if err:  # stage_head, not head: an undo from the ROUND's start spans an applied fix
            empty = empty_report()
            return report if batch_head else empty, review.abort_text(stage_head, err)
        print(
            f"--- {key} ---\n{result}" if batch_head else result
        )  # before any refusal: the findings exist nowhere else yet
        if (
            not batch_head
            and (stage != "fixer" or correction)
            and (motion := review.check_reviewer_motion(stage_head, marker, digest_before, cards))
        ):
            return empty_report(), motion
        if batch_head:
            return report, review.abort_text(stage_head, report_err) if report_err else ""
        if not report_err and stage == "fixer":
            current = git("rev-parse", "HEAD").stdout.strip()
            if git("status", "--porcelain").stdout.strip():
                report_err = "fixer left uncommitted work; lead must inspect it"
            elif git("merge-base", "--is-ancestor", stage_head, current, check=False).returncode:
                report_err = "fixer rewrote the reviewed solution"
            elif review.marker_digest(marker) != digest_before:
                report_err = "fixer moved the close marker"
            else:
                from completion import committed_contents

                committed_contents()
                touched = git(
                    "diff", "--name-only", "--no-renames", stage_head, current
                ).stdout.splitlines()
                if outside := [p for p in touched if p.startswith(".xp/") and p not in declared]:
                    report_err = (
                        "fixer committed paths outside the Files line: "
                        + ", ".join(outside)
                        + "; lead must inspect preserved work"
                    )
        return report, review.abort_text(stage_head, report_err) if report_err else ""

    resume_announced = False

    def stage(stage_name: str, key: str, extra: list, charter: str = "") -> tuple[dict, str]:
        nonlocal resume_announced
        if prefix and resume_round.get("producer") == key:
            prefix.close("the interrupted producer may correct only its report")
        report, _error = sprint_review_resume.take(
            prefix, "solution" if stage_name == "verifier" else stage_name, key, reports, round_n
        )
        if report is not None:
            return report, ""
        if resume and not resume_announced:
            print(f"round {round_n} resumes at {key}")
            resume_announced = True
        return leg(stage_name, key, extra, charter)

    def batch(stage_name: str, jobs: list[tuple[str, list]]) -> tuple[list[dict], str]:
        nonlocal resume_announced
        if dry_run:
            results = [stage(stage_name, key, extra) for key, extra in jobs]
            launched = [key for key, _ in jobs if not prefix or key not in prefix.reused]
            if launched:
                print(f"concurrent {stage_name} stages: " + ", ".join(launched))
            return [report for report, _ in results], next((err for _, err in results if err), "")
        batch_head = git("rev-parse", "HEAD").stdout.strip()
        ordered = []
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            for key, extra in jobs:
                report, _ = sprint_review_resume.take(
                    prefix,
                    "solution" if stage_name == "verifier" else stage_name,
                    key,
                    reports,
                    round_n,
                )
                if report is not None:
                    ordered.append((key, report, None))
                    continue
                if resume and not resume_announced:
                    print(f"round {round_n} resumes at {key}")
                    resume_announced = True
                future = pool.submit(leg, stage_name, key, extra, batch_head=batch_head)
                ordered.append((key, None, future))
            results = []
            errors = []
            for key, reused_report, future in ordered:
                if future is None:
                    results.append(reused_report)
                    continue
                try:
                    report, error = future.result()
                except BaseException:  # a KeyboardInterrupt lands here, never in a leg
                    while not all(f.done() for _, _, f in ordered if f):
                        kill_live()
                        time.sleep(0.1)
                    raise
                if report:  # DECLARED order, never completion order: resume reuses this prefix
                    ran.append(key)
                    reports.append(report)
                results.append(report)
                if error:
                    errors.append(error)
        motion = review.check_reviewer_motion(batch_head, marker, digest_before, cards)
        return results, motion or (errors[0] if errors else "")

    prior = [
        ("Current integration obligations", "\n".join(overlap.unresolved_blocking(state)) or "none")
    ]
    fixed, closing = empty_report(), empty_report()
    survivors, reserved = [], []
    if complete_n:
        solution, err = stage(
            "solution", "solution", [("Sprint altitude", altitude), *prior], review.charter()
        )
        if err:
            return stop(err)
        survivors, reserved = solution["actionable"], solution["blocking"]
    else:
        candidates = []
        jobs = [(f"find-{slug}", [("Your angle", prose), *prior]) for slug, prose in found]
        finder_reports, err = batch("finder", jobs)
        if err:
            return stop(err)
        for report in finder_reports:
            candidates += report["blocking"]
        if dry_run:
            print("(then: verifiers; authorized findings buy one fixer and narrow closer)")
            return 0
        batches = stages.batches(candidates, cap)
        verify_keys = [f"verify-{n}" for n in range(1, len(batches) + 1)]
        if prefix and (why := prefix.match_verifiers(verify_keys)):
            print(f"round {round_n}: cannot reuse verifiers: {why}")
        jobs = [
            (
                f"verify-{n}",
                [("The candidates you are judging", "\n".join(f"- {c}" for c in items))],
            )
            for n, items in enumerate(batches, 1)
        ]
        verifier_reports, err = batch("verifier", jobs)
        if err:
            return stop(err)
        for report in verifier_reports:
            survivors += report["actionable"]
            reserved += report["blocking"]
        print(
            f"{len(candidates)} candidates, {len(survivors)} authorized, {len(reserved)} reserved"
        )
    if survivors:
        told = [("The findings you must fix", "\n".join(f"- {s}" for s in survivors))]
        fixed, err = stage("fixer", "fix", told)
        if err:
            return stop(err)
        if not fixed["blocking"]:
            closing, err = stage(
                "closer",
                "close",
                [
                    *told,
                    ("What the fixer reported", json.dumps(fixed)),
                    (
                        "Correction range",
                        f"{reviewed_head}..{git('rev-parse', 'HEAD').stdout.strip()}",
                    ),
                ],
            )
            if err:
                return stop(err)
    if dry_run:
        return 0
    shown_sha = git("rev-parse", "HEAD").stdout.strip()

    # Plan drift is safe to reject only after every sprint member is terminal.
    if sprint_cards(plan.read_text(), sprint_id) != cards:
        changed = f"sprint {sprint_id}'s cards changed during the review"
        return stop(review.abort_text(shown_sha, changed))
    round_ = aggregate(reports)
    round_["schema"] = 2
    round_["blocking"] = [*reserved, *fixed["blocking"], *closing["blocking"]]
    if clearable := closing.get(review.CLEARABLE_BY_FULL):
        round_[review.CLEARABLE_BY_FULL] = clearable
    fix_report = review.sprint_report_path(sprint_id, "fix", round_n)
    if err := review.write_reviewer_diff(fix_report, reviewed_head, f"sprint {sprint_id}"):
        return stop(err)
    sprint_review_resume.finish(
        resume,
        marker,
        state,
        round_n,
        round_,
        reviewed_head if resume else head,
        shown_sha,
        prefix,
        ran,
        review,
        write_sprint_state,
        review_base,
    )
    print(
        f"round {round_n} recorded at {shown_sha[:8]}:"
        f" {len(round_.get('fixed', []))} fixed, {len(round_['blocking'])} blocking"
    )
    if round_["blocking"]:
        return fail(
            "refused: integration findings remain — the lead must inspect the reports "
            "and correction, then explicitly review any changed solution"
        )
    return 0
