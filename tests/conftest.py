"""Git exports GIT_DIR to hook subprocesses; a worktree exports an ABSOLUTE path, so
any inherited git call would run against the real index with the fixture as its
work tree. Stripped once here so every test's fixture repo is its own."""

import os
import sys
from pathlib import Path

for _var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "XP_AGENT"):
    os.environ.pop(_var, None)

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"))
