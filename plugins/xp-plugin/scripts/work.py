#!/usr/bin/env python3
"""Append bug/debt/note records to work.md (the only writer — see PROCESS.md), and
resolve the installed plugin root for anything that was not spawned from it (`env`).

A bug's falsifier must red (exit nonzero) right now; a debt's must be green.
The check runs at creation because that is the only cheap enforcement point;
semantic review of falsifiers belongs to the story reviewer.
"""

import argparse
import fcntl
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import data_root, plugin_root

NOTE_CAP = 4000  # chars; measured: p90 of 392 records is 1,799, so this binds rarely


STRUCTURAL = re.compile(r"^(## |Claim:|Falsifier:|Resolves:|Archives:|Files:|Story:)", re.M)


def neutralize(text: str) -> str:
    """A record body must not mint a heading OR a field line.

    work.md is a grammar now: the block boundary is the record's id, `## resolved`
    substitutes another record's falsifier, and the batch EXECUTES the first
    `Falsifier:` line in a block. So a field forged through any free-text argument
    silences a live bug with the green check never having run.

    Breaks are CANONICALISED first, because the writer and every reader must mean
    the same thing by "line". re.M anchors on \n alone, while read_text() turns a
    bare CR into one and splitlines() also breaks on VT, FF, NEL and U+2028 — so a
    character invisible here is a line break downstream, and the guard misses it.
    """
    return STRUCTURAL.sub(r" \1", "\n".join(text.splitlines()))


def chdir_repo_root() -> bool:
    """Anchor to the git toplevel so .xp/ reads work from any subdirectory."""

    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    os.chdir(r.stdout.strip())
    return True


def plan_path() -> Path:
    """The clone's execution plan: shared by its every worktree, by nothing outside."""
    return data_root() / "plan.md"


def stale_plan() -> str:
    """The migration sentence, or "" — folded into each tool's EXISTING missing-plan
    refusal rather than added as a guard of its own."""
    if plan_path().exists() or not Path(".xp/plan.md").exists():
        return ""
    return (
        f"the execution plan is per-clone now and lives at {plan_path()}; the"
        " .xp/plan.md beside you is the pre-move copy. Migrate it:\n"
        # mkdir first: nothing creates the state root until a tool writes a marker
        # or a record there, and a repo scaffolded before the move may have written
        # neither — so the bare `mv` fails on the very population this addresses
        f"  mkdir -p {data_root()} && mv .xp/plan.md {plan_path()}"
        " && git rm --cached .xp/plan.md"
    )


def missing_plan_refusal() -> str:
    """What every leg says when this clone has no plan: the migration sentence
    when a pre-move copy sits beside us, else the diagnosis. Five legs carried a
    copy of it and the sixth had already lost the half naming what to check."""
    return stale_plan() or f"no plan at {plan_path()} — is this an xp-managed repo?"


def edit_plan(mutate) -> bool:
    """Read-modify-write the clone's plan under a lock; True when it changed.

    The read is INSIDE the lock: the current writers read-mutate-write unlocked,
    and a read outside means the loser writes a plan that never saw the winner's
    edit. Two lanes flipping two cards is the normal case, not the rare one.

    temp+rename so an interrupted write leaves the PREVIOUS plan whole: the plan is
    not git-versioned (DESIGN §3b cost 1), so a torn one is unrecoverable. Untested
    by design — rename and in-place are indistinguishable to a reader here, so a
    test telling them apart would certify. It forces the lock onto a SIBLING file:
    rename swaps the inode, so flocking plan.md would leave the next writer
    locking a ghost.

    Serialises OUR writers only — the lead's Edit tool takes no lock, so
    lead-vs-lane stays last-writer-wins (DESIGN §3b cost 5).
    """
    path = plan_path()
    lock = data_root() / "locks" / "plan.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        text = path.read_text() if path.exists() else ""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(edited := mutate(text))
        tmp.replace(path)
    return edited != text


def strip_comment(line: str) -> str:
    """A YAML comment opens at a `#` starting the line or after whitespace, never
    one inside a word: cutting at any `#` truncated a tier whose inline env var held
    one to a bare assignment — exits 0, runs no test. Third reader: tier_cmd."""
    return re.sub(r"(?:^|(?<=\s))#.*", "", line)


def config_block_value(block: str, key: str, missing: str = "") -> str:
    """`key:` nested under `block:` in the project config.

    Comments are stripped BEFORE the header compare. Shared by the roles and
    tests lookups so the pair cannot drift: they were separate copies of this
    parser, and only one of them got fixed.
    """
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return missing
    inside = False
    for raw in cfg.read_text(errors="replace").splitlines():
        line = strip_comment(raw)
        if line.rstrip() == f"{block}:":
            inside = True
        elif inside and line.strip().startswith(f"{key}:"):
            return line.split(f"{key}:", 1)[1].strip()
        elif inside and line.strip() and not line.startswith(" "):
            inside = False
    return missing


def card_title(card: str) -> str:
    """The story title from a card header, or "" when it carries no em-dash."""
    header = card.splitlines()[0]
    return header.split("— ", 1)[1].split(" [")[0].strip() if "— " in header else ""


def card_lines(card: str) -> list[str]:
    """The card as the credential sees it: the whole block, minus what moves for
    reasons that are not drift — TestCardDigest holds which, and why.

    What the refusal DIFFS is this same list, so a diff of anything else would
    name lines the digest forgave.
    """
    lines = [ln.rstrip() for ln in card.splitlines()]
    head = lines[0]
    if head.endswith("]"):
        lines[0] = head[: head.rindex("[")].rstrip()
    while lines and not lines[-1]:
        lines.pop()
    return lines


def card_digest(card: str) -> str:
    return hashlib.sha256("\n".join(card_lines(card)).encode()).hexdigest()[:16]


def flip_status(text: str, story_id: str, frm: str, to: str) -> str:
    """Rewrite the card's TRAILING status bracket only.

    A bare str.replace over the heading rewrites a TITLE carrying the same text
    (measured at story-023's own spawn), and here that also breaks the digest
    minted a line earlier — the leg's own edit then reads as the lead's.
    """
    out = []
    for ln in text.splitlines(keepends=True):
        head, sep, tail = ln.rstrip().rpartition(f"[{frm}]")
        if sep and not tail and ln.startswith(f"#### {story_id} "):
            ln = f"{head}[{to}]" + ln[len(ln.rstrip()) :]
        out.append(ln)
    return "".join(out)


def flip_card(story_id: str, frm: str, to: str) -> bool:
    """Flip one card's status in the clone's plan, under the lock; True when it
    moved. Locked because a sibling lane may be flipping its own card right now."""
    return edit_plan(lambda text: flip_status(text, story_id, frm, to))


def ready_marker_path(story_id: str) -> Path:
    """Story-scoped. No mkdir: a refused mint writes nothing."""
    return data_root() / "markers" / f"{story_id}.ready.json"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:20].strip("-")


def user_ns() -> str:
    """The branch-naming namespace: git identity, slugified. The "user" fallback
    is unreachable in any repo that can commit — a default, not a case to guard."""
    for key, take_local_part in (("user.email", True), ("user.name", False)):
        r = subprocess.run(["git", "config", key], capture_output=True, text=True)
        value = r.stdout.strip()
        if take_local_part:
            value = value.split("@")[0]
        if slug := slugify(value):
            return slug
    return "user"


def append(root: Path, block: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    if story_id := os.environ.get("XP_STORY_ID"):
        heading, body = block.split("\n", 1)
        block = f"{heading}\nStory: {neutralize(story_id)}\n{body}"
    with open(root / "work.md", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(block)
    return entry_id(block)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_id(text: str) -> str:
    """A record's name, DERIVED from its text rather than stored in it: the
    heading is an ISO second, and 48 concurrent appends share one."""
    return hashlib.sha256(text.strip().encode()).hexdigest()[:8]


def record_summary(text: str) -> tuple[str, str]:
    """(heading, claim line) — `Story:` is PROVENANCE and never the record's own
    words, so every reader that summarises a record drops it here rather than
    each re-deriving the absent/unreadable distinction and one of them forgetting:
    two implementations, and the stale one shows a stamp where a claim belongs).
    """
    kept = [ln for ln in text.splitlines() if not ln.startswith("Story: ")]
    return (kept[0] if kept else ""), (kept[1] if len(kept) > 1 else "")


def entries(root: Path) -> list[tuple[str, str]]:
    """(id, text) per record, in file order."""
    # errors="replace": every reader of this is a REPORTER — the session banner,
    # the escalation seam — and a byte nobody can decode must cost one mangled
    # character, never the whole report (the hook degrades a raising builder to
    # silence, so a traceback here deletes the recovery block wholesale).
    path = root / "work.md"
    text = path.read_text(errors="replace") if path.exists() else ""
    blocks = re.split(r"^(?=## )", text, flags=re.M)
    return [(entry_id(b), b) for b in blocks if b.strip()]


def falsifier_is_green(command: str) -> bool:
    return subprocess.run(command, shell=True, capture_output=True).returncode == 0


def entry(kind: str, args: argparse.Namespace) -> str:
    return (
        f"## {kind} {stamp()}\n"
        f"Claim: {neutralize(args.claim)}\n"
        f"Falsifier: `{neutralize(args.falsifier)}`\n"
        f"Files: {neutralize(args.files)}\n\n"
    )


def _single_line(value: str, field: str) -> bool:
    if len(value.splitlines()) > 1 or "`" in value:
        print(
            f"refused: --{field} must be one line and must not contain a backtick —"
            " the record format holds it inside backticks on a single line, so"
            " anything else forges the record that follows it.",
            file=sys.stderr,
        )
        return False
    return True


def _kind_of(root: Path, ref: str) -> str | None:
    """The referenced record's kind, or None having printed why not — None, so a
    heading whose kind reads EMPTY still reaches the refusal below that names it."""
    matches = [text for eid, text in entries(root) if eid == ref]
    if len(matches) != 1:
        print(
            f"refused: --ref {ref!r} matches {len(matches)} records — a ref that"
            " names none is a typo, one that names several silences the others.",
            file=sys.stderr,
        )
        return None
    return matches[0].split(" ", 2)[1]


def resolve(root: Path, args: argparse.Namespace) -> int:
    """Resolve a record by SUBSTITUTING a falsifier, never by deleting one.

    Marking a record done is an unchecked assertion, and one command would
    silence a live bug forever. The replacement must be green now and the batch
    runs it, so a wrong resolution reds later and the record reopens.
    """
    if not _single_line(args.falsifier, "falsifier"):
        return 2
    if (kind := _kind_of(root, args.ref)) is None:
        return 2
    if kind not in ("bug", "debt"):
        print(
            f"refused: {args.ref} is a {kind} — only a bug or a debt carries the"
            " falsifier a resolution substitutes for, so resolving anything else"
            " asserts a change no batch will ever honour.",
            file=sys.stderr,
        )
        return 2
    if not falsifier_is_green(args.falsifier):
        print(
            f"refused: the replacement falsifier reds ({args.falsifier!r}) — a"
            " resolution asserts the claim no longer holds, so its falsifier must be"
            " green NOW. If it reds, the record is not resolved.",
            file=sys.stderr,
        )
        return 2
    print(
        append(
            root,
            f"## resolved {stamp()}\nResolves: {args.ref}\nFalsifier: `{args.falsifier}`\n\n",
        )
    )
    return 0


def archive(root: Path, args: argparse.Namespace) -> int:
    """Record a triage DECISION. Without it a decision has nowhere to live, so
    cmd_start re-emits every note ever filed and the pile only grows.

    The block stays in work.md rather than moving to archive.md: sprint_close's
    corpus() keys a debt's falsifier off its own `## debt ` heading, so leaving
    the block where it is keeps archived falsifiers running for zero new lines —
    and archive.md is read with FALSIFIER.finditer over the WHOLE file, so text
    landing there would be executed by the batch.
    """
    if (kind := _kind_of(root, args.ref)) is None:
        return 2
    if kind not in ("debt", "note"):
        print(
            f"refused: {args.ref} is a {kind} — only a debt or a note is archivable."
            " A bug's falsifier reds NOW, so archiving one hides a live defect; a"
            " resolved or archived block is already disposed of.",
            file=sys.stderr,
        )
        return 2
    print(
        append(
            root,
            f"## archived {stamp()}\nArchives: {args.ref}\n{neutralize(args.disposition)}\n\n",
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("bug", "debt"):
        p = sub.add_parser(kind)
        p.add_argument("--claim", required=True)
        p.add_argument("--falsifier", required=True, help="shell command; red = exit nonzero")
        p.add_argument("--files", required=True, help="comma-separated paths")
    sub.add_parser("note").add_argument("text")
    sub.add_parser("list")
    sub.add_parser("env", help="print the installed plugin root recorded in the data root")
    a = sub.add_parser("archive")
    a.add_argument("--ref", required=True, help="record id from `list`")
    a.add_argument("--disposition", required=True, help="why: promoted, superseded, dropped")
    r = sub.add_parser("resolve")
    r.add_argument("--ref", required=True, help="record id from `list`")
    r.add_argument("--falsifier", required=True, help="replacement; must be GREEN now")
    args = parser.parse_args()

    if args.kind == "env":
        print(plugin_root())
        return 0
    root = data_root()
    if args.kind == "list":
        for eid, text in entries(root):
            heading, body = record_summary(text)
            print(f"{eid} {heading[3:]} — {body[:60]}")
        return 0
    if args.kind == "archive":
        return archive(root, args)
    if args.kind == "resolve":
        return resolve(root, args)
    if args.kind == "note":
        text = args.text
        if len(text) > NOTE_CAP:
            dropped = len(text) - NOTE_CAP
            text = f"{text[:NOTE_CAP]} [truncated: {dropped} chars dropped]"
            print(f"note truncated: {dropped} chars over NOTE_CAP={NOTE_CAP}", file=sys.stderr)
        print(append(root, f"## note {stamp()}\n{neutralize(text)}\n\n"))
        return 0

    if not _single_line(args.falsifier, "falsifier"):
        return 2
    green = falsifier_is_green(args.falsifier)  # outside the lock: may be slow
    if args.kind == "bug" and green:
        print(
            f"refused: falsifier is green ({args.falsifier!r} exited 0) — a bug's"
            " falsifier must red now. File as debt if the claim is about the future.",
            file=sys.stderr,
        )
        return 2
    if args.kind == "debt" and not green:
        print(
            f"refused: falsifier already reds ({args.falsifier!r}) — file as bug and fix it now.",
            file=sys.stderr,
        )
        return 2
    print(append(root, entry(args.kind, args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())


def work_entries_since(branch_point_epoch: int) -> str:
    """work.md entries whose header timestamp postdates the branch point."""
    from datetime import datetime, timezone

    path = data_root() / "work.md"
    if not path.exists():
        return ""
    out, keep = [], False
    for ln in path.read_text().splitlines():
        if ln.startswith("## "):
            ts = ln.rsplit(" ", 1)[1]
            try:
                epoch = (
                    datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                keep = epoch >= branch_point_epoch
            except ValueError:
                keep = False
        if keep:
            out.append(ln)
    return "\n".join(out)
