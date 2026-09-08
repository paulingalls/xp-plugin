"""A locked flip must survive a card refresher applying its stale candidate.

CONSTRUCTS the interleaving rather than grepping for `flock` (constraint 11):
a refresher reads its card at t0, a lifecycle writer flips a DIFFERENT card
under the lock at t1, and the public refresher helper applies at t2. Reds when
that helper writes a stale snapshot instead of re-reading under the lock.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "plugins/xp-plugin/scripts")

PLAN = """# Roadmap

#### story-041 — a card another lane flips   [ready]
Context: x
#### story-045 — the card the refresher is rewriting   [planned]
Context: OLD
"""
HOLDER = """
import pathlib, sys, time
sys.path.insert(0, {scripts!r})
from work import edit_plan, flip_status
acquired, release = map(pathlib.Path, sys.argv[1:])
def mutate(text):
    acquired.write_text("held")
    while not release.exists(): time.sleep(0.01)
    return flip_status(text, "#### story-041 ", "ready", "in-progress")
edit_plan(mutate)
"""


def await_text(path: Path, expected: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if path.exists() and expected in path.read_text():
            return
        time.sleep(0.01)
    raise SystemExit(f"RED: hang guard waiting for {expected!r} in {path}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "locks").mkdir()
    os.environ["XP_DATA"] = str(root)
    import work
    from close import story_card

    plan = work.plan_path()
    plan.write_text(PLAN)

    stale, status = story_card(plan.read_text(), "story-045")  # t0
    candidate = root / "story-045.card"
    candidate.write_text(stale.replace("Context: OLD", "Context: NEW", 1))
    acquired, release = root / "acquired", root / "release"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            HOLDER.format(scripts=str(Path("plugins/xp-plugin/scripts").resolve())),
            acquired,
            release,
        ],
        env=os.environ,
    )
    await_text(acquired, "held")
    helper_log = root / "helper.stderr"
    with open(helper_log, "w") as log:
        applied = subprocess.Popen(
            [
                sys.executable,
                str(Path("plugins/xp-plugin/scripts/work.py").resolve()),
                "edit-card",
                "story-045",
                "--digest",
                work.card_digest(stale),
                "--status",
                status,
                str(candidate),
            ],
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        await_text(helper_log, "held")
        release.write_text("flip")
        assert holder.wait(20) == 0
        _stdout, _ = applied.communicate(timeout=20)
    if applied.returncode:
        print(helper_log.read_text(), end="")
        raise SystemExit(applied.returncode)

    final = plan.read_text()
    if "#### story-041 — a card another lane flips   [in-progress]" not in final:
        print("RED: the locked flip of story-041 was erased by an unlocked plan write")
        print(f"     story-041 now reads: {[ln for ln in final.splitlines() if '041' in ln]}")
        raise SystemExit(1)
    if "Context: NEW" not in final:
        print("RED: the refresher correction was not applied")
        raise SystemExit(1)
    print("GREEN: the locked flip and refresher correction both survived")
