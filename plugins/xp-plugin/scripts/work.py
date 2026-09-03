#!/usr/bin/env python3
"""Write work.md lifecycle records and resolve the installed plugin root (`env`).
Bug/debt falsifier polarity is checked when each record is created.
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


STRUCTURAL = re.compile(
    r"^(## |# Record |Claim:|Falsifier:|Covered by:|Resolves:|Archives:|"
    r"Id:|Disposition:|Files:|Story:)",
    re.M,
)


def neutralize(text: str) -> str:
    """Prevent free text from minting grammar fields that silence a falsifier.
    Canonicalize every splitlines break before the re.M field scan.
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
    """The clone's roadmap: shared by its every worktree, by nothing outside."""
    return data_root() / "plan.md"


def missing_plan_refusal() -> str:
    return f"no plan at {plan_path()} — is this an xp-managed repo?"


def edit_plan(mutate) -> bool:
    """Read-modify-write inside a sibling lock; True when changed.

    Temp+rename preserves the previous unversioned plan after interruption. The
    sibling lock survives that inode swap. The lead's editor does not take it.
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
    """A YAML comment opens only at line start or after whitespace."""
    return re.sub(r"(?:^|(?<=\s))#.*", "", line)


def config_block_value(
    block: str, key: str | None = None, missing: str = ""
) -> str | dict[str, str]:
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return {} if key is None else missing
    values = {}
    inside = False
    for raw in cfg.read_text(errors="replace").splitlines():
        line = strip_comment(raw)
        if line.rstrip() == f"{block}:":
            inside = True
        elif inside and line.strip() and not line[:1].isspace():
            inside = False
        elif inside and ":" in line:
            name, value = line.strip().split(":", 1)
            values[name] = value.strip()
    return values if key is None else values.get(key, missing)


def card_title(card: str) -> str:
    """The story title from a card header, or "" when it carries no em-dash."""
    header = card.splitlines()[0]
    return header.split("— ", 1)[1].split(" [")[0].strip() if "— " in header else ""


def card_lines(card: str) -> list[str]:
    """The card lines that its credential hashes and drift refusal diffs."""
    lines = [ln.rstrip() for ln in card.splitlines()]
    head = lines[0]
    if head.endswith("]"):
        lines[0] = head[: head.rindex("[")].rstrip()
    while lines and not lines[-1]:
        lines.pop()
    return lines


def card_digest(card: str) -> str:
    return hashlib.sha256("\n".join(card_lines(card)).encode()).hexdigest()[:16]


def flip_status(text: str, heading: str, frm: str, to: str) -> str:
    exact = heading.startswith("## ")  # a milestone heading is whole; a card's is a prefix
    out = []
    for ln in text.splitlines(keepends=True):
        head, sep, tail = ln.rstrip().rpartition(f"[{frm}]")
        if sep and not tail and (head == heading if exact else ln.startswith(heading)):
            ln = f"{head}[{to}]" + ln[len(ln.rstrip()) :]
        out.append(ln)
    return "".join(out)


def flip_card(story_id: str, frm: str, to: str) -> bool:
    """Flip one card's status in the clone's plan, under the lock; True when it
    moved. Locked because a sibling lane may be flipping its own card right now."""
    return edit_plan(lambda text: flip_status(text, f"#### {story_id} ", frm, to))


def ready_marker_path(story_id: str) -> Path:
    """Story-scoped. No mkdir: a refused mint writes nothing."""
    return data_root() / "markers" / f"{story_id}.ready.json"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:20].strip("-")


def user_ns() -> str:
    """The slugified git identity used as the branch namespace."""
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
    """A compacted record's stored id, else one derived from the full record."""
    if explicit := re.search(r"^Id: ([0-9a-f]{8})$", text, re.M):
        return explicit.group(1)
    return hashlib.sha256(text.strip().encode()).hexdigest()[:8]


def record_summary(text: str) -> tuple[str, str]:
    """Return heading and body line, excluding the optional `Story:` provenance."""
    kept = [ln for ln in text.splitlines() if not ln.startswith("Story: ")]
    return (kept[0] if kept else ""), (kept[1] if len(kept) > 1 else "")


def entries(root: Path) -> list[tuple[str, str]]:
    """(id, text) per record, in file order."""
    # Reporters lose one undecodable byte, never the whole recovery block.
    path = root / "work.md"
    text = path.read_text(errors="replace") if path.exists() else ""
    blocks = re.split(r"^(?=## )", text, flags=re.M)
    return [(entry_id(b), b) for b in blocks if b.strip()]


def falsifier_is_green(command: str) -> bool:
    return subprocess.run(command, shell=True, capture_output=True).returncode == 0


def checked_coverage(args: argparse.Namespace) -> str | None:
    tier = args.covered_by
    if not tier:
        return ""
    tiers = config_block_value("tests")
    if tier in tiers:
        return f"Covered by: {tier}\n"
    names = ", ".join(tiers) or "none"
    print(f"refused: --covered-by {tier!r}; configured tiers: {names}", file=sys.stderr)
    return None


def entry(kind: str, args: argparse.Namespace, coverage: str) -> str:
    return (
        f"## {kind} {stamp()}\n"
        f"Claim: {neutralize(args.claim)}\n"
        f"Falsifier: `{neutralize(args.falsifier)}`\n"
        f"{coverage}"
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


def _archived(root: Path, ref: str) -> bool:
    field = f"Archives: {ref}"
    return any(
        field in text.splitlines() and (text.startswith("## archived ") or eid == ref)
        for eid, text in entries(root)
    )


def resolve(root: Path, args: argparse.Namespace) -> int:
    """Resolve a record by SUBSTITUTING a falsifier, never by deleting one.

    Marking a record done is an unchecked assertion, and one command would
    silence a live bug forever. The replacement must be green now and the batch
    runs it, so a wrong resolution reds later and the record reopens.
    """
    if (coverage := checked_coverage(args)) is None:
        return 2
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
    if _archived(root, args.ref):
        print(
            f"refused: {args.ref} is archived — it has left the falsifier batch;"
            " choose an open bug or debt to resolve.",
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
            f"## resolved {stamp()}\nResolves: {args.ref}\nFalsifier: `{args.falsifier}`\n"
            f"{coverage}\n",
        )
    )
    return 0


def archive(root: Path, args: argparse.Namespace) -> int:
    """Record a disposition; `compact` later moves its record's durable prose."""
    if (kind := _kind_of(root, args.ref)) is None:
        return 2
    if kind not in ("debt", "note"):
        print(
            f"refused: {args.ref} is a {kind} — only a debt or a note is archivable."
            " Archiving a bug hides its red falsifier: fix it, then resolve it. A"
            " resolved or archived record is already disposed of; choose an open one.",
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
        p.add_argument("--covered-by", metavar="TIER", help="a configured tier that runs it")
    sub.add_parser("note").add_argument("text")
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("env", help="print the installed plugin root recorded in the data root")
    a = sub.add_parser("archive")
    a.add_argument("--ref", required=True, help="record id from `list`")
    a.add_argument("--disposition", required=True, help="why: promoted, superseded, dropped")
    r = sub.add_parser("resolve")
    r.add_argument("--ref", required=True, help="record id from `list`")
    r.add_argument("--falsifier", required=True, help="replacement; must be GREEN now")
    r.add_argument("--covered-by", metavar="TIER", help="a configured tier that runs it")
    args = parser.parse_args()

    if args.kind == "env":
        print(plugin_root())
        return 0
    root = data_root()
    if args.kind == "compact":
        from work_compact import compact

        return compact(root, entry_id, record_summary)
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

    if (coverage := checked_coverage(args)) is None:
        return 2
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
    print(append(root, entry(args.kind, args, coverage)))
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
