"""Run the sprint-close falsifier batch and attribute failures."""

import shlex
from dataclasses import dataclass
from pathlib import Path

from sprint_bundle import ARCHIVES, COVERED_BY, FALSIFIER, RESOLVES, source_files
from work import FalsifierResult, append, entries, falsifier_result, neutralize, stamp

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


def corpus(root: Path) -> list[tuple[str, str, str, str]]:
    return [
        (record.eid, record.head, record.falsifier, record.covered)
        for record in ledger(root)
        if record.state != ARCHIVED
    ]


def execute_batch(grouped: dict[str, list[tuple[str, str, str]]]) -> dict[str, FalsifierResult]:
    results = {}
    for falsifier in grouped:
        result = falsifier_result(falsifier)
        results[falsifier] = result
        print(f"falsifier wall clock: {result.elapsed:.3f}s")
    return results


def batch_refusal(
    root: Path,
    grouped: dict[str, list[tuple[str, str, str]]],
    results: dict[str, FalsifierResult] | None = None,
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
        else:
            commands = [falsifier for falsifier, _records, _result in red]
            combined = (
                commands[0]
                if len(commands) == 1
                else "status=0; "
                + "; ".join(
                    f"/bin/sh -c {shlex.quote(command)} || status=1" for command in commands
                )
                + '; exit "$status"'
            )
            append(
                root,
                f"## bug {stamp()}\nClaim: batch falsifier RED for source records "
                f"{', '.join(refs)}; debt/archive red means the latent problem materialised.\n"
                f"{neutralize(evidence)}\nFalsifier: `{combined}`\n"
                f"Files: {', '.join(files)}\n\n",
            )
            decision = "Filed as one bug."
    return f"refused: {evidence}\n{decision} Fix it, then run start again"


def resolved_offers(
    records: list[LedgerRecord], results: dict[str, FalsifierResult], limit: int = 5
) -> str:
    candidates = [record for record in records if record.state == RESOLVED]
    if not candidates:
        return "0 resolved records to consider archiving."
    measured = {record.falsifier for record in candidates if record.falsifier in results}
    total = sum(results[command].elapsed for command in measured)
    ranked = sorted(
        candidates,
        key=lambda record: (
            -(results[record.falsifier].elapsed if record.falsifier in results else 0.0),
            record.eid,
        ),
    )
    lines = [
        f"{len(candidates)} resolved records to consider archiving;"
        f" total distinct measured cost: {total:.3f}s"
    ]
    for record in ranked[:limit]:
        cost = (
            f"{results[record.falsifier].elapsed:.3f}s this close"
            if record.falsifier in results
            else "deferred; standalone duration not measured"
        )
        lines.append(
            f"  {record.eid} — {cost}; archiving forfeits its replacement"
            " falsifier's recurring guarantee"
        )
    if len(candidates) > limit:
        lines.append(f"  ... {len(candidates) - limit} more")
    return "\n".join(lines)
