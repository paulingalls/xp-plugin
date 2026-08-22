"""Falsifier for the duplicate-story-id bug: reds while story_card accepts a
plan holding two cards with the same id (it returns the first; flip_status
rewrites the last — measured disagreeing on the fresh-repo setup walk)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))
from close import story_card

PLAN = (
    "#### story-001 — a   [ready]\nExecutor: x/y\n\n"
    "#### story-001 — b   [ready]\nExecutor: (default)\n"
)
try:
    story_card(PLAN, "story-001")
except Exception:
    sys.exit(0)
print("duplicate story id accepted silently", file=sys.stderr)
sys.exit(1)
