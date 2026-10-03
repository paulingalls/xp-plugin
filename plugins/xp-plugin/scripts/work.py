#!/usr/bin/env python3
"""Write work.md lifecycle records and resolve the installed plugin root (`env`).
Bug/debt falsifier polarity is checked when each record is created.
"""

import argparse
import fcntl
import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# card_title/card_lines are RE-EXPORTED, not used here: 17 modules and tests read them
# from work, and the extraction that moved them must not become their rename.
from card_text import (  # noqa: F401
    card_digest,
    card_lines,
    card_title,
    flip_status,
)
from env import data_root, plugin_root
from plan_writer import CardEditRefusal, apply_card, locked_edit

NOTE_CAP = 4000  # chars; measured: p90 of 392 records is 1,799, so this binds rarely
FALSIFIER_STREAM_CAP = 4000


STRUCTURAL = re.compile(
    r"^(## |# Record |Claim:|Falsifier:|Covered by:|Resolves:|Archives:|"
    r"Id:|Disposition:|Files:|Story:|Keeps:|Too big:|Too important:|Source:|Digest:|Judgment:)",
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
    sibling lock survives that inode swap.
    """
    return locked_edit(plan_path(), data_root() / "locks" / "plan.lock", mutate)


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


@dataclass(frozen=True)
class FalsifierResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed: float


def _bounded_stream(stream: str) -> str:
    if len(stream) <= FALSIFIER_STREAM_CAP:
        return stream
    dropped = len(stream) - FALSIFIER_STREAM_CAP
    return f"[truncated: {dropped} leading chars dropped]\n{stream[-FALSIFIER_STREAM_CAP:]}"


def falsifier_result(command: str) -> FalsifierResult:
    started = time.perf_counter()
    result = subprocess.run(command, shell=True, capture_output=True, text=True, errors="replace")
    elapsed = time.perf_counter() - started
    return FalsifierResult(
        result.returncode, _bounded_stream(result.stdout), _bounded_stream(result.stderr), elapsed
    )


def falsifier_is_green(command: str) -> bool:
    return falsifier_result(command).returncode == 0


def entry(kind: str, args: argparse.Namespace) -> str:
    return (
        f"## {kind} {stamp()}\n"
        f"Claim: {neutralize(args.claim)}\n"
        f"Falsifier: `{neutralize(args.falsifier)}`\n"
        f"{exception_metadata(args)}"
        f"Files: {neutralize(args.files)}\n\n"
    )


def exception_metadata(args: argparse.Namespace) -> str:
    if args.kind != "debt":
        return ""
    return f"Too big: {neutralize(args.too_big)}\nToo important: {neutralize(args.too_important)}\n"


def _single_line(value: str, field: str) -> bool:
    if not value.strip() or len(value.splitlines()) > 1 or "`" in value:
        print(
            f"refused: --{field} must be a non-empty line and must not contain a backtick —"
            " the record format holds it inside backticks on a single line, so"
            " anything else forges the record that follows it.",
            file=sys.stderr,
        )
        return False
    return True


def edit_card_command(args: argparse.Namespace) -> int:
    from close import story_card

    try:
        changed = apply_card(
            args.story_id,
            args.digest,
            args.status,
            args.candidate,
            story_card,
            card_digest,
            edit_plan,
        )
    except CardEditRefusal as error:
        context = args.context
        snapshot = shlex.join(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "card-snapshot",
                args.story_id,
                str(args.candidate.with_suffix(".recovery.md")),
            ]
        )
        repair = (
            f"Repair {args.candidate}; if stale, run `{snapshot}`, retain your edits there,"
            " then retry edit-card with its printed digest and status."
        )
        print(
            f"refused: {context} {args.story_id} cannot apply: {error}. {repair}", file=sys.stderr
        )
        return 2
    print(f"{args.story_id} card {'updated' if changed else 'unchanged'}")
    return 0


def card_snapshot_command(args: argparse.Namespace) -> int:
    from close import story_card

    if not args.candidate.is_absolute():
        print("refused: candidate path must be absolute", file=sys.stderr)
        return 2
    try:
        card, status = story_card(plan_path().read_text(), args.story_id)
        with args.candidate.open("x") as candidate:
            candidate.write(card)
    except FileExistsError:
        print("refused: candidate already exists; choose a new absolute path", file=sys.stderr)
        return 2
    except (OSError, KeyError) as error:
        print(f"refused: cannot snapshot {args.story_id}: {error}", file=sys.stderr)
        return 2
    print(f"digest: {card_digest(card)}\nstatus: {status}\ncandidate: {args.candidate}")
    return 0


def _record(root: Path, ref: str) -> str | None:
    matches = [text for eid, text in entries(root) if eid == ref]
    if len(matches) != 1:
        print(
            f"refused: --ref {ref!r} matches {len(matches)} records — a ref that"
            " names none is a typo, one that names several silences the others.",
            file=sys.stderr,
        )
        return None
    return matches[0]


def debt_reference_error(root: Path, ref: str) -> str:
    matches = [text for eid, text in entries(root) if eid == ref]
    if len(matches) != 1:
        return f"debt ref {ref!r} matches {len(matches)} records — use one exact record id"
    text = matches[0]
    falsifier = re.search(r"^Falsifier: `([^`\n]+)`$", text, re.M)
    if not text.startswith("## debt ") or not falsifier or not falsifier[1].strip():
        return f"debt ref {ref!r} is not a usable debt record — create an exceptional debt"
    if any(not re.search(rf"^{field}: \S.*$", text, re.M) for field in ("Claim", "Files")):
        return f"debt ref {ref!r} lacks claim/files — repair the record"
    disposal = _disposal()
    if disposal._archived(root, ref) or disposal._resolved(root, ref):
        return f"debt ref {ref!r} is disposed — choose an open debt"
    return ""


def _disposal():
    """Imported LATE, not at module load: disposal imports work for its shared
    helpers, so a top-level import here is a cycle."""
    sys.path.insert(0, str(Path(__file__).parent / "work"))
    import disposal

    return disposal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("bug", "debt"):
        p = sub.add_parser(kind)
        p.add_argument("--claim", required=True)
        p.add_argument("--falsifier", required=True, help="shell command; red = exit nonzero")
        p.add_argument("--files", required=True, help="comma-separated paths")
        if kind == "debt":
            p.add_argument(
                "--too-big",
                required=True,
                help="why fixing doubles/crosses the card or needs design",
            )
            p.add_argument(
                "--too-important", required=True, help="silent/corrupting, privacy or user harm"
            )
    k = sub.add_parser("keep", help="restate both exceptional-debt bars for an open record")
    k.add_argument("--ref", required=True)
    k.add_argument("--too-big", required=True)
    k.add_argument("--too-important", required=True)
    j = sub.add_parser(
        "judge", help="record a disposition linked to legacy/unresolved review history"
    )
    j.add_argument("--source", required=True, help="marker path or closes.jsonl:LINE")
    j.add_argument("--report", type=Path, required=True, help="fresh schema-2 disposition report")
    sub.add_parser("note").add_argument("text")
    sub.add_parser("list")
    sub.add_parser("show").add_argument("ref")
    sub.add_parser("compact")
    sub.add_parser("env", help="print the installed plugin root recorded in the data root")
    a = sub.add_parser("archive")
    a.add_argument("--ref", required=True, help="record id from `list`")
    a.add_argument("--disposition", required=True, help="why: promoted, superseded, dropped")
    r = sub.add_parser("resolve")
    r.add_argument("--ref", required=True, help="record id from `list`")
    r.add_argument("--falsifier", required=True, help="replacement; must be GREEN now")
    e = sub.add_parser(
        "edit-card", help="validate and apply one card candidate under the plan lock"
    )
    e.add_argument("story_id")
    e.add_argument("--context", choices=("card-edit", "executor"), default="card-edit")
    e.add_argument("--digest", required=True)
    e.add_argument("--status", required=True)
    e.add_argument("candidate", type=Path)
    s = sub.add_parser("card-snapshot", help="copy one card and print its edit preconditions")
    s.add_argument("story_id")
    s.add_argument("candidate", type=Path)
    args = parser.parse_args()

    if args.kind == "edit-card":
        return edit_card_command(args)
    if args.kind == "card-snapshot":
        return card_snapshot_command(args)
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
    if args.kind == "show":
        if (text := _record(root, args.ref)) is None:
            return 2
        print(text, end="" if text.endswith("\n") else "\n")
        return 0
    if args.kind == "judge":
        return _disposal().judge(root, args)
    if args.kind == "keep":
        return _disposal().keep(root, args)
    if args.kind == "archive":
        return _disposal().archive(root, args)
    if args.kind == "resolve":
        return _disposal().resolve(root, args)
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
    if args.kind == "debt" and not all(
        _single_line(getattr(args, field), field.replace("_", "-"))
        for field in ("too_big", "too_important")
    ):
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
