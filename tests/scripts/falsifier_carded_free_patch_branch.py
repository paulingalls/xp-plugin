#!/usr/bin/env python3
"""A carded free patch must be spawned onto the branch `free start` cut.

`free start` cuts <ns>/free-<date>-<slug> and every free leg keys off that exact
name. `spawn` derives its own from the CARD TITLE and branches from the
integration target, so a carded free patch lands somewhere the free legs refuse —
and the lead's own commits on the free branch are absent from it. Recovering by
reset discards them, silently: the refusal catches the NAME, never the divergence.
Free work goes through spawn by PROCESS (bug 898ad9e1), so a carded free patch is
the normal case.
CONSTRUCTED: both name-builders, on the same slug and the card that free start's
own id implies. No greps.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "close"))
import free  # noqa: E402
import spawn  # noqa: E402

slug = "record-hygiene"
free_branch = free.branch_for(slug)
story_id = free_branch.split("/", 1)[1]
card = f"#### {story_id} — three bugs, and the record stops growing forever   [ready]\n"
spawn_branch = spawn.story_branch(card, story_id)

print(f"free start cuts : {free_branch}")
print(f"spawn cuts      : {spawn_branch}")
if free_branch != spawn_branch:
    print("  the free legs key off the first; the executor's work lands on the second")
sys.exit(1 if free_branch != spawn_branch else 0)
