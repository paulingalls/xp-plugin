"""A sprint marker write must not clobber a concurrent write it never read.

sprint_close.cmd_start reads the marker, runs the full tier -- measured at ~70
minutes by issue #55 -- then writes the WHOLE in-memory snapshot back. Any
`close.py sprint <id> review` or `salvage` write landing inside that window is
silently lost, along with the round it recorded. Same class as bug 44a7d784
(unlocked plan.md writers), on a different artifact.

CONSTRUCTS the interleaving through the REAL read/write pair (constraint 11), so
a fix that re-reads or merges under a lock greens this rather than leaving it
pinned to today's flaw.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, "plugins/xp-plugin/scripts")

with tempfile.TemporaryDirectory() as tmp:
    os.environ["XP_DATA"] = tmp
    import sprint_close as sc

    path = sc.sprint_marker("21")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reviewed_head": "abc", "rounds": []}))

    _p, state, err = sc.read_sprint_state("21")  # t0: cmd_start reads, tier starts
    assert not err, err

    _p2, other, err2 = sc.read_sprint_state("21")  # t1: a review round lands
    assert not err2, err2
    other["rounds"] = [{"fixed": 3, "blocking": 0}]
    sc.write_sprint_state(path, other)

    state["tier"] = {"verdict": "passed", "ran_by": "start"}  # t2: tier finishes
    sc.write_sprint_state(path, state)

    final = json.loads(path.read_text())
    if not final.get("rounds"):
        print("RED: the concurrent round was clobbered by the tier-holder's stale snapshot")
        print(f"     marker now: {final}")
        raise SystemExit(1)
    print("GREEN: the concurrent round survived the tier-holder's write-back")
