#!/usr/bin/env python3
"""A card amended after its plan review must not reach an executor on that stale plan.

`amend` rewrites only the card credential, and resume re-stages the planner and
plan review only when the review BLOCKED — so after an amendment a fresh executor
gets the new card beside a plan reviewed against the old one. Field-measured on
free-2026-09-11-diff-reference: one executor launch spent stopping on exactly that.
CONSTRUCTED: spawn a multi-file story through a clean plan review and a blocking
diff review, amend an AC, resume. Reds when the resumed executor launches before
any plan review whose prompt carries the amended AC. A CONTROL in the same run
resumes without amending and must launch an executor, so a fixture that stops
launching anything cannot green this vacuously. Run from the repo root.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
    os.environ.pop(var, None)
sys.path.insert(0, "tests")
sys.path.insert(0, "plugins/xp-plugin/scripts")
sys.path.insert(0, "plugins/xp-plugin/scripts/spawn")

AMENDED = "Then AMENDED-AC-SENTINEL"


def resumed_events(root: Path, name: str, amend: bool) -> tuple[list[dict], str]:
    from spawn_helpers import make_repo, spawn
    from test_spawn_stages import stub_stages

    case = root / name
    case.mkdir()
    repo, env, _g = make_repo(case, files="src/thing.py, src/other.py")
    events = stub_stages(case, blocking_diff=True)
    first = spawn(repo, env, "story-042")
    state = json.loads((case / "data/plans/story-042.handoff.json").read_text())
    stages = state.get("stages", {})
    if state.get("state") != "STOPPED" or stages.get("plan-reviewer") != "ran":
        sys.exit(f"construction broke ({name}): {state}\n{first.stdout}{first.stderr}")
    if amend:
        plan = case / "data/plan.md"
        plan.write_text(plan.read_text().replace("Then Z", AMENDED))
        amended = spawn(repo, env, "amend", "story-042", "--reason", "an AC changed")
        if amended.returncode:
            sys.exit(f"construction broke: amend refused\n{amended.stdout}{amended.stderr}")
    seen = len(events.read_text().splitlines())
    stub_stages(case)
    resumed = spawn(repo, env, "resume", "story-042")
    later = [json.loads(line) for line in events.read_text().splitlines()[seen:]]
    return later, resumed.stdout + resumed.stderr


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    template = root / "templates" / "spawn"
    template.mkdir(parents=True)
    git_env = {"PATH": "/usr/bin:/bin", "HOME": tmp}
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "ada@example.com"],
        ["config", "user.name", "Ada L"],
    ):
        subprocess.run(["git", *args], cwd=template, env=git_env, check=True)
    os.environ["XP_TEST_REPO_TEMPLATES"] = str(root / "templates")

    control, output = resumed_events(root, "control", amend=False)
    if "teammate" not in [e["role"] for e in control]:
        sys.exit(f"construction broke: an unamended resume launched no executor\n{output}")

    later, output = resumed_events(root, "amended", amend=True)
    roles = [e["role"] for e in later]
    launched = roles.index("teammate") if "teammate" in roles else None
    before = later if launched is None else later[:launched]
    reviewed = any(e["role"] == "plan-reviewer" and AMENDED in e["prompt"] for e in before)

stale = launched is not None and not reviewed
print(f"resumed roles after amend: {roles}")
if stale:
    print("  ^ the executor launched on a plan no review has seen against the amended card")
sys.exit(1 if stale else 0)
