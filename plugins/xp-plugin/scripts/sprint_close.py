#!/usr/bin/env python3
"""Sprint opening and close: branch state, checks, review, release."""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
import lifecycle as lc
import milestone
import overlap
import stages
from close import config_flat, default_branch, fail, git, story_card
from env import record_sprint_branch, refuse_direct_invocation, sprint_branch
from release import cmd_post_merge as release_post_merge
from release import next_version, refuse_unbumpable
from review import reviewer_strays
from work import (
    append,
    config_block_value,
    data_root,
    entries,
    falsifier_is_green,
    missing_plan_refusal,
    plan_path,
    record_summary,
    stamp,
    work_entries_since,
)

PLUGIN_ROOT = Path(__file__).parent.parent
FALSIFIER = re.compile(r"^Falsifier: `(.+)`$", re.M)
RESOLVES = re.compile(r"^Resolves: (\w+)$", re.M)
sprint_stories = milestone.sprint_stories


def corpus(root: Path) -> list[tuple[str, str, str]]:
    """Use resolved headings, not references, to substitute batch falsifiers."""
    records, resolutions = {}, {}
    for eid, text in entries(root):
        head = text.splitlines()[0]
        if head.startswith("## resolved "):
            ref, m = RESOLVES.search(text), FALSIFIER.search(text)
            if ref and m:
                resolutions[ref.group(1)] = m.group(1)
        elif head.startswith(("## bug ", "## debt ")) and (m := FALSIFIER.search(text)):
            claim = next((ln for ln in text.splitlines() if ln.startswith("Claim: ")), "")
            records[eid] = (f"{head[3:]} — {claim[7:97]}", m.group(1))
    return [(eid, head, resolutions.get(eid, f)) for eid, (head, f) in records.items()]


def sprint_cards(plan: str, sprint_id: str) -> str:
    return "\n".join(story_card(plan, ln.split()[1])[0] for ln in sprint_stories(plan, sprint_id))


def sprint_marker(sprint_id: str) -> Path:
    d = data_root() / "markers" / "sprint"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sprint_id}.json"


def _sprint_records(root: Path, since_epoch: int) -> tuple[str, str]:
    """Keep original falsifiers for review while corpus substitutes the batch copy."""
    originals = {e: t for e, t in entries(root) if t.startswith(("## bug ", "## debt "))}
    latest, kept = {}, []
    for block in re.split(r"^(?=## )", work_entries_since(since_epoch), flags=re.M):
        if block.startswith("## archived "):
            continue
        if not block.startswith("## resolved "):
            kept.append(block)
        elif (ref := RESOLVES.search(block)) and (new := FALSIFIER.search(block)):
            latest[ref.group(1)] = new.group(1)
    out = []
    for ref, new in latest.items():
        text = originals.get(ref, "")
        claim = next((ln[7:] for ln in text.splitlines() if ln.startswith("Claim: ")), "")
        old = FALSIFIER.search(text)
        out.append(
            f"- {ref}: {claim or '(no record with this id)'}\n  original falsifier:"
            f" `{old.group(1) if old else '(none)'}`\n  replacement: `{new}`"
        )
    return "\n".join(out) or "none", "\n".join(kept).strip() or "none"


def build_sprint_bundle(
    sprint_id: str, cards: str, base: str, report: Path, charter: str, extra: list, diff_base=""
) -> str:
    """Build at launch so the closer sees the fixer's tree."""
    from close import _read

    resolutions, work_md = _sprint_records(
        data_root(), int(git("show", "-s", "--format=%ct", base).stdout.strip())
    )
    title = "The delta since the last recorded round" if diff_base else "Cumulative sprint diff"
    sections = [
        ("Your charter", charter),
        ("Your report", f"REPORT_PATH: {report}"),
        *extra,
        (f"The stories in sprint {sprint_id}", cards),
        (title, git("diff", f"{diff_base or base}..HEAD").stdout),
        ("Resolutions filed during the sprint", resolutions),
        ("work.md entries filed during the sprint", work_md),
        ("PROCESS", _read(str(PLUGIN_ROOT / "PROCESS.md"))),
        ("VALUES", _read(str(PLUGIN_ROOT / "VALUES.md"))),
        ("Constraints", _read(".xp/constraints.md")),
        ("System context", _read(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def cmd_review(sprint_id: str, dry_run: bool) -> int:
    import review
    from bookkeep import render_sprint_prior

    if git("status", "--porcelain").stdout.strip():
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
    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    rounds = state.get("rounds", [])
    round_n = len(rounds) + 1
    complete_n = max((n for n, r in enumerate(rounds, 1) if not r.get("incomplete")), default=0)
    found, cap, charters, altitude = [], 0, {}, ""
    if complete_n:
        altitude, err = stages.altitude()
        if err:
            return fail(err)
    else:
        found, err = stages.angles()
        if err:
            return fail(err)
        cap, err = stages.batch_cap()
        if err:
            return fail(err)
        charters, err = stages.charters()
        if err:
            return fail(err)
        stages.check_roles(cards)
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    digest_before = review.marker_digest(marker)
    diff_base = state["shown_sha"] if complete_n else ""
    if diff_base and (missing := _shown_diff(sprint_id, diff_base, head)[1]):
        return fail(missing)

    ran, reports = [], []

    def stop(err: str) -> int:
        if reports:
            err = err.replace(review.NO_ROUND, f"Round {round_n} IS recorded, incomplete.")
            seen = {k: dict.fromkeys(i for r in reports for i in r[k]) for k in review.REPORT_KEYS}
            round_ = {k: list(v) for k, v in seen.items()} | {"incomplete": err, "stages": ran}
            review.write_round(marker, state, round_)
            print(f"round {round_n} recorded incomplete after {', '.join(ran)}")
        return fail(err)

    def leg(stage: str, key: str, extra: list, charter: str = "") -> tuple[dict, str]:
        path = review.sprint_report_path(sprint_id, key, round_n)
        if not dry_run:  # a preview must not delete the findings of a refused round
            path.unlink(missing_ok=True)
            review.patch_path(path).unlink(missing_ok=True)
        if stage == "fixer":
            extra = [("Your patch", f"PATCH_PATH: {review.patch_path(path)}"), *extra]
        bundle = build_sprint_bundle(
            sprint_id, cards, base, path, charter or charters[stage], extra, diff_base
        )
        stage_head = git("rev-parse", "HEAD").stdout.strip()
        role = stage if not complete_n else ""
        result, err = review.run(
            bundle, Path.cwd(), dry_run, f"sprint {key}", cards if role else "", role
        )
        if dry_run:  # an EMPTY report, not a shapeless one: a preview walks
            empty = {k: [] for k in review.REPORT_KEYS}
            return empty, review.abort_text(head, err) if err else ""
        report, report_err = review.read_report(path)
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
            report, err = leg("finder", f"find-{slug}", [("Your angle", prose), *prior])
            if err:
                return stop(err)
            candidates += report["blocking"]
        if dry_run:
            print("(then: verifiers, the fixer, the closer)")
            return 0
        survivors = []
        for n, batch in enumerate(stages.batches(candidates, cap), 1):
            judged = [("The candidates you are judging", "\n".join(f"- {c}" for c in batch))]
            report, err = leg("verifier", f"verify-{n}", judged)
            if err:
                return stop(err)
            survivors += report["blocking"]
        print(f"{len(candidates)} candidates, {len(survivors)} survived refutation")
        if survivors:
            told = [("The findings you must fix", "\n".join(f"- {s}" for s in survivors))]
            fixed, err = leg("fixer", "fix", told)
            if err:
                return stop(err)
        closing, err = leg("closer", "close", [("What the fixer reported", json.dumps(fixed))])
        if err:
            return stop(err)
    shown_sha = git("rev-parse", "HEAD").stdout.strip()

    # Plan drift is safe to reject only after every sprint member is terminal.
    if sprint_cards(plan.read_text(), sprint_id) != cards:
        changed = f"sprint {sprint_id}'s cards changed during the review"
        return stop(review.abort_text(shown_sha, changed))
    round_ = {k: fixed[k] for k in review.REPORT_KEYS}
    round_["blocking"] += closing["blocking"]
    fix_report = review.sprint_report_path(sprint_id, "fix", round_n)
    if err := review.write_reviewer_diff(fix_report, head, f"sprint {sprint_id}"):
        # A rolled-back fix must not remain in the recorded round.
        if "fix" in ran and git("rev-parse", "HEAD").stdout.strip() == head:
            reports.pop(ran.index("fix"))
            ran.remove("fix")
        return stop(err)
    review.write_round(marker, state, round_, reviewed_head=head, shown_sha=shown_sha)
    print(
        f"round {round_n} recorded at {shown_sha[:8]}:"
        f" {len(round_['fixed'])} fixed, {len(round_['blocking'])} blocking"
    )
    return 0


def cmd_start(sprint_id: str) -> int:
    plan = plan_path()
    if not plan.exists():
        return fail(f"refused: {missing_plan_refusal()}")
    members = sprint_stories(plan.read_text(), sprint_id)
    if not members:
        return fail(f"refused: no `### Sprint {sprint_id}` section in {plan}")
    branch = git("branch", "--show-current").stdout.strip()
    if not branch or branch == default_branch():
        return fail("refused: open the sprint from its freshly cut branch, not trunk")
    if not sprint_branch():
        if red := lc.run(config_flat(lc.KEY), "sprint-open", sprint_id):
            return fail(red)
        if red := milestone.move(sprint_id):
            return fail(red)
    opening = record_sprint_branch(branch)
    print(f"sprint branch: {branch}")
    if unfinished := [m for m in members if not m.endswith(("[done]", "[retired]"))]:
        if not opening:
            return fail(f"refused: sprint {sprint_id} is unfinished:\n  " + "\n  ".join(unfinished))
        print(f"recorded; {len(unfinished)} stories unfinished — close checks wait")
        return 0

    root = data_root()
    batch = corpus(root)
    grouped = {}
    for eid, head, falsifier in batch:
        grouped.setdefault(falsifier, []).append((eid, head))
    known = {f for _e, h, f in batch if h.startswith("bug ")}
    for falsifier, records in grouped.items():
        if not falsifier_is_green(falsifier):
            citations = "; ".join(f"{eid} ({head})" for eid, head in records)
            if falsifier not in known:
                append(
                    root,
                    f"## bug {stamp()}\nClaim: a falsifier in the sprint-close batch RED"
                    f" for records {citations}. A debt or archived falsifier asserts the"
                    " system is still OK, so red means the latent problem materialised.\n"
                    f"Falsifier: `{falsifier}`\nFiles: unknown\n\n",
                )
            filed = "already filed as a bug" if falsifier in known else "Re-filed as a bug"
            return fail(
                f"refused: batch falsifier RED for records {citations}:\n  {falsifier}\n"
                f"{filed}. Fix it, then run start again"
            )

    if tier := config_block_value("tests", "full"):
        print(f"running the full tier: {tier}")
        if subprocess.run(tier, shell=True).returncode != 0:
            return fail(f"refused: full tier red: {tier}")

    if completion := milestone.candidate(plan.read_text(), sprint_id):
        print(f"\n{completion.heading.rstrip()}")
        print(f"close.py sprint {sprint_id} milestone-done")

    disposed = {
        m.group(1)
        for _eid, text in entries(root)
        if (m := re.search(r"^(?:Archives|Resolves): (\w+)$", text, re.M))
    }
    notes = [
        text for eid, text in entries(root) if text.startswith("## note ") and eid not in disposed
    ]
    print(f"\n{len(members)} stories, {len(notes)} notes to triage. Each note: promote to")
    print("constraints.md/system.md via the retro diff, or archive it.\n")
    for text in notes:
        heading, body = record_summary(text)
        print(f"  {heading[3:]} — {body[:100]}")
    print("\n" + (PLUGIN_ROOT / "templates" / "retro.md").read_text())
    print(
        "Then write the sprint digest yourself — this leg emits facts, never a"
        " narrative; judgment belongs only where an LLM is present. First line:"
        " # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0


def _is_retro_prose(path: str) -> bool:
    return path.startswith(".xp/") and path not in overlap.GATE_FILES


def _shown_diff(sprint_id: str, shown: str, head: str) -> tuple[subprocess.CompletedProcess, str]:
    moved = git("diff", "--name-only", shown, head, check=False)
    if moved.returncode:
        action = (
            f"move {sprint_marker(sprint_id)} aside — it holds this sprint's recorded"
            f" rounds and moving it forfeits them — then run `close.py sprint"
            f" {sprint_id} review`"
        )
        return moved, f"refused: the review recorded {shown[:8]}, which no longer exists — {action}"
    return moved, ""


def _coverage_refusal(sprint_id: str, head: str) -> str:
    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    rerun = f"run `close.py sprint {sprint_id} review`"
    if not (rounds := state.get("rounds") or []):
        return f"refused: no recorded review for sprint {sprint_id} — {rerun}"
    if incomplete := rounds[-1].get("incomplete"):
        detail = incomplete.replace("\n", "\n  ")
        return (
            f"refused: the last review round is incomplete:\n  {detail}\n"
            f"Its findings are recorded and stand; clear what it names, then {rerun}"
        )
    if blocking := rounds[-1]["blocking"]:
        return (
            "refused: the last round left blocking findings:\n  "
            + "\n  ".join(blocking)
            + "\nFix them, then review again — a flag cannot clear these"
        )
    if (shown := str(state.get("shown_sha"))) == head:
        return ""
    moved, missing = _shown_diff(sprint_id, shown, head)
    if missing:
        return missing
    # BEFORE the authorship branch: an empty range reads there as "no strays"
    if git("merge-base", "--is-ancestor", shown, head, check=False).returncode:
        return (
            f"refused: HEAD does not contain {shown[:8]}, the tree the round covered"
            f" — the recorded round describes no tree that exists. {rerun}"
        )
    strays = reviewer_strays(shown, head)
    if not strays and not any(f in overlap.GATE_FILES for f in moved.stdout.splitlines()):
        print(f"the delta since {shown[:8]} is the reviewer's own fixes")
        return ""
    if code := [f for f in moved.stdout.splitlines() if not _is_retro_prose(f)]:
        return (
            f"refused: the review did not cover HEAD — {', '.join(code)}"
            f" changed since {shown[:8]}. {rerun}"
        )
    if exempt := moved.stdout.splitlines():
        print(f"reviewed earlier; the delta since is .xp/ only: {', '.join(sorted(set(exempt)))}")
    return ""


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import shutil

    import review

    if refusal := _coverage_refusal(sprint_id, git("rev-parse", "HEAD").stdout.strip()):
        return fail(refusal)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not (version := next_version()):
        return refuse_unbumpable()
    cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", f"release {version}", "--body", f"Sprint {sprint_id}"],
    ]
    ref = overlap.merge_source(default_branch(), "pr")
    pending = overlap.unmerged(ref)
    if dry_run:
        for c in cmds:
            print(" ".join(c))
        print(f"(then: close.py sprint {sprint_id} post-merge — tag {version}, retire the key)")
        full = config_block_value("tests", "full") or "none configured"
        print(f"(and first: the full tier — {full})")
        if pending:
            print(f"...on a trial merge with {ref} — staged, then aborted either way")
        return 0

    if dirty := git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: the working tree is dirty — the tier must judge the tree"
            " that ships, and these files are not in it:\n  " + dirty
        )
    # Triage can stale start's tier, so land measures the shipping merge again.
    if red := overlap.gates(ref, "", "full", pending):
        return fail(red)
    state = json.loads(sprint_marker(sprint_id).read_text())
    shown, rounds = state.get("shown_sha", ""), len(state.get("rounds", []))
    rng = f"{state.get('reviewed_head', shown)}..{shown}"
    if work := review.reviewer_range(state.get("reviewed_head", shown), shown):
        print("the reviewer changed this tree — you are merging its work:")
        print(work, end="")
        print(f"full diff: {review.diff_path(review.sprint_report_path(sprint_id, 'fix', rounds))}")
    if gates := [
        f for f in git("diff", "--name-only", rng).stdout.splitlines() if f in overlap.GATE_FILES
    ]:
        print(f"among them a gate file, which no later check re-reads: {', '.join(gates)}")
    if stale := review.reviewer_range(shown, git("rev-parse", "HEAD").stdout.strip()):
        print("reviewer commits from a round that never recorded — nothing covers these:")
        print(stale, end="")
    if not shutil.which("gh"):
        return fail(
            "refused: pr mode needs the gh CLI on PATH — install it, or open the PR by hand"
        )
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0:
            return fail(f"{c[0]} failed: {r.stderr.strip()}")
    print(f"release PR open. After it MERGES: close.py sprint {sprint_id} post-merge")
    return 0


def cmd_post_merge(sprint_id: str) -> int:
    return release_post_merge(sprint_id)


if __name__ == "__main__":
    refuse_direct_invocation("close.py sprint <id> <action>")
