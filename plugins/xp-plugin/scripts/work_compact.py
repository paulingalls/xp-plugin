"""Archive disposed record prose after preserving the work.md execution surface."""

import fcntl
import os
import re
import sys
from pathlib import Path


def compact(root: Path, entry_id, record_summary) -> int:
    path = root / "work.md"
    if not path.exists():
        print(0)
        return 0
    with path.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        blocks = [b for b in re.split(r"^(?=## )", handle.read(), flags=re.M) if b.strip()]
        indexed = [(entry_id(block), block) for block in blocks]
        records, actions = dict(indexed), {}
        for aid, block in indexed:
            head = block.splitlines()[0]
            field = "Resolves" if head.startswith("## resolved ") else "Archives"
            if head.startswith(("## resolved ", "## archived ")) and (
                match := re.search(rf"^{field}: (\w+)$", block, re.M)
            ):
                actions.setdefault(match.group(1), []).append((aid, block, field))
        disposed = {ref: value for ref, value in actions.items() if ref in records}
        if not disposed:
            print(0)
            return 0
        removed = {aid for value in disposed.values() for aid, _block, _field in value}
        kept, sections = [], []
        for eid, block in indexed:
            if eid not in disposed:
                if eid not in removed:
                    kept.append(block)
                continue
            decisions = disposed[eid]
            _aid, decision, field = next(
                (item for item in reversed(decisions) if item[2] == "Archives"), decisions[-1]
            )
            heading, body = record_summary(block)
            detail = (
                " ".join(
                    line
                    for line in decision.splitlines()[1:]
                    if line.strip() and not line.startswith(("Story: ", "Archives: "))
                )
                if field == "Archives"
                else "resolved"
            )
            summary = body if body.startswith("Claim: ") else f"Disposition: {detail}"
            lines = [heading, summary, f"Id: {eid}", f"{field}: {eid}"]
            if summary == body:
                lines.append(f"Disposition: {detail}")
            source = decision if field == "Resolves" else block
            if falsifier := re.search(r"^Falsifier: `.+`$", source, re.M):
                lines.append(falsifier.group(0))
            if covered := re.search(r"^Covered by: .+$", source, re.M):
                lines.append(covered.group(0))
            if files := re.search(r"^Files: .*$", block, re.M):
                lines.append(files.group(0))
            kept.append("\n".join(lines) + "\n\n")
            prose = [] if re.search(r"^Id: ", block, re.M) else [f"# Record {eid}\n\n{block}"]
            sections.append((eid, prose + [d[1] for d in decisions]))
        try:
            with (root / "archive.md").open("a+") as archived:
                fcntl.flock(archived, fcntl.LOCK_EX)
                archived.seek(0)
                before = archived.read()
                addition = ""
                for eid, parts in sections:
                    archived_before = f"# Record {eid}\n" in before
                    for part in parts:
                        if part in before or part in addition:
                            continue
                        if archived_before and part.startswith("# Record "):
                            raise OSError(f"archive section {eid} does not match work.md")
                        addition += part
                archived.write(addition)
                archived.flush()
                os.fsync(archived.fileno())
                archived.seek(0)
                if archived.read() != before + addition:
                    raise OSError("archive.md verification failed")
            compacted = "".join(kept)
            handle.seek(0)
            handle.write(compacted)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            print(f"refused: compaction failed: {exc}", file=sys.stderr)
            return 2
    print(len(disposed))
    return 0
