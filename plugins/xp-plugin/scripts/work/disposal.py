"""Record DISPOSAL: which open record may be retired, and by which route."""

import argparse
import sys
from pathlib import Path

from work import (
    _record,
    _single_line,
    append,
    checked_coverage,
    entries,
    falsifier_is_green,
    neutralize,
    stamp,
)


def _kind_of(root: Path, ref: str) -> str | None:
    """The referenced record's kind, or None having printed why not — None, so a
    heading whose kind reads EMPTY still reaches the refusal below that names it."""
    text = _record(root, ref)
    return text.split(" ", 2)[1] if text is not None else None


def _archived(root: Path, ref: str) -> bool:
    field = f"Archives: {ref}"
    return any(
        field in text.splitlines() and (text.startswith("## archived ") or eid == ref)
        for eid, text in entries(root)
    )


def _resolved(root: Path, ref: str) -> bool:
    field = f"Resolves: {ref}"
    return any(
        field in text.splitlines() and (text.startswith("## resolved ") or eid == ref)
        for eid, text in entries(root)
    )


def resolve(root: Path, args: argparse.Namespace) -> int:
    """Resolve a record by SUBSTITUTING a falsifier, never by deleting one.

    Marking a record done is an unchecked assertion, and one command would
    silence a live bug forever. The replacement must be green now and the batch
    runs it, so a wrong resolution reds later and the record reopens.
    """
    if (coverage := checked_coverage(args, required=True)) is None:
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
    if kind == "bug" and _archived(root, args.ref):
        print(
            f"refused: {args.ref} is already archived — choose an undisposed record.",
            file=sys.stderr,
        )
        return 2
    # FILED IN ERROR is a third state, not a shade of `open`. A bug whose subject
    # lives in an unlanded story cannot be fixed from here and cannot be resolved —
    # `resolve` runs the replacement in the LEAD's checkout, where the covering test
    # does not exist yet — so without this arm such a record has no exit and blocks
    # every card in the sprint. The reason is REQUIRED and must outlive the word:
    # this must stay expensive to reach by accident, or it becomes the cheap way to
    # bury a genuinely red falsifier.
    misfiled = args.disposition.strip().lower().startswith("misfiled")
    if kind == "bug" and misfiled and not _resolved(root, args.ref):
        if len(args.disposition.split(":", 1)[-1].split()) < 4:
            print(
                f"refused: archiving {args.ref} as misfiled needs why it was filed in"
                " error, not the word alone — name what is wrong with the RECORD"
                " (its type, its claim, its falsifier), and where the finding now"
                " lives. A bug whose CODE is wrong is fixed and resolved, not"
                " withdrawn.",
                file=sys.stderr,
            )
            return 2
    elif kind not in ("debt", "note") and not (kind == "bug" and _resolved(root, args.ref)):
        print(
            f"refused: {args.ref} is a {kind} — only a debt, a note, an already"
            " RESOLVED bug, or a bug archived `misfiled: <why>` is archivable."
            " Archiving an unresolved bug hides its red falsifier: fix it, then"
            " resolve it, then archive it. A resolved or archived record is already"
            " disposed of; choose an open one.",
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
