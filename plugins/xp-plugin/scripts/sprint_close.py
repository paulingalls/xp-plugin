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
from close import config_flat, default_branch, fail, git, story_card
from work import (
    append,
    config_block_value,
    data_root,
    entries,
    falsifier_is_green,
    stamp,
    work_entries_since,
)

PLUGIN_ROOT = Path(__file__).parent.parent
FALSIFIER = re.compile(r"^Falsifier: `(.+)`$", re.M)
RESOLVES = re.compile(r"^Resolves: (\w+)$", re.M)
LENSES = ("broad", "security")


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
    archive = root / "archive.md"
    if archive.exists():
        for m in FALSIFIER.finditer(archive.read_text()):
            records[f"archive:{len(records)}"] = ("archive.md entry", m.group(1))
    return [(eid, head, resolutions.get(eid, f)) for eid, (head, f) in records.items()]


def sprint_cards(plan: str, sprint_id: str) -> str:
    return "\n".join(story_card(plan, ln.split()[1])[0] for ln in sprint_stories(plan, sprint_id))


def sprint_marker(sprint_id: str, lens: str) -> Path:
    d = data_root() / "markers" / "sprint"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sprint_id}.{lens}.json"


def _sprint_records(root: Path, since_epoch: int) -> tuple[str, str]:
    """(resolutions, the raw work.md section minus its `## resolved` blocks) from
    ONE split. corpus() cannot serve the first: substitution is exactly where it
    discards the original falsifier a reader needs to judge the swap."""
    originals = {e: t for e, t in entries(root) if t.startswith(("## bug ", "## debt "))}
    latest, kept = {}, []
    for block in re.split(r"^(?=## )", work_entries_since(since_epoch), flags=re.M):
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


def build_sprint_bundle(sprint_id: str, lens: str, cards: str, base: str, report: Path) -> str:
    import review
    from bookkeep import render_sprint_prior
    from close import _read_first

    state = json.loads(p.read_text()) if (p := sprint_marker(sprint_id, lens)).exists() else {}
    resolutions, work_md = _sprint_records(
        data_root(), int(git("show", "-s", "--format=%ct", base).stdout.strip())
    )
    sections = [
        (f"Your charter, for the {lens} lens", review.charter("sprint-reviewer")),
        ("Your report", f"REPORT_PATH: {report}"),
        (f"The stories in sprint {sprint_id}", cards),
        ("Findings from earlier rounds of THIS lens", render_sprint_prior(state.get("rounds", []))),
        ("Cumulative sprint diff", git("diff", f"{base}..HEAD").stdout),
        ("Resolutions filed during the sprint", resolutions),
        ("work.md entries filed during the sprint", work_md),
        ("PROCESS", _read_first(str(PLUGIN_ROOT / "PROCESS.md"))),
        ("VALUES", _read_first(str(PLUGIN_ROOT / "VALUES.md"))),
        ("Constraints", _read_first(".xp/constraints.md")),
        ("System context", _read_first(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def cmd_review(sprint_id: str, lens: str, dry_run: bool) -> int:
    import review

    if lens not in LENSES:
        return fail(f"refused: --lens must be one of {', '.join(LENSES)}, not {lens!r}")
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — commit or stash first")
    plan = Path(".xp/plan.md")
    if not plan.exists():
        return fail("refused: no .xp/plan.md here — is this an xp-managed repo?")
    trunk = default_branch()
    if (branch := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) == trunk:
        return fail(
            f"refused: review the sprint from its branch, not {branch} — the diff"
            " against the default branch would be empty and certify nothing"
        )
    if not (cards := sprint_cards(plan.read_text(), sprint_id)):
        return fail(f"refused: no `### Sprint {sprint_id}` section in .xp/plan.md")

    marker = sprint_marker(sprint_id, lens)
    state = json.loads(marker.read_text()) if marker.exists() else {}
    path = review.sprint_report_path(sprint_id, lens, len(state.get("rounds", [])) + 1)
    if not dry_run:  # a preview must not delete the findings of a refused round
        path.unlink(missing_ok=True)
    # BOTH before the launch: the reviewer may not move the tree, and recording a
    # post-run head would make anything it moved count as reviewed.
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    digest_before = review.marker_digest(marker)
    bundle = build_sprint_bundle(sprint_id, lens, cards, base, path)
    result, err = review.run(bundle, Path.cwd(), dry_run, name="sprint-reviewer")
    if dry_run:
        return 0
    if err:
        return fail(review.abort_text(head, err))
    print(result)  # before any refusal: the findings exist nowhere else yet
    if motion := review.check_report_only(head, marker, digest_before):
        return fail(motion)
    report, err = review.read_report(path)
    if err:
        return fail(review.abort_text(head, err))
    state.setdefault("rounds", []).append(report)
    state["shown_sha"] = head
    marker.write_text(json.dumps(state))
    print(f"{lens} round {len(state['rounds'])} recorded at {head[:8]}")
    return 0


def cmd_start(sprint_id: str) -> int:
    plan = Path(".xp/plan.md")
    if not plan.exists():
        return fail("refused: no .xp/plan.md here — is this an xp-managed repo?")
    members = sprint_stories(plan.read_text(), sprint_id)
    if not members:
        return fail(f"refused: no `### Sprint {sprint_id}` section in .xp/plan.md")
    if unfinished := [m for m in members if "[done]" not in m]:
        return fail(
            "refused: sprint "
            + sprint_id
            + " has unfinished stories:\n  "
            + "\n  ".join(unfinished)
        )

    root = data_root()
    batch = corpus(root)
    # the red path is the re-run path, so re-file only what is not already a bug
    known = {f for _e, h, f in batch if h.startswith("bug ")}
    for eid, head, falsifier in batch:
        if not falsifier_is_green(falsifier):
            if falsifier not in known:
                append(
                    root,
                    f"## bug {stamp()}\nClaim: a falsifier in the sprint-close batch RED"
                    f" for record {eid} ({head}). A debt or archived falsifier asserts the"
                    " system is still OK, so red means the latent problem materialised.\n"
                    f"Falsifier: `{falsifier}`\nFiles: unknown\n\n",
                )
            filed = "already filed as a bug" if falsifier in known else "Re-filed as a bug"
            return fail(
                f"refused: batch falsifier RED for {eid} ({head}):\n  {falsifier}\n"
                f"{filed}. Fix it, then run start again"
            )

    if tier := config_block_value("tests", "full"):
        print(f"running the full tier: {tier}")
        if subprocess.run(tier, shell=True).returncode != 0:
            return fail(f"refused: full tier red: {tier}")

    notes = [t for _eid, t in entries(root) if t.startswith("## note ")]
    print(f"\n{len(members)} stories, {len(notes)} notes to triage. Each note: promote to")
    print("constraints.md/system.md via the retro diff, or archive it.\n")
    for text in notes:
        lines = text.splitlines()
        print(f"  {lines[0][3:]} — {(lines[1] if len(lines) > 1 else '')[:100]}")
    print("\n" + (PLUGIN_ROOT / "templates" / "retro.md").read_text())
    print(
        "Then write the sprint digest yourself — this leg emits facts, never a"
        " narrative (constraint 7). First line: # Session digest — written <ISO-ts> at <short-sha>"
    )
    return 0


def _next_version() -> str:
    """Minor bump off the latest TAG — a sprint release is a minor. The tag is the
    source of truth: a plugin.json path is meaningless in a consuming project,
    which is also why the scheme is checked: theirs is the input we don't pick.
    Returns "" when the latest tag is not semver, so the caller refuses."""
    latest = git("describe", "--tags", "--abbrev=0", check=False).stdout.strip() or "v0.0.0"
    if not (m := re.fullmatch(r"v?(\d+)\.(\d+)(\..*)?", latest)):
        return ""
    return f"v{m.group(1)}.{int(m.group(2)) + 1}.0"


def _refuse_unbumpable() -> int:
    latest = git("describe", "--tags", "--abbrev=0", check=False).stdout.strip()
    return fail(f"refused: latest tag {latest!r} is not vMAJOR.MINOR — cannot bump it")


def _coverage_refusal(sprint_id: str, head: str) -> str:
    """ "" if a round of EVERY lens covers HEAD, else why not. Bug c9b48a66.

    HEAD coverage only — deliberately no "trunk moved since the review" clause:
    that is trunk motion, a different guard's business, and copying it here from
    close.cmd_land is the wrong half of the symmetry.
    """
    exempt = []
    for lens in LENSES:
        marker = sprint_marker(sprint_id, lens)
        state = json.loads(marker.read_text()) if marker.exists() else {}
        rerun = f"run `close.py sprint {sprint_id} review --lens {lens}`"
        if not (rounds := state.get("rounds") or []):
            return f"refused: no recorded {lens} review for sprint {sprint_id} — {rerun}"
        if blocking := rounds[-1]["blocking"]:
            return (
                f"refused: the last {lens} round left blocking findings:\n  "
                + "\n  ".join(blocking)
                + "\nFix them, then review again — a flag cannot clear these"
            )
        if (shown := str(state.get("shown_sha"))) == head:
            continue
        # check=False: a rebased, reset or gc'd sha must refuse, never raise
        # CalledProcessError from inside the gate that guards the release
        moved = git("diff", "--name-only", shown, head, check=False)
        if moved.returncode != 0:
            return (
                f"refused: the {lens} review recorded {shown[:8]}, which no longer exists — {rerun}"
            )
        if code := [f for f in moved.stdout.split() if not f.startswith(".xp/")]:
            return (
                f"refused: the {lens} review did not cover HEAD — {', '.join(code)}"
                f" changed since {shown[:8]}. {rerun}"
            )
        exempt += moved.stdout.split()
    if exempt:
        print(f"reviewed earlier; the delta since is .xp/ only: {', '.join(sorted(set(exempt)))}")
    return ""


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import shutil

    if refusal := _coverage_refusal(sprint_id, git("rev-parse", "HEAD").stdout.strip()):
        return fail(refusal)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not (version := _next_version()):
        return _refuse_unbumpable()
    cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", f"release {version}", "--body", f"Sprint {sprint_id}"],
    ]
    if dry_run:
        for c in cmds:
            print(" ".join(c))
        print(
            f"(then: close.py sprint {sprint_id} post-merge — bump, tag {version}, retire the key)"
        )
        return 0
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
    """Bump, tag and key retirement in ONE leg, on the merged sha.

    A tag cut at PR-open names a commit that is not the release: the review
    commits the PR exists to produce land after it, and a fetched tag never moves.
    """
    if (head := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) != (
        trunk := default_branch()
    ):
        return fail(f"refused: on {head}, not {trunk} — the release tag names the MERGED sha")
    sprint_branch = config_flat("sprint_branch")
    if (
        sprint_branch
        and git("merge-base", "--is-ancestor", sprint_branch, "HEAD", check=False).returncode != 0
    ):
        return fail(
            f"refused: {sprint_branch} is not merged into {trunk} — tagging here would"
            " name a commit containing none of the sprint. Merge the release PR first"
        )
    if not (version := _next_version()):
        return _refuse_unbumpable()
    if git("rev-parse", "--verify", "-q", f"refs/tags/{version}", check=False).returncode == 0:
        return fail(f"refused: tag {version} already exists — nothing was changed")
    config = Path(".xp/config.yml")
    if not config.exists():
        return fail("refused: no .xp/config.yml here — is this an xp-managed repo?")
    kept = [
        ln
        for ln in config.read_text().splitlines(keepends=True)
        if not ln.startswith("sprint_branch:")
    ]
    if git("tag", version, check=False).returncode != 0:
        return fail(f"refused: could not create tag {version}")
    config.write_text("".join(kept))
    print(
        f"tagged {version} at {git('rev-parse', 'HEAD').stdout.strip()[:8]}; sprint_branch retired"
    )
    print("commit the config change, push the tag, and open the next sprint")
    return 0
