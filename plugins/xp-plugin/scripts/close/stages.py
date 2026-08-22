"""The sprint review's stages: their angles, their charters, their batch bound.

Extracted from sprint_close.py rather than left inline: that file runs against
the 500-line hard cap (constraints.md #8), and this is the seam — everything
here answers "what does a stage get?", and nothing here knows about a sprint.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from work import config_block_value

ANGLES = Path(__file__).parent.parent / "angles"
DEFAULT_BATCHES = 2
STAGES = ("finder", "verifier", "fixer", "closer")


def angles() -> tuple[list[tuple[str, str]], str]:
    """[(slug, prose)] for every shipped angle, or a refusal. Unreadable refuses
    BEFORE any launch: a finder whose angle never arrived runs generalist, and a
    generalist pass looks exactly like a working one in every artifact kept."""
    found = []
    for path in sorted(ANGLES.glob("*.md")):
        if not (text := path.read_text(errors="replace").strip()):
            return [], f"refused: the angle file {path} is empty — a blind finder needs it"
        found.append((path.stem, text))
    if not found:
        return [], f"refused: no angle files under {ANGLES} — a finder has nothing to carry"
    return found, ""


def charters() -> tuple[dict[str, str], str]:
    """{stage: the shared charter plus its own section}, or a refusal. Hoisted for
    angles()'s reason and one worse: a stage launched without its section is an
    uninstructed agent whose report the pipeline records all the same, and reading
    the CLOSER's section at the closer's launch discovers it missing only after
    every earlier stage has spent and the fixer has committed."""
    import review

    text = review.charter("sprint-reviewer")
    shared, _, rest = text.partition("\n## ")
    found = {}
    for section in rest.split("\n## "):
        if (name := section.split("\n", 1)[0].strip()) in STAGES:
            found[name] = f"{shared.strip()}\n\n## {section.strip()}"
    if missing := [s for s in STAGES if s not in found]:
        return {}, f"refused: agents/sprint-reviewer.md has no `## {missing[0]}` section"
    return found, ""


def batches(items: list, cap: int) -> list[list]:
    """At most `cap` non-empty chunks, whatever the item count. Sprint-003 ran
    one refuter per LOCATION: 22 agents to kill 3 candidates, ~80% of the spend
    for a 12% filter, because locations barely collide and batches do."""
    if not items:
        return []
    size = -(-len(items) // min(cap, len(items)))
    return [items[i : i + size] for i in range(0, len(items), size)]


def batch_cap() -> tuple[int, str]:
    """(verifier agents per round, refusal). CONFIG bounds it, never the
    candidate count — the whole point of batching. A typo refuses rather than
    silently substituting a number the lead believes they set."""
    raw = config_block_value("review", "verify_batches")
    if not raw:
        return DEFAULT_BATCHES, ""
    if not (raw.isdigit() and int(raw) > 0):
        return 0, f"refused: review.verify_batches must be a positive integer, not {raw!r}"
    return int(raw), ""
