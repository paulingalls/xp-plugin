import sys
from pathlib import Path

sys.path.insert(0, "plugins/xp-plugin/scripts")
import session_start as s

r = Path.cwd()
total = sum(
    len(x)
    for x in [
        s.banner(r),
        s.config_age(r),
        s.read(s.PLUGIN_ROOT / "VALUES.md"),
        s.read(s.PLUGIN_ROOT / "PROCESS.md"),
        s.recovery_block(),
        s.read(r / ".xp" / "constraints.md"),
        s.digest_with_staleness(),
    ]
)
assert total <= s.OUTPUT_CAP, (
    f"the lead profile assembles {total} chars against OUTPUT_CAP {s.OUTPUT_CAP}"
    " — the cut lands inside constraints.md and the tail rules never reach the lead"
)
