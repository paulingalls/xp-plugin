"""Bug ab6a1354: this repo's lead profile against the cap the hook enforces.

Measured on the HOOK'S OWN STDOUT. The first version summed the sections and
missed the `\n\n` joins and the two trust markers — 117 chars short, which is
the wrong side to be wrong on for a bound.
"""

import json
import os
import re
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
# advisory hook: a raise exits 0 with stdout empty, and every check below then
# reads as satisfied or dies on `.index`. Measured in Sprint 8 (AUDIT.md §10).
assert out.strip(), "the hook printed no profile at all — its traceback is on stderr"
assert len(out.encode()) <= OUTPUT_CAP, (
    f"the lead profile assembles {len(out.encode())} bytes against OUTPUT_CAP {OUTPUT_CAP}"
)
constraints = (repo / ".xp" / "constraints.md").read_text()
headings = re.findall(r"^(\d+\. \*\*[^\n]+)", constraints, re.M)
missing = [heading for heading in headings if heading not in out]
assert not missing, f"SessionStart omitted constraints: {missing}"
values = (repo / "plugins/xp-plugin/VALUES.md").read_text()[:60]
process = (repo / "plugins/xp-plugin/PROCESS.md").read_text()[:60]
assert out.index(values) < out.index(process) < out.index("BEGIN project content"), (
    "VALUES sets the stage and PROCESS is the loop; they lead the profile"
)
