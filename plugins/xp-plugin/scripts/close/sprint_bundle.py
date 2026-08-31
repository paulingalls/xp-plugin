import re
from pathlib import Path

from close import _read, git
from work import data_root, entries, work_entries_since

FALSIFIER = re.compile(r"^Falsifier: `(.+)`$", re.M)
COVERED_BY = re.compile(r"^Covered by: (.+)$", re.M)
RESOLVES = re.compile(r"^Resolves: (\w+)$", re.M)
ARCHIVES = re.compile(r"^Archives: (\w+)$", re.M)
PLUGIN_ROOT = Path(__file__).parent.parent.parent


def _sprint_records(root: Path, since_epoch: int) -> tuple[str, str]:
    """Keep original falsifiers for review while corpus substitutes the batch copy."""
    originals = {e: t for e, t in entries(root) if t.startswith(("## bug ", "## debt "))}
    latest, kept = {}, []
    for block in re.split(r"^(?=## )", work_entries_since(since_epoch), flags=re.M):
        if block.startswith("## archived "):
            continue
        if not block.startswith("## resolved "):
            kept.append(block)
        elif (ref := RESOLVES.search(block)) and (new := FALSIFIER.search(block)):
            latest[ref.group(1)] = (new.group(1), COVERED_BY.search(block))
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


def build(sprint_id, cards, base, report, charter, extra, diff_base="") -> str:
    """Build at launch so the closer sees the fixer's tree."""
    epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    resolutions, work_md = _sprint_records(data_root(), epoch)
    title = "The delta since the last recorded round" if diff_base else "Cumulative sprint diff"
    sections = [
        ("Your charter", charter),
        ("Your report", f"REPORT_PATH: {report}"),
        *extra,
        (f"The stories in sprint {sprint_id}", cards),
        (title, git("diff", f"{diff_base or base}..HEAD").stdout),
        ("Resolutions filed during the sprint", resolutions),
        ("work.md entries filed during the sprint", work_md),
        ("JUDGMENT", _read(str(PLUGIN_ROOT / "JUDGMENT.md"))),
        ("VALUES", _read(str(PLUGIN_ROOT / "VALUES.md"))),
        ("Constraints", _read(".xp/constraints.md")),
        ("System context", _read(".xp/system.md")),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)
