#!/usr/bin/env python3
"""Sprint close: the falsifier batch, the triage emission, and the release.

`start` is read-and-emit — it runs checks and prints what the human must judge,
and mutates nothing but appends. `land` opens the release PR. `post-merge` cuts
the bump and the tag on the sha that actually shipped, and retires the key.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
import overlap
import stages
from close import default_branch, fail, git, story_card
from env import refuse_direct_invocation
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


def sprint_stories(plan: str, sprint_id: str) -> list[str]:
    """The `####` cards under `### Sprint <id>`, and no others.

    Membership is an ARGUMENT, never "every non-done card in plan.md": the next
    sprint's stories are [ready] right now, so that reading refuses forever.
    The id must END here — a prefix match makes sprint 2 own sprint 20's cards.
    """
    out, inside, head = [], False, f"### Sprint {sprint_id}"
    for ln in plan.splitlines():
        if ln.startswith("### "):
            inside = ln.startswith(head) and not ln[len(head) : len(head) + 1].isdigit()
        elif inside and ln.startswith("#### "):
            out.append(ln)
    return out


def corpus(root: Path) -> list[tuple[str, str, str]]:
    """(id, headline, falsifier) for every record the batch must run — a resolved
    record contributing its RESOLUTION's falsifier. Keyed off the `## resolved`
    heading, never a `Resolves:` line anywhere in a block: a record that merely
    REFERENCES an id would silence a live bug with resolve's green-check never
    having run."""
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
    """(resolutions, the raw work.md section minus `## resolved`/`## archived`
    blocks) from ONE split. corpus() cannot serve the first: substitution is
    exactly where it discards the original falsifier a reader needs to judge."""
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
    """Built once per LEG, at launch: the closing pass must diff the tree the
    fixer left, and a bundle composed up front would hand it the pre-fix one."""
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
    """Run the full first review or a delta-scoped confirming round."""
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
    found, err = stages.angles()
    if err:
        return fail(err)
    cap, err = stages.batch_cap()
    if err:
        return fail(err)
    charters, err = stages.charters()
    if err:
        return fail(err)

    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    rounds = state.get("rounds", [])
    round_n = len(rounds) + 1
    complete_n = max((n for n, r in enumerate(rounds, 1) if "incomplete" not in r), default=0)
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    digest_before = review.marker_digest(marker)
    scoped, unnamed, diff_base, scope = found, [], "", []
    if complete_n:
        diff_base = state["shown_sha"]
        changed = git("diff", "--name-only", "--no-renames", f"{diff_base}..").stdout.splitlines()
        scoped, unnamed = [], set(changed)
        for slug, prose in found:
            path = review.sprint_report_path(sprint_id, f"find-{slug}", complete_n)
            named, err = review.named_paths(path, changed)
            if err:
                return fail(err)
            if named:
                scoped.append((slug, prose))
                why = "" if path.exists() else f"round-{complete_n} report absent; "
                print(f"re-run {slug}: {why}" + ", ".join(sorted(named)))
            else:
                print(f"skip {slug}: no round-{complete_n} finding named a changed path")
            unnamed -= named
        # in the RECORD, not only stdout: two counts cannot tell a scoped round from a sweep
        scope = [f"scoped: read {diff_base[:8]}..HEAD, {len(scoped)}/{len(found)} finders re-run"]
        if unnamed:
            print("closer covers unnamed delta paths: " + ", ".join(sorted(unnamed)))

    ran, reports = [], []

    def stop(err: str) -> int:
        if reports:
            round_ = {k: [i for r in reports for i in r[k]] for k in review.REPORT_KEYS}
            round_.update(incomplete=err, stages=ran)
            review.write_round(marker, state, round_)
            print(f"round {round_n} recorded incomplete after {', '.join(ran)}")
        return fail(err)

    def leg(stage: str, key: str, extra: list) -> tuple[dict, str]:
        path = review.sprint_report_path(sprint_id, key, round_n)
        if not dry_run:  # a preview must not delete the findings of a refused round
            path.unlink(missing_ok=True)
            review.patch_path(path).unlink(missing_ok=True)
        if stage == "fixer":
            extra = [("Your patch", f"PATCH_PATH: {review.patch_path(path)}"), *extra]
        bundle = build_sprint_bundle(
            sprint_id, cards, base, path, charters[stage], extra, diff_base
        )
        stage_head = git("rev-parse", "HEAD").stdout.strip()
        ran.append(key)
        result, err = review.run(bundle, Path.cwd(), dry_run, name=f"sprint {key}")
        if dry_run:  # an EMPTY report, not a shapeless one: a preview walks
            empty = {k: [] for k in review.REPORT_KEYS}
            return empty, ""
        report, report_err = review.read_report(path)
        if not report_err:
            reports.append(report)
        if err:
            return {k: [] for k in review.REPORT_KEYS}, review.abort_text(head, err)
        print(result)  # before any refusal: the findings exist nowhere else yet
        if motion := review.check_reviewer_motion(stage_head, marker, digest_before, cards):
            return {k: [] for k in review.REPORT_KEYS}, motion
        if not report_err and stage == "fixer":
            report_err = review.apply_patch(path, cards)
        return report, review.abort_text(stage_head, report_err) if report_err else ""

    prior = [("Findings from earlier rounds", render_sprint_prior(rounds if complete_n else []))]
    candidates = []
    for slug, prose in scoped:
        report, err = leg("finder", f"find-{slug}", [("Your angle", prose), *prior])
        if err:
            return stop(err)
        candidates += report["blocking"]
    if dry_run:
        print("(then: the closer)" if complete_n else "(then: verifiers, the fixer, the closer)")
        return 0

    fixed = {"fixed": [], "blocking": [], "noted": []}
    if not complete_n:
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
        closing_extra = [("What the fixer reported", json.dumps(fixed))]
    else:
        closing_extra = [
            ("Confirmation candidates", "\n".join(f"- {c}" for c in candidates) or "none"),
            ("Delta paths only you cover", "\n".join(sorted(unnamed)) or "none"),
            *prior,
        ]
    closing, err = leg("closer", "close", closing_extra)
    if err:
        return stop(err)

    # No diff covers the plan now. Cross-lane BY CONSTRUCTION here, safe only
    # because a sprint review runs when every member is [done]: a mid-sprint run
    # would refuse and blame itself for a lane's flip.
    if sprint_cards(plan.read_text(), sprint_id) != cards:
        changed = f"sprint {sprint_id}'s cards changed during the review"
        return stop(review.abort_text(head, changed))
    round_ = {
        "fixed": fixed["fixed"],
        "blocking": fixed["blocking"] + closing["blocking"],
        "noted": fixed["noted"] + scope,
    }
    shown_sha = git("rev-parse", "HEAD").stdout.strip()
    fix_report = review.sprint_report_path(sprint_id, "fix", round_n)
    if err := review.write_reviewer_diff(fix_report, head, f"sprint {sprint_id}"):
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
    if unfinished := [m for m in members if "[done]" not in m]:
        return fail(
            "refused: sprint "
            + sprint_id
            + " has unfinished stories:\n  "
            + "\n  ".join(unfinished)
        )

    root = data_root()
    batch = corpus(root)
    grouped = {}
    for eid, head, falsifier in batch:
        grouped.setdefault(falsifier, []).append((eid, head))
    # the red path is the re-run path, so re-file only what is not already a bug
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


def _coverage_refusal(sprint_id: str, head: str) -> str:
    """ "" if a recorded round covers HEAD, else why not. Bug c9b48a66.

    HEAD coverage only — deliberately no "trunk moved since the review" clause:
    that is trunk motion, a different guard's business, and copying it here from
    close.cmd_land is the wrong half of the symmetry.
    """
    marker = sprint_marker(sprint_id)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    rerun = f"run `close.py sprint {sprint_id} review`"
    if not (rounds := state.get("rounds") or []):
        return f"refused: no recorded review for sprint {sprint_id} — {rerun}"
    if incomplete := rounds[-1].get("incomplete"):
        detail = incomplete.replace("\n", "\n  ")
        return f"refused: the last review round is incomplete:\n  {detail}"
    if blocking := rounds[-1]["blocking"]:
        return (
            "refused: the last round left blocking findings:\n  "
            + "\n  ".join(blocking)
            + "\nFix them, then review again — a flag cannot clear these"
        )
    if (shown := str(state.get("shown_sha"))) == head:
        return ""
    # check=False: a rebased, reset or gc'd sha must refuse, never raise
    # CalledProcessError from inside the gate that guards the release
    moved = git("diff", "--name-only", shown, head, check=False)
    if moved.returncode != 0:
        return f"refused: the review recorded {shown[:8]}, which no longer exists — {rerun}"
    # BEFORE the authorship branch: an empty range reads there as "no strays"
    if git("merge-base", "--is-ancestor", shown, head, check=False).returncode:
        return (
            f"refused: HEAD does not contain {shown[:8]}, the tree the round covered"
            f" — the recorded round describes no tree that exists. {rerun}"
        )
    # AUTHORSHIP, the story leg's rule: the review leg's fixer commits inside the
    # range its round covers, so a bare sha compare refuses the release over the
    # fixes the review exists to produce. Never over a GATE_FILE, whatever signed
    # it — patch application permits any `.xp/` path a sprint card declares.
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
    # start's tier is stale by construction: SKILL.md puts triage, the retro and the
    # release artifacts BETWEEN it and here, so the tree that ships is never the one
    # that was measured (sprint-003: four commits, one of them this file). And what
    # ships is this branch MERGED into the default branch, which no leg here builds —
    # so the tier judges a trial merge, through the story leg's own gates(). BELOW
    # the dry-run return because a preview runs nothing, and ABOVE the gh check so a
    # red tier is what you are told about, not a missing binary.
    if red := overlap.gates(ref, "", "full", pending):
        return fail(red)
    # Assent is given by RUNNING land, where close.cmd_land's rationale applies
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
