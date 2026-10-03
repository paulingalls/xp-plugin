"""Read-only interrupted review children shared by consumer tests."""

import json
import sys

# The bound is the longest SILENCE, and it starts at launch — so the stub streams
# until it has written its artifacts, which restarts the clock and models the
# field case: a reviewer that was producing output right up to the kill. One
# second still has a 30x margin over the terminal sleep without charging every
# salvage assertion five seconds for the same constructed event.
KILLED = {"XP_AGENT_TIMEOUT": "1"}
FIXED = {
    "actionable": [],
    "fixed": ["tightened the guard"],
    "blocking": [],
    "schema": 2,
    "dropped": [],
    "debt": [],
}
PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+guarded = True
"""
NEW_FILE_PATCH = """diff --git a/src/fixed.py b/src/fixed.py
new file mode 100644
--- /dev/null
+++ b/src/fixed.py
@@ -0,0 +1 @@
+fixed = True
"""


def dying_reviewer(tmp_path, extra="", patch=PATCH):
    """A reviewer that writes its report and patch and then goes SILENT.

    It emits no terminal result, which is what the silence bound reads and what
    the field case looked like: the artifacts on disk, the process killed inside
    whatever it was doing next. A ticker streams while it works, because the
    bound starts at LAUNCH — without one a loaded machine kills the stub
    mid-write and the test measures the fixture. Its own process rather than a
    shell loop: a builtin printf writing to a pipe is block-buffered, so a
    subshell that never exits never flushes a byte of it.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ticker = tmp_path / "ticker.py"
    ticker.write_text(
        "import sys, time\n"
        "while True:\n"
        '    sys.stdout.write(\'{"type": "system"}\\n\')\n'
        "    sys.stdout.flush()\n"
        "    time.sleep(0.2)\n"
    )
    (bin_dir / "claude").write_text(
        "#!/bin/sh\n"
        '[ "$1 $2 $3" = "plugin list --json" ] && echo '
        '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\' && exit 0\n'
        f"{sys.executable} {ticker} &\n"
        "ticker=$!\n"
        f"echo launched >> {tmp_path / 'spawns'}\n"
        "input=$(cat)\n"
        "p=$(printf '%s' \"$input\" | sed -n 's/^REPORT_PATH: //p')\n"
        "q=$(printf '%s' \"$input\" | sed -n 's/^PATCH_PATH: //p')\n"
        f"printf '%s' '{json.dumps(FIXED)}' > \"$p\"\n"
        f"printf '%s' '{patch}' > \"$q\"\n"
        f"{extra}"
        "kill $ticker\n"
        "sleep 30\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir
