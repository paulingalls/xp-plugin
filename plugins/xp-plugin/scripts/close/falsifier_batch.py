"""Run the sprint-close falsifier batch and attribute failures."""

import shlex
from dataclasses import dataclass
from pathlib import Path

from sprint_bundle import ARCHIVES, COVERED_BY, FALSIFIER, RESOLVES, source_files
from work import (
    FalsifierResult,
    append,
    config_block_value,
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
        if record.state != ARCHIVED
    ]


def execute_batch(grouped: dict[str, list[tuple[str, str, str]]]) -> dict[str, FalsifierResult]:
    results = {}
    for falsifier, records in grouped.items():
        result = falsifier_result(falsifier)
        results[falsifier] = result
        sources = ", ".join(eid for eid, _head, _covered in records)
        print(f"falsifier wall clock: {result.elapsed:.3f}s {sources}")
    return results


def validated_coverage(tiers: dict[str, str]) -> tuple[dict[str, list[str]], str]:
    declared = config_block_value("tier_coverage")
    graph = {
        name: [target.strip() for target in targets.split(",") if target.strip()]
        for name, targets in declared.items()
    }
    if not graph:
        return {}, ""
    participants = set(graph)
    participants.update(target for targets in graph.values() for target in targets)
    if absent := sorted(participants - tiers.keys()):
        return {}, f"tier_coverage names absent tier(s): {', '.join(absent)} in .xp/config.yml"
    unavailable = sorted(
        name for name in participants if not tiers[name] or tiers[name] == "EDIT-ME"
    )
    if unavailable:
        return {}, f"tier_coverage names unavailable tier(s): {', '.join(unavailable)}"
    pins = config_block_value("tier_coverage_pins")
    if missing := sorted(participants - pins.keys()):
        return {}, f"tier_coverage_pins missing tier(s): {', '.join(missing)} in .xp/config.yml"
    for name in sorted(participants):
        if pins[name] != tiers[name]:
            return (
                {},
                f"stale tier_coverage_pins for {name} in .xp/config.yml:"
                f" pinned {pins[name]!r}; current {tiers[name]!r}",
            )
    done, active = set(), []

    def visit(name: str) -> str:
        if name in active:
            cycle = [*active[active.index(name) :], name]
            return "tier_coverage cycle in .xp/config.yml: " + " -> ".join(cycle)
        if name in done:
            return ""
        active.append(name)
        for target in graph.get(name, []):
            if error := visit(target):
                return error
        active.pop()
        done.add(name)
        return ""

    for name in graph:
        if error := visit(name):
            return {}, error
    return graph, ""


def tier_covers(
    tagged: str, running: str, tiers: dict[str, str], graph: dict[str, list[str]]
) -> bool:
    if tagged not in tiers or not tiers[tagged] or tiers[tagged] == "EDIT-ME":
        return False
    if tagged == running or tiers[tagged] == tiers.get(running, ""):
        return True
    seen, pending = set(), list(graph.get(tagged, []))
    while pending:
        current = pending.pop()
        if current == running:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(graph.get(current, []))
    return False


def unavailable_coverage(records: list[LedgerRecord], tiers: dict[str, str]) -> list[str]:
    lines = []
    for record in records:
        if record.state == ARCHIVED or not record.covered or record.covered == "none":
            continue
        value = tiers.get(record.covered)
        if record.covered not in tiers:
            reason = "absent"
        elif not value:
            reason = "empty"
        elif value == "EDIT-ME":
            reason = "EDIT-ME"
        else:
            continue
        lines.append(f"coverage unavailable for {record.eid}: tier {record.covered} is {reason}")
    return lines


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
        coverage = (
            "coverage not recorded (legacy)"
            if not record.covered
            else "no tier runs this"
            if record.covered == "none"
            else f"covered by tier {record.covered}"
        )
        lines.append(
            f"  {record.eid} — {cost}; {coverage}; archiving forfeits its replacement"
            " falsifier's recurring guarantee"
        )
    if len(candidates) > limit:
        lines.append(f"  ... {len(candidates) - limit} more")
    return "\n".join(lines)
