"""A work.md record's Files line must survive decoration, like a card's.

close/sprint_bundle.py `_declared_files` splits on commas with no `_bare()` and
no plausibility check, so it carries BOTH #45's decoration defect and #68's
comma-split defect. Fixed for CARDS by v0.21.4; this is the second, unfixed
implementation of the same rule.

CONSTRUCTS the record rather than grepping (constraint 11). Reds while a
decorated or comma-annotated record path is dropped.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, "plugins/xp-plugin/scripts")
SRC = Path("plugins/xp-plugin/scripts/close/sprint_bundle.py").resolve()
spec = importlib.util.spec_from_file_location("xp_sprint_bundle", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
_declared_files = mod._declared_files

RECORD = "Files: a.py, infra/compose.yml (compose, not the chart), `b.py`\n"
got = _declared_files(RECORD)
missing = [p for p in ("infra/compose.yml", "b.py") if p not in got]
if missing:
    print(f"RED: record Files line dropped {missing}; got {sorted(got)}")
    raise SystemExit(1)
print("GREEN: decorated record paths survive")
