"""Bug ab6a1354: this repo's lead profile against the cap the hook enforces.

Measured on the HOOK'S OWN STDOUT. The first version summed the sections and
missed the `\n\n` joins and the two trust markers — 117 chars short, which is
the wrong side to be wrong on for a bound.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / "plugins/xp-plugin/scripts"))
from session_start import OUTPUT_CAP  # noqa: E402

out = subprocess.run(
    [sys.executable, str(repo / "plugins/xp-plugin/scripts/session_start.py")],
    input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(repo)}),
    capture_output=True,
    text=True,
    cwd=repo,
    env=dict(os.environ) | {"XP_ROLE": "lead"},
).stdout
assert "teammate session" not in out, "the role gate ate the profile; this asserts nothing"
assert len(out) <= OUTPUT_CAP, (
    f"the lead profile assembles {len(out)} chars against OUTPUT_CAP {OUTPUT_CAP}"
    " — the cut lands inside constraints.md and the tail rules never reach the lead"
)
values = (repo / "plugins/xp-plugin/VALUES.md").read_text()[:60]
process = (repo / "plugins/xp-plugin/PROCESS.md").read_text()[:60]
assert out.index(values) < out.index(process) < out.index("BEGIN project content"), (
    "VALUES sets the stage and PROCESS is the loop; they lead the profile"
)
