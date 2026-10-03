#!/usr/bin/env python3
"""Plan review as a headless role through the runner both harnesses use.

Codex teammates have neither `--plugin-dir` nor subagents; the script is what
makes the shipped charter reachable there.
"""

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))

import review
from close import fail, story_card
from plan_disposition import disposition_fields as disposition_fields
from plan_disposition import disposition_object as disposition_object
from plan_disposition import durable_disposition as durable_disposition
from plan_disposition import evaluate_disposition as evaluate_disposition
from review_runner import archive_failed_findings, review_prior
from slate_review import review_findings_path, review_marker, run_detached
from spawn import _read, _read_shipped
from teammate_tee import agent_log_id, log_path
from work import chdir_repo_root, data_root, plan_path, ready_marker_path

PLUGIN_ROOT = Path(__file__).parent.parent


class ReviewResult(tuple):
    def __new__(cls, rc: int, outcome: str, acceptance: dict | None = None):
        result = super().__new__(cls, (rc, outcome))
        result.acceptance = acceptance
        return result


def findings_path(story_id: str) -> Path:
    return review_findings_path(story_id, "plan")


def incomplete_marker(story_id: str) -> Path:
    """Written BEFORE the reviewer launches and removed only on findings.

    Inverted deliberately: the failure that matters kills the process (codex's
    shell timeout_ms is model-supplied, ~10s by default, and a review runs
    minutes), and a killed process writes nothing on its way out. So absence of
    the marker is the success signal, and its presence outlives any death.
    """
    return review_marker(story_id, "plan")


def card_for(story_id: str) -> str:
    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError):
        return ""


def build_bundle(
    charter: str, plan: str, card: str, plan_file: Path, out: Path, prior: str = ""
) -> str:
    sections = [
        ("Your charter", charter),
        ("Your findings file", f"FINDINGS_PATH: {out}"),
        ("The plan file", f"PLAN_PATH: {plan_file}"),
        ("The plan under review", plan),
        ("Story card", card),
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        ("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),
        ("Constraints", _read(Path(".xp/constraints.md"))),
        ("System context", _read(Path(".xp/system.md"))),
    ]
    if prior:
        sections.insert(5, ("Findings from prior rounds", prior))
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def review_state(plan_file: Path, story_id: str) -> tuple:
    """State a plan reviewer must leave unchanged outside its draft.

    THIS STORY'S OWN CARD, never the whole plan: plan.md is project-global and the
    lead edits it throughout a run — status flips, re-mints, a sibling lane's card
    — so a whole-file digest refuses a review that did nothing wrong, and blames
    the reviewer by name for it (bug 5a1abadb, which cost story-032 a full run).
    close.review.check_reviewer_motion already scopes its card check this way.
    """

    from git_source import tracked_state

    root = Path.cwd().resolve()
    excluded = [
        str(path.resolve().relative_to(root))
        for path in (plan_file, plan_path())
        if path.resolve().is_relative_to(root)
    ]
    source = tracked_state(excluded)
    return source["head"], source["status"], card_for(story_id), source


def plan_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _cmd_review(
    story_id: str, plan_file: Path, dry_run: bool, detach: bool = True, review_card: bool = False
) -> tuple[int, str]:
    if not plan_file.is_file():
        return fail(f"refused: no plan at {plan_file} — draft it to a file first"), "failed"
    plan = plan_file.read_text()
    if not plan.strip():
        return fail(f"refused: the draft plan at {plan_file} is empty"), "failed"
    # An empty read would spend a whole review on no rubric and still exit 0 with
    # plausible prose: nothing downstream can tell that from a real round.
    charter = review.charter("plan-reviewer")
    if not charter:
        rc = fail(
            f"refused: {PLUGIN_ROOT / 'agents' / 'plan-reviewer.md'} carries no charter"
            " — a review with an empty rubric certifies. Restore the file"
        )
        return rc, "failed"
    card = card_for(story_id)
    if not card:
        return fail(f"refused: no {story_id} card in {plan_path()}"), "failed"
    prior, problem = review_prior(story_id, "plan")
    if problem:
        return fail(problem), "failed"
    out = findings_path(story_id)
    if dry_run:
        return _run_review(story_id, plan_file, charter, plan, card, out, True, prior)
    if not detach:
        for path in (out, incomplete_marker(story_id)):
            path.parent.mkdir(parents=True, exist_ok=True)
        resume = shlex.join(
            [
                sys.executable,
                str(Path(__file__).with_name("spawn.py").resolve()),
                "resume",
                story_id,
            ]
        )
        incomplete_marker(story_id).write_text(
            json.dumps(
                {
                    "findings": str(out),
                    "log": str(
                        log_path(data_root(), agent_log_id("plan-reviewer", "plan-reviewer", card))
                    ),
                    "state": "PLAN REVIEW DID NOT COMPLETE",
                    "next": f"run {resume} to resume the story",
                }
            )
        )
        return _run_review(story_id, plan_file, charter, plan, card, out, False, prior, review_card)
    rc = run_detached(
        story_id, "plan", out, [str(Path(__file__).resolve()), story_id, str(plan_file)]
    )
    return rc, "ran" if rc == 0 else "failed"


def cmd_review(story_id: str, plan_file: Path, dry_run: bool, detach: bool = True) -> int:
    return _cmd_review(story_id, plan_file, dry_run, detach)[0]


def run_foreground(story_id: str, plan_file: Path) -> tuple[int, str]:
    """spawn's own stage: no detached child, and cmd_review's guards all still run
    — an absent plan, an empty one, an empty charter and a missing card each end a
    round that would otherwise report a verdict nothing produced."""
    return _cmd_review(story_id, plan_file, False, detach=False, review_card=True)


def _run_review(
    story_id: str,
    plan_file: Path,
    charter: str,
    plan: str,
    card: str,
    out: Path,
    dry_run: bool,
    prior: str = "",
    review_card: bool = False,
) -> tuple[int, str]:
    try:
        before = review_state(plan_file, story_id)
        from ready import credential

        minted_before = credential(ready_marker_path(story_id)) if review_card else None
    except (OSError, ValueError, UnicodeError) as e:
        return fail(f"refused: cannot snapshot the repository before review: {e}"), "failed"
    accepted = None
    before_plan = plan_bytes(plan_file)
    from plan_acceptance import candidate_path, prepare, publish, receipt_path
    from plan_writer import CardEditRefusal

    candidate = candidate_path(out) if review_card and not dry_run else None
    if candidate:
        candidate.write_text(card)
    bundle = build_bundle(charter, plan, card, plan_file, out, prior)
    if candidate:
        bundle += f"## The locked card candidate\n\nCARD_CANDIDATE_PATH: {candidate}\n"

    result, err = review.run(bundle, Path.cwd(), dry_run, name="plan-reviewer", card=card)
    if dry_run:
        return (fail("refused: " + err), "failed") if err else (0, "ran")

    def refused(message: str, outcome: str = "failed") -> tuple[int, str]:
        archived = archive_failed_findings(out) if outcome == "failed" else ""
        return ReviewResult(fail(message + archived), outcome, accepted)

    try:
        changed = review_state(plan_file, story_id) != before
        if review_card:
            changed |= credential(ready_marker_path(story_id)) != minted_before
    except (OSError, ValueError, UnicodeError) as e:
        return refused(f"refused: the plan reviewer left the repository unreadable: {e}")
    if changed:
        return refused(
            "refused: the plan reviewer changed the repository or story card"
            " — inspect and restore its changes before continuing"
        )
    if err:
        return refused(err)
    try:
        findings = out.read_text().strip() if out.is_file() else ""
    except (OSError, UnicodeError) as error:
        return refused(f"refused: cannot read plan-review findings at {out}: {error}")
    if not findings:
        findings = result.strip()
        if not findings:
            return refused(f"refused: the plan reviewer wrote no findings at {out}")
        try:
            out.write_text(findings)
        except OSError as error:
            return refused(f"refused: cannot write plan-review findings at {out}: {error}")
    after_plan = plan_bytes(plan_file)
    if after_plan is None:
        retry = shlex.join(
            [sys.executable, str(Path(__file__).resolve()), story_id, str(plan_file)]
        )
        return refused(
            f"refused: cannot read the reviewed plan at {plan_file}; restore a readable plan"
            f" there, then rerun `{retry}`"
        )
    try:
        after_card = candidate.read_text() if candidate else card
    except (OSError, UnicodeError) as error:
        return refused(f"refused: cannot read review candidate: {error}; restore {candidate}")
    outcome, problem = evaluate_disposition(findings, before_plan, after_plan, card, after_card)
    if outcome in {"ran", "blocked"} and candidate:
        try:
            record = prepare(story_id, card, candidate, plan_file, out)
            if review_state(plan_file, story_id) != before:
                raise ValueError("story card moved before acceptance; inspect concurrent edits")
            if credential(ready_marker_path(story_id)) != minted_before:
                raise ValueError("credential moved before acceptance; inspect concurrent amendment")

            def source_check(applied=False):
                expected = (*before[:2], record["after"] if applied else before[2], before[3])
                if review_state(plan_file, story_id) != expected:
                    raise CardEditRefusal(
                        "tracked source moved during plan publication; inspect retained work"
                    )

            publish(story_id, record, source_check)
            accepted = record
        except (OSError, ValueError, KeyError, CardEditRefusal) as error:
            if not receipt_path(out).exists():
                resume = shlex.join(
                    [sys.executable, str(Path(__file__).with_name("spawn.py")), "resume", story_id]
                )
                return refused(
                    f"refused: invalid review candidate: {error}; nothing was applied and the"
                    f" next round rewrites {candidate} from the current card — run `{resume}`"
                    " for a fresh plan review"
                )
            retry = shlex.join(
                [
                    sys.executable,
                    str(Path(__file__).with_name("plan_acceptance.py")),
                    story_id,
                    str(out),
                ]
            )
            return fail(
                f"refused: review candidate cannot apply: {error}. Repair the "
                f"recorded candidate/artifacts and re-apply this completed round with `{retry}`"
            ), "failed"

    if problem:
        if outcome == "blocked":
            marker = incomplete_marker(story_id)
            try:
                state = json.loads(marker.read_text())
            except (OSError, ValueError):
                state = {}
            marker.write_text(
                json.dumps(state | {"state": "PLAN REVIEW BLOCKED", "disposition": "blocked"})
            )
        return refused(f"refused: {problem}", outcome)
    incomplete_marker(story_id).unlink(missing_ok=True)  # the child's own verdict
    print(findings)
    return ReviewResult(0, outcome, accepted)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("story_id")
    p.add_argument("plan_file", help="the draft plan to review")
    p.add_argument("--dry-run", action="store_true")
    # the detached half re-enters here; not a user surface, hence the name
    p.add_argument("--_review", default="", help=argparse.SUPPRESS)
    a = p.parse_args()
    # resolved BEFORE the chdir, or a relative path names a different file after it
    plan_file = Path(a.plan_file).resolve()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if a._review:
        charter = review.charter("plan-reviewer")
        card = card_for(a.story_id)
        prior, problem = review_prior(a.story_id, "plan")
        if problem:
            return fail(problem)
        return _run_review(
            a.story_id,
            plan_file,
            charter,
            plan_file.read_text(),
            card,
            Path(a._review),
            False,
            prior,
        )[0]
    return cmd_review(a.story_id, plan_file, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
