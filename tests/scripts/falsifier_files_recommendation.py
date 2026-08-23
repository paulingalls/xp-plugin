"""Falsifier for the Files-as-contract bug: reds while the shipped prose still
treats a card's Files line as a permission list. Measured cost at story-028:
five plan-gate exits, ~500k teammate tokens, of which three stops were mere
Files-completeness — findings the implementation could absorb and report.
Green when TEAMMATE.md carries the starting-map/report-deviations contract and
the plan-reviewer charter no longer names bare files-list omission a catch."""

import sys
from pathlib import Path

ROOT = Path(__file__).parents[2] / "plugins" / "xp-plugin"
teammate = (ROOT / "TEAMMATE.md").read_text()
charter = (ROOT / "agents" / "plan-reviewer.md").read_text()

ok = (
    "starting map" in teammate
    and "report" in teammate.lower()
    and "omits what the plan edits" not in charter
    and "mislead" in charter.lower()
)
if ok:
    sys.exit(0)
print("shipped prose still holds Files as a permission list", file=sys.stderr)
sys.exit(1)
