#!/usr/bin/env python3
"""Append bug/debt/note records to work.md. The only writer — see PROCESS.md.

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

NOTE_CAP = 2000  # chars; a judgment call, not a derived number


STRUCTURAL = re.compile(r"^(## |Claim:|Falsifier:|Resolves:|Archives:|Files:)", re.M)


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
    import os

    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    os.chdir(r.stdout.strip())
    return True


def data_root() -> Path:
    if env := os.environ.get("XP_DATA"):
        return Path(env)
    proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if proc.returncode != 0:
        print("not inside a git repository and XP_DATA is unset", file=sys.stderr)
        raise SystemExit(2)
    common = proc.stdout.strip()
    project_id = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:12]
    return Path.home() / ".xp" / "data" / project_id


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
        f"  mv .xp/plan.md {plan_path()} && git rm --cached .xp/plan.md"
    )


def edit_plan(mutate) -> None:
    """Read-modify-write the clone's plan under a lock.

    The read is INSIDE the lock: the current writers read-mutate-write unlocked,
    and a read outside means the loser writes a plan that never saw the winner's
    edit. Two lanes flipping two cards is the normal case, not the rare one.

    temp+rename so an interrupted write leaves the PREVIOUS plan whole: the plan is
    no longer git-versioned (DESIGN §3b cost 1), so a torn one is unrecoverable. Defense in
    depth and NOT a tested property — measured, rename and in-place are
    indistinguishable to a reader here, so a test telling them apart would certify
    (note 12d7fcea). It forces the lock onto a SIBLING file: rename swaps the
    inode, so flocking plan.md would leave the next writer locking a ghost.

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
        tmp.write_text(mutate(text))
        tmp.replace(path)


def config_block_value(block: str, key: str) -> str:
    """`key:` nested under `block:` in the project config.

    Comments are stripped BEFORE the header compare. Shared by the roles and
    tests lookups so the pair cannot drift: they were separate copies of this
    parser, and only one of them got fixed.
    """
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    inside = False
    for raw in cfg.read_text(errors="replace").splitlines():
        line = raw.split("#", 1)[0]
        if line.rstrip() == f"{block}:":
            inside = True
        elif inside and line.strip().startswith(f"{key}:"):
            return line.split(f"{key}:", 1)[1].strip()
        elif inside and line.strip() and not line.startswith(" "):
            inside = False
    return ""


def card_title(card: str) -> str:
    """The story title from a card header, or "" when it carries no em-dash."""
    header = card.splitlines()[0]
    return header.split("— ", 1)[1].split(" [")[0].strip() if "— " in header else ""


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:20].strip("-")


def user_ns() -> str:
    """The branch-naming namespace: git identity, slugified.

    Here rather than in spawn.py because this module already owns per-clone
    identity (data_root), and because close.py and spawn.py both import it —
    story-011's `<user>/free-...` branches get it with no new import edge.
    The "user" fallback is unreachable in any repo that can commit; it is a
    default, not a case to guard.
    """
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
    with open(root / "work.md", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(block)
    return entry_id(block)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_id(text: str) -> str:
    """A record's name, DERIVED from its text rather than stored in it.

    The heading is an ISO second and that is not a name: 48 concurrent appends
    produce 48 identical headings. Deriving it means the 53 entries filed before
    ids existed have one too, which an append-only file can never be given by
    backfilling.
    """
    return hashlib.sha256(text.strip().encode()).hexdigest()[:8]


def entries(root: Path) -> list[tuple[str, str]]:
    """(id, text) per record, in file order."""
    text = (root / "work.md").read_text() if (root / "work.md").exists() else ""
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


def resolve(root: Path, args: argparse.Namespace) -> int:
    """Resolve a record by SUBSTITUTING a falsifier, never by deleting one.

    Marking a record done is an unchecked assertion, and one command would
    silence a live bug forever. The replacement must be green now and the batch
    runs it, so a wrong resolution reds later and the record reopens.
    """
    if not _single_line(args.falsifier, "falsifier"):
        return 2
    matches = [(eid, text) for eid, text in entries(root) if eid == args.ref]
    if len(matches) != 1:
        print(
            f"refused: --ref {args.ref!r} matches {len(matches)} records — a ref that"
            " names none is a typo, one that names several silences the others.",
            file=sys.stderr,
        )
        return 2
    kind = matches[0][1].split(" ", 2)[1]
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
    matches = [(eid, text) for eid, text in entries(root) if eid == args.ref]
    if len(matches) != 1:
        print(
            f"refused: --ref {args.ref!r} matches {len(matches)} records — a ref that"
            " names none is a typo, one that names several silences the others.",
            file=sys.stderr,
        )
        return 2
    kind = matches[0][1].split(" ", 2)[1]
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
    a = sub.add_parser("archive")
    a.add_argument("--ref", required=True, help="record id from `list`")
    a.add_argument("--disposition", required=True, help="why: promoted, superseded, dropped")
    r = sub.add_parser("resolve")
    r.add_argument("--ref", required=True, help="record id from `list`")
    r.add_argument("--falsifier", required=True, help="replacement; must be GREEN now")
    args = parser.parse_args()

    root = data_root()
    if args.kind == "list":
        for eid, text in entries(root):
            head = text.splitlines()
            print(f"{eid} {head[0][3:]} — {(head[1] if len(head) > 1 else '')[:60]}")
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
