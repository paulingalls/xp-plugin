#!/usr/bin/env python3
"""A plan review that PRODUCED FINDINGS must not be reported as one nobody signed.

plan_review_notice tests only `marker.exists()`, so a review that ran, wrote its
findings and then lost its marker cleanup reads identically to one that never
started. Field-measured (Legacy, 0.7.0): a sound 6.2KB review discarded and the
story re-spawned. Absent, unreadable and UNSIGNED are three states; the notice
enumerates two.
CONSTRUCTED: both artifacts on disk at once — the stale marker AND the findings
the review actually wrote. Never greps the notice text.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "xp-plugin" / "scripts"))

with tempfile.TemporaryDirectory() as tmp:
    os.environ["XP_DATA"] = tmp
    import review

    root = Path(tmp)
    (root / "markers").mkdir(parents=True)
    (root / "plans").mkdir(parents=True)
    (root / "markers" / "story-042.plan-review-incomplete").write_text("pid 1234")
    findings = {"status": "edited", "reasons": ["a real reason the reviewer wrote"]}
    (root / "plans" / "story-042.md").write_text(json.dumps(findings))

    notice = review.plan_review_notice("story-042")

signed_off_claim = "no reviewer signed off" in notice
print(f"findings on disk: yes | notice returned: {bool(notice)}")
print(f"  notice: {notice[:120]!r}")
if signed_off_claim:
    print("  ^ claims nobody signed off while the reviewer's own findings sit beside the marker")
sys.exit(1 if signed_off_claim else 0)
