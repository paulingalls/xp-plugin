"""A locked flip must survive a concurrent unlocked whole-file plan write.

CONSTRUCTS the interleaving rather than grepping for `flock` (constraint 11):
a refresher reads the plan at t0, `spawn.py ready` flips a DIFFERENT card under
the lock at t1, and the refresher writes back its stale text at t2. Reds while
any plan writer bypasses work.edit_plan.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "plugins/xp-plugin/scripts")

PLAN = """# Roadmap

#### story-041 — a card another lane flips   [ready]
Context: x
#### story-045 — the card the refresher is rewriting   [planned]
Context: OLD
"""

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "locks").mkdir()
    import os

    os.environ["XP_DATA"] = str(root)
    import work

    plan = work.plan_path()
    plan.write_text(PLAN)

    stale = plan.read_text()  # t0: the refresher reads
    work.flip_card("story-041", "ready", "in-progress")  # t1: locked flip
    # t2: the refresher writes back, the way slate_review.py:314 does
    plan.write_text(stale.replace("Context: OLD", "Context: NEW", 1))

    final = plan.read_text()
    if "#### story-041 — a card another lane flips   [in-progress]" not in final:
        print("RED: the locked flip of story-041 was erased by an unlocked plan write")
        print(f"     story-041 now reads: {[ln for ln in final.splitlines() if '041' in ln]}")
        raise SystemExit(1)
    print("GREEN: the locked flip survived")
