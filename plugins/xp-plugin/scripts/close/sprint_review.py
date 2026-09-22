"""The sprint review leg: fanout, stage resume, round record."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import close as story_close
import stages
from close import default_branch, fail, git
from review_artifacts import (
    notice as artifact_notice,
)
from review_artifacts import (
    rotate as rotate_artifacts,
)
from review_artifacts import sprint_paths
from sprint_bundle import build

# `sprint_cards` and `_shown_diff` are imported FROM sprint_close, never the reverse:
# close/sprint_land.py and slate_review.py still read them out of that module, and a
# second home for either is the one-rule-two-implementations shape this repo keeps filing.
from sprint_close import _shown_diff, sprint_cards
from sprint_state import sprint_marker, write_sprint_state
from work import missing_plan_refusal, plan_path


def cmd_review(sprint_id: str, dry_run: bool) -> int:
    import review
    import sprint_review_resume
    from bookkeep import render_sprint_prior

    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    rounds = state.get("rounds", [])
    head = git("rev-parse", "HEAD").stdout.strip()
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty and (why := sprint_review_resume.dirty_fixer(rounds, head, sprint_id, review)):
        return fail(f"refused: {why}")
    if dirty:
        return fail("refused: working tree is dirty — commit or stash first")
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
    complete_n, reviewed_head, resume_round, why, refusal = sprint_review_resume.state(
        rounds, head, sprint_id, review, git
    )
    if refusal:  # `review` is the only command that runs one, so a refusal that names
        return fail(  # no way out of the round leaves the sprint with no next action
            f"refused: {refusal}; or discard the incomplete round by moving {marker}"
            " aside — it holds this sprint's recorded rounds and moving it forfeits"
            f" them — then `close.py sprint {sprint_id} review` for a fresh fanout"
        )
    resume = resume_round is not None
    discarded = next((r for r in reversed(rounds) if r.get("incomplete")), None)
    if not resume and discarded:
        names = ", ".join(discarded.get("stages", [])) or "no recorded stages"
        reason = why or "the recorded round is not resumable"
        print(
            f"warning: {reason} — opening a fresh round and discarding completed stages: {names}",
            file=sys.stderr,
        )
    round_n = len(rounds) if resume else len(rounds) + 1
    found, cap, charters, altitude, err = sprint_review_resume.inputs(complete_n, cards, stages)
    if err:
        return fail(err)
    authority = story_close.review_authority_sections()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    digest_before = review.marker_digest(marker)
    diff_base = state["shown_sha"] if complete_n else ""
    if diff_base and (missing := _shown_diff(sprint_id, diff_base, head)[1]):
        return fail(missing)

    salvage_cmd = f"close.py sprint {sprint_id} salvage"
    if not (dry_run or resume):
        moves = rotate_artifacts(sprint_paths(sprint_id, round_n))
        if left := artifact_notice(moves, salvage_cmd):
            print("warning: " + left, file=sys.stderr)

    ran, reports = [], []
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
        )
        if notice:
            print(notice)
        return fail(err)

    def leg(stage: str, key: str, extra: list, charter: str = "") -> tuple[dict, str]:
        path = review.sprint_report_path(sprint_id, key, round_n)
        if not dry_run and (aside := rotate_artifacts([path, review.patch_path(path)])):
            print("warning: " + artifact_notice(aside, salvage_cmd), file=sys.stderr)
        if stage == "fixer":
            extra = [("Your patch", f"PATCH_PATH: {review.patch_path(path)}"), *extra]
        bundle = build(
            sprint_id, cards, base, path, charter or charters[stage], extra, authority, diff_base
        )
        stage_head = git("rev-parse", "HEAD").stdout.strip()
        role = stage if not complete_n else ""
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
            empty = {k: [] for k in review.REPORT_KEYS}
            return empty, review.abort_text(head, err) if err else ""
        report, report_err = review.read_report(path, stage=stage)
        if not report_err:  # `ran` is what the round CONTAINS: a stage that wrote
            ran.append(key)  # nothing did not cover it, whatever it was launched for
            reports.append(report)
        if err:  # stage_head, not head: an undo from the ROUND's start spans an applied fix
            return {k: [] for k in review.REPORT_KEYS}, review.abort_text(stage_head, err)
        print(result)  # before any refusal: the findings exist nowhere else yet
        if motion := review.check_reviewer_motion(stage_head, marker, digest_before, cards):
            return {k: [] for k in review.REPORT_KEYS}, motion
        if not report_err and stage == "fixer":
            report_err = review.apply_patch(path, cards)
        return report, review.abort_text(stage_head, report_err) if report_err else ""

    resume_announced = False

    def stage(stage_name: str, key: str, extra: list, charter: str = "") -> tuple[dict, str]:
        nonlocal resume_announced
        report, _error = sprint_review_resume.take(prefix, stage_name, key, reports, round_n)
        if report is not None:
            return report, ""
        if resume and not resume_announced:
            print(f"round {round_n} resumes at {key}")
            resume_announced = True
        return leg(stage_name, key, extra, charter)

    prior = [("Findings from earlier rounds", render_sprint_prior(rounds if complete_n else []))]
    if complete_n:
        fixed, err = leg("fixer", "fix", [("Sprint altitude", altitude), *prior], review.charter())
        if err:
            return stop(err)
        if dry_run:
            return 0
        closing = {k: [] for k in review.REPORT_KEYS}
    else:
        fixed = {k: [] for k in review.REPORT_KEYS}
        candidates = []
        for slug, prose in found:
            report, err = stage("finder", f"find-{slug}", [("Your angle", prose), *prior])
            if err:
                return stop(err)
            candidates += report["blocking"]
        if dry_run:
            print("(then: verifiers, the fixer, the closer)")
            return 0
        survivors = []
        batches = stages.batches(candidates, cap)
        verify_keys = [f"verify-{n}" for n in range(1, len(batches) + 1)]
        if prefix and (why := prefix.match_verifiers(verify_keys)):
            print(f"round {round_n}: cannot reuse verifiers: {why}")
        for n, batch in enumerate(batches, 1):
            judged = [("The candidates you are judging", "\n".join(f"- {c}" for c in batch))]
            report, err = stage("verifier", f"verify-{n}", judged)
            if err:
                return stop(err)
            survivors += report["blocking"]
        print(f"{len(candidates)} candidates, {len(survivors)} survived refutation")
        if survivors:
            told = [("The findings you must fix", "\n".join(f"- {s}" for s in survivors))]
            if prefix and prefix.open and head == reviewed_head and resume_round.get("fixed"):
                why = prefix.close("the tree is unchanged and carries none of the claimed fixes")
                print(f"round {round_n}: cannot reuse fix: {why}")
            fixed, err = stage("fixer", "fix", told)
            if err:
                return stop(err)
        closing, err = stage("closer", "close", [("What the fixer reported", json.dumps(fixed))])
        if err:
            return stop(err)
    shown_sha = git("rev-parse", "HEAD").stdout.strip()

    # Plan drift is safe to reject only after every sprint member is terminal.
    if sprint_cards(plan.read_text(), sprint_id) != cards:
        changed = f"sprint {sprint_id}'s cards changed during the review"
        return stop(review.abort_text(shown_sha, changed))
    round_ = {k: fixed[k] for k in review.REPORT_KEYS}
    round_["blocking"] += closing["blocking"]
    if clearable := closing.get(review.CLEARABLE_BY_FULL):
        round_[review.CLEARABLE_BY_FULL] = clearable
    fix_report = review.sprint_report_path(sprint_id, "fix", round_n)
    if err := review.write_reviewer_diff(fix_report, reviewed_head, f"sprint {sprint_id}"):
        # A rolled-back fix must not remain in the recorded round.
        if "fix" in ran and git("rev-parse", "HEAD").stdout.strip() == head:
            reports.pop([*(prefix.reused if prefix else []), *ran].index("fix"))
            ran.remove("fix")
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
    )
    print(
        f"round {round_n} recorded at {shown_sha[:8]}:"
        f" {len(round_['fixed'])} fixed, {len(round_['blocking'])} blocking"
    )
    return 0
