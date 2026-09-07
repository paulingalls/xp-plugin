"""Run the sprint-close falsifier batch and attribute failures."""

import shlex
from pathlib import Path

from sprint_bundle import ARCHIVES, COVERED_BY, FALSIFIER, RESOLVES, source_files
from work import append, entries, falsifier_result, neutralize, stamp


def corpus(root: Path) -> list[tuple[str, str, str, str]]:
    records, resolutions, archived = {}, {}, set()
    for eid, text in entries(root):
        head = text.splitlines()[0]
        if (archive := ARCHIVES.search(text)) and (
            head.startswith("## archived ")
            or (head.startswith(("## bug ", "## debt ")) and archive.group(1) == eid)
        ):
            archived.add(archive.group(1))
        if head.startswith("## resolved "):
            ref, m = RESOLVES.search(text), FALSIFIER.search(text)
            if ref and m:
                covered = COVERED_BY.search(text)
                resolutions[ref.group(1)] = (m.group(1), covered.group(1) if covered else "")
        elif head.startswith(("## bug ", "## debt ")) and (m := FALSIFIER.search(text)):
            claim = next((ln for ln in text.splitlines() if ln.startswith("Claim: ")), "")
            covered = COVERED_BY.search(text)
            records[eid] = (
                f"{head[3:]} — {claim[7:97]}",
                m.group(1),
                covered.group(1) if covered else "",
            )
    return [
        (eid, head, *resolutions.get(eid, (f, covered)))
        for eid, (head, f, covered) in records.items()
        if eid not in archived
    ]


def batch_refusal(root: Path, grouped: dict[str, list[tuple[str, str, str]]]) -> str:
    red = []
    for falsifier, records in grouped.items():
        result = falsifier_result(falsifier)
        if result.returncode:
            red.append((falsifier, records, result))
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
