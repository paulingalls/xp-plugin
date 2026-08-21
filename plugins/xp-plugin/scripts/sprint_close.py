#!/usr/bin/env python3
"""Sprint close: the falsifier batch, the triage emission, and the release.

`start` is read-and-emit — it runs checks and prints what the human must judge,
and mutates nothing but appends. `land` opens the release PR. `post-merge` cuts
the bump and the tag on the sha that actually shipped, and retires the key.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from close import config_flat, default_branch, fail, git
from work import append, data_root, entries, falsifier_is_green

PLUGIN_ROOT = Path(__file__).parent.parent
FALSIFIER = re.compile(r"^Falsifier: `(.+)`$", re.M)


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
    """(id, headline, falsifier) for every record the batch must run.

    A resolved record contributes its RESOLUTION's falsifier, not its original:
    resolution substitutes a claim-coupled check for one that no longer holds, so
    a wrong resolution reds here and the record reopens.

    Substitution is keyed off the `## resolved` heading `work.py resolve` writes,
    never off a `Resolves:` line anywhere in a block: a record that merely
    REFERENCES an id would otherwise substitute its own green falsifier and
    silence a live bug, with resolve's green-check never having run.
    """
    records, resolutions = {}, {}
    for eid, text in entries(root):
        head = text.splitlines()[0]
        if head.startswith("## resolved "):
            ref, m = re.search(r"^Resolves: (\w+)$", text, re.M), FALSIFIER.search(text)
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

    if tier := config_flat("full") or _tests_full():
        print(f"running the full tier: {tier}")
        if subprocess.run(tier, shell=True).returncode != 0:
            return fail(f"refused: full tier red: {tier}")

    root = data_root()
    batch = corpus(root)
    # the red path is the re-run path, so re-file only what is not already a bug
    known = {f for _e, h, f in batch if h.startswith("bug ")}
    for eid, head, falsifier in batch:
        if not falsifier_is_green(falsifier):
            if falsifier not in known:
                append(
                    root,
                    f"## bug {_stamp()}\nClaim: a falsifier in the sprint-close batch RED"
                    f" for record {eid} ({head}). A debt or archived falsifier asserts the"
                    " system is still OK, so red means the latent problem materialised.\n"
                    f"Falsifier: `{falsifier}`\nFiles: unknown\n\n",
                )
            filed = "already filed as a bug" if falsifier in known else "Re-filed as a bug"
            return fail(
                f"refused: batch falsifier RED for {eid} ({head}):\n  {falsifier}\n"
                f"{filed}. Fix it, then run start again"
            )

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


def _tests_full() -> str:
    from close import config_block_value

    return config_block_value("tests", "full")


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_version() -> str:
    """Minor bump off the latest TAG — a sprint release is a minor. The tag is the
    source of truth: a plugin.json path is meaningless in a consuming project."""
    latest = git("describe", "--tags", "--abbrev=0", check=False).stdout.strip() or "v0.0.0"
    major, minor, _patch = [*latest.lstrip("v").split("."), "0", "0"][:3]
    return f"v{major}.{int(minor) + 1}.0"


def cmd_land(sprint_id: str, dry_run: bool) -> int:
    import shutil

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    version = _next_version()
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
    version = _next_version()
    if git("rev-parse", "--verify", "-q", f"refs/tags/{version}", check=False).returncode == 0:
        return fail(f"refused: tag {version} already exists — nothing was changed")
    config = Path(".xp/config.yml")
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
