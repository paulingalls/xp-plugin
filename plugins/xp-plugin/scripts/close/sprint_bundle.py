import json
import re
from datetime import datetime, timezone
from pathlib import Path

import review_scope
from close import git
from diff_range import render as render_diff_range
from work import _disposal, data_root, entries, entry_id

FALSIFIER = re.compile(r"^Falsifier: `(.+)`$", re.M)
COVERED_BY = re.compile(r"^Covered by: (.+)$", re.M)
RESOLVES = re.compile(r"^Resolves: (\w+)$", re.M)
ARCHIVES = re.compile(r"^Archives: (\w+)$", re.M)


def _declared_files(text: str) -> list[str]:
    line = next(
        (line.removeprefix("Files:") for line in text.splitlines() if line.startswith("Files:")),
        "",
    )
    paths = review_scope.file_entries(line)
    return [] if not paths or "unknown" in paths else paths


def source_files(root: Path, refs: list[str]) -> tuple[list[str], list[str], str]:
    records = dict(entries(root))
    found = {}
    for ref in refs:
        try:
            found[ref] = _declared_files(records.get(ref, ""))
        except ValueError as exc:
            return [], [], f"record {ref} has an invalid Files declaration: {exc}"
    unresolved = [ref for ref in refs if not found[ref]]
    if unresolved:
        archive_path = root / "archive.md"
        try:
            archive = archive_path.read_text(errors="replace") if archive_path.exists() else ""
        except OSError as exc:
            return [], [], f"archive.md is unreadable: {exc}"
        for ref in unresolved:
            section = re.search(
                rf"^# Record {re.escape(ref)}\n(.*?)(?=^# Record |\Z)",
                archive,
                re.M | re.S,
            )
            if section:
                try:
                    found[ref] = _declared_files(section.group(1))
                except ValueError as exc:
                    return [], [], f"record {ref} has an invalid Files declaration: {exc}"
    paths = list(dict.fromkeys(path for ref in refs for path in found[ref]))
    return paths, [ref for ref in refs if not found[ref]], ""


def _sprint_records(root: Path, since_epoch: int) -> tuple[str, str]:
    archive = root / "archive.md"
    archived = [
        b
        for b in re.split(r"^(?=## )", archive.read_text() if archive.exists() else "", flags=re.M)
        if b.startswith("## ")
    ]
    active = entries(root)
    originals = {
        e: t
        for e, t in [*active, *((entry_id(b), b) for b in archived)]
        if t.startswith(("## bug ", "## debt "))
    }
    disposal = _disposal()
    latest, kept = {}, []
    for ref, block in [*((entry_id(b), b) for b in archived), *active]:
        try:
            timestamp = block.splitlines()[0].rsplit(" ", 1)[-1]
            epoch = (
                datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            continue
        if epoch < since_epoch:
            continue
        if (
            block.startswith("## resolved ")
            and (resolved := RESOLVES.search(block))
            and (new := FALSIFIER.search(block))
        ):
            latest[resolved.group(1)] = (new.group(1), COVERED_BY.search(block))
        elif block.startswith(("## bug ", "## debt ", "## note ")) and not (
            disposal._archived(root, ref) or disposal._resolved(root, ref)
        ):
            kept.append(block)
    out = []
    for ref, (new, covered) in latest.items():
        text = originals.get(ref, "")
        claim = next((ln[7:] for ln in text.splitlines() if ln.startswith("Claim: ")), "")
        old = FALSIFIER.search(text)
        out.append(
            f"- {ref}: {claim or '(no record with this id)'}\n  original falsifier:"
            f" `{old.group(1) if old else '(none)'}`\n  replacement: `{new}`"
            + (f"\n  covered by: {covered.group(1)}" if covered else "")
        )
    return "\n".join(out) or "none", "\n".join(kept).strip() or "none"


def delivered_scope(cards: str, root: Path) -> str:
    members = re.findall(r"^#### (\S+) — (.+?)\s+\[(done|retired)\]$", cards, re.M)
    closes, errors = {}, []
    path = root / "closes.jsonl"
    try:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            try:
                record = json.loads(line)
                closes[record["story"]] = record["merge_sha"]
            except (ValueError, KeyError, TypeError):
                errors.append(f"Unreadable close record {path}:{number} — repair the evidence")
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError) as error:
        errors.append(f"Unreadable close history {path}: {error} — repair the evidence")
    return (
        "\n".join(
            [
                *(
                    f"- {story} — {title} — "
                    + (
                        "retired"
                        if status == "retired"
                        else f"delivered at {closes[story]}"
                        if closes.get(story)
                        else "missing close evidence"
                    )
                    for story, title, status in members
                ),
                *errors,
            ]
        )
        or "no terminal members"
    )


def build(
    sprint_id,
    cards,
    base,
    report,
    charter,
    extra,
    authority,
    diff_base="",
    excluded=None,
    trunk_range="",
) -> str:
    """Build at launch so the closer sees the fixer's tree — but the RUBRIC is the
    caller's snapshot, read once before the first launch. Re-read here it would exit
    from a later stage's bundle, past leg()'s error return and the incomplete round
    it writes (stages.check_roles refuses up front for the same reason)."""
    from finding_triage import render_triage

    epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    resolutions, work_md = _sprint_records(data_root(), epoch)
    title = "The delta since the last recorded round" if diff_base else "Cumulative sprint diff"
    sections = [
        ("Your charter", charter),
        ("Your report", f"REPORT_PATH: {report}"),
        *extra,
        (f"The stories in sprint {sprint_id}", cards),
        ("Delivered outcome", delivered_scope(cards, data_root())),
        ("Current unresolved obligations and historical sources", render_triage(data_root())),
        (title, render_diff_range(diff_base or base, "HEAD", excluded, trunk_range)),
        ("Resolutions filed during the sprint", resolutions),
        ("work.md entries filed during the sprint", work_md),
        *authority,
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)
