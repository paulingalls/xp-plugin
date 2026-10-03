"""Run the sprint-close falsifier batch and attribute failures."""

from dataclasses import dataclass
from pathlib import Path

from sprint_bundle import ARCHIVES, COVERED_BY, FALSIFIER, RESOLVES, source_files
from work import (
    FalsifierResult,
    append,
    entries,
    falsifier_result,
    neutralize,
    stamp,
)

OPEN = "OPEN"
RESOLVED = "RESOLVED"
ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class LedgerRecord:
    eid: str
    head: str
    falsifier: str
    covered: str
    state: str


def ledger(root: Path, source: list[tuple[str, str]] | None = None) -> list[LedgerRecord]:
    records, resolutions, archived = {}, {}, set()
    for eid, text in entries(root) if source is None else source:
        head = text.splitlines()[0]
        archive = ARCHIVES.search(text)
        if archive and (
            head.startswith("## archived ")
            or (head.startswith(("## bug ", "## debt ")) and archive.group(1) == eid)
        ):
            archived.add(archive.group(1))
        if head.startswith("## resolved "):
            ref, match = RESOLVES.search(text), FALSIFIER.search(text)
            if ref and match:
                covered = COVERED_BY.search(text)
                resolutions[ref.group(1)] = (match.group(1), covered.group(1) if covered else "")
        elif head.startswith(("## bug ", "## debt ")) and (match := FALSIFIER.search(text)):
            claim = next((line for line in text.splitlines() if line.startswith("Claim: ")), "")
            covered = COVERED_BY.search(text)
            resolved = RESOLVES.search(text)
            records[eid] = (
                f"{head[3:]} — {claim[7:97]}",
                match.group(1),
                covered.group(1) if covered else "",
                bool(resolved and resolved.group(1) == eid),
            )
    out = []
    for eid, (head, falsifier, covered, compacted_resolution) in records.items():
        disposed = eid in resolutions or compacted_resolution
        state = ARCHIVED if eid in archived else RESOLVED if disposed else OPEN
        command, coverage = resolutions.get(eid, (falsifier, covered))
        out.append(LedgerRecord(eid, head, command, coverage, state))
    return out


def corpus(
    root: Path, records: list[LedgerRecord] | None = None
) -> list[tuple[str, str, str, str]]:
    return [
        (record.eid, record.head, record.falsifier, record.covered)
        for record in (ledger(root) if records is None else records)
        if record.state == OPEN
    ]


def execute_batch(grouped: dict[str, list[tuple[str, str, str]]]) -> dict[str, FalsifierResult]:
    results = {}
    for falsifier, records in grouped.items():
        result = falsifier_result(falsifier)
        results[falsifier] = result
        sources = ", ".join(eid for eid, _head, _covered in records)
        print(f"falsifier wall clock: {result.elapsed:.3f}s {sources}")
    return results


def grouped_batch(root: Path) -> tuple[dict, list]:
    source = entries(root)
    grouped = {}
    for eid, head, falsifier, covered in corpus(root, ledger(root, source)):
        grouped.setdefault(falsifier, []).append((eid, head, covered))
    return grouped, source


def triage_notes(source: list[tuple[str, str]]) -> list[str]:
    notes, archived = {}, set()
    for eid, text in source:
        head, lines = text.splitlines()[0], text.splitlines()
        archive = ARCHIVES.search(text)
        if head.startswith("## archived ") and archive:
            archived.add(archive.group(1))
        elif head.startswith("## note "):
            notes[eid] = text
            if archive and archive.group(1) == eid and f"Id: {eid}" in lines:
                archived.add(eid)
    return [text for eid, text in notes.items() if eid not in archived]


def batch_refusal(
    root: Path,
    grouped: dict[str, list[tuple[str, str, str]]],
    results: dict[str, FalsifierResult] | None = None,
    retry: str = "start",
) -> str:
    results = execute_batch(grouped) if results is None else results
    red = [
        (falsifier, records, results[falsifier])
        for falsifier, records in grouped.items()
        if results[falsifier].returncode
    ]
    if not red:
        return ""
    lines = ["batch falsifier RED:"]
    refs = []
    for falsifier, records, result in red:
        lines.append(f"command: {falsifier}")
        for eid, head, _covered in records:
            refs.append(eid)
            lines.append(f"source {eid} ({head})")
        lines.extend(
            (f"stdout:\n{result.stdout or '(empty)'}", f"stderr:\n{result.stderr or '(empty)'}")
        )
    evidence = "\n".join(lines)
    # 126/127 is the shell's own "not executable"/"not found": nothing was measured
    unrun = ", ".join(
        f"`{falsifier}` (exit {result.returncode})"
        for falsifier, _records, result in red
        if result.returncode in (126, 127)
    )
    known = any(head.startswith("bug ") for _f, records, _r in red for _e, head, _c in records)
    if known:
        decision = "No bug filed because an open source bug already filed this batch."
    else:
        files, missing, archive_error = source_files(root, refs)
        if archive_error:
            decision = f"No bug filed because {archive_error}."
        elif missing:
            malformed = "; ".join(f"{ref} has no usable Files declaration" for ref in missing)
            decision = f"No bug filed because {malformed}."
        elif unrun:
            decision = f"No bug filed: {unrun} could not run."
        elif len(red) != 1:
            decision = "No bug filed for several red commands."
        else:
            append(
                root,
                f"## bug {stamp()}\nClaim: batch falsifier RED for source records "
                f"{', '.join(refs)}; debt/archive red means the latent problem materialised.\n"
                f"{neutralize(evidence)}\nFalsifier: `{red[0][0]}`\n"
                f"Files: {', '.join(files)}\n\n",
            )
            decision = "Filed as one bug."
    if unrun or len(red) != 1:
        decision += " Triage the commands, then use `work.py bug` if a product bug is confirmed."
    return f"refused: {evidence}\n{decision} Fix it, then run {retry} again"
