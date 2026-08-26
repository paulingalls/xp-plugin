#!/usr/bin/env python3
"""A finder's blocking[] over LIST_CAP must reach the verifier intact.

read_report caps the DATA, not the display, and sprint_close builds its candidate
pool from that dict — so findings past the cap are judged by nobody, and the
placeholder string is handed to a verifier as if it were a finding.
CONSTRUCTED: a report with LIST_CAP+5 distinct findings, read through the real
reader. Never greps for the placeholder — that assertion greens the day someone
renames it and says nothing about coverage.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "xp-plugin" / "scripts"))
import review

n = review.LIST_CAP + 5
findings = [f"finding number {i} in some/file.py" for i in range(n)]
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "r.json"
    path.write_text(json.dumps({"fixed": [], "blocking": findings, "noted": []}))
    got, err = review.read_report(path)
    assert not err, err
    reached = got["blocking"]

missing = [f for f in findings if f not in reached]
print(f"{n} findings written, {len(reached)} reached the verifier, {len(missing)} lost")
if missing:
    print(f"  first lost: {missing[0]!r}")
fabricated = [r for r in reached if r not in findings]
if fabricated:
    print(f"  fabricated candidate handed to the verifier: {fabricated[0]!r}")
sys.exit(1 if (missing or fabricated) else 0)
