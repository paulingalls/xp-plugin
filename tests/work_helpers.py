"""One home for work.py's test drivers: test_work.py and work_archive_cases.py
both need them, and a copy in each is the one-rule-two-implementations shape
this repo keeps finding in review.
"""

import subprocess
import sys
from pathlib import Path

WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"


def run(args, data_dir, check=False, story=""):
    env = {"XP_DATA": str(data_dir), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(WORK), *args],
        env=env | {"XP_STORY_ID": story} if story else env,
        capture_output=True,
        text=True,
        check=check,
    )


def resolve_without_tier(ref, falsifier):
    return ["resolve", "--ref", ref, "--falsifier", falsifier, "--covered-by", "none"]


def _append_notes(job):
    data_dir, worker, count = job
    for i in range(count):
        run(["note", f"entry-w{worker}-{i:03d}"], data_dir, check=True)
