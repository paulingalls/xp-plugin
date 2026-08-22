"""Falsifier: reds while the codex argv omits an --add-dir for the git COMMON
dir. Measured (first live codex review, story-027): a worktree's index lives at
<main>/.git/worktrees/<id>/, outside workspace-write, so the fixing reviewer
cannot commit. The 021 probe that 'falsified' the spike ran its scratch repo
under /tmp — writable by default in the sandbox — a confound, not a fact."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))
from spawn import agent_argv

argv = agent_argv("codex", "m", "medium", "json")
adds = [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"]
if len(adds) >= 2:  # data root AND a git-common-dir slot
    sys.exit(0)
print(f"codex argv carries only {adds} — no git-common-dir add-dir", file=sys.stderr)
sys.exit(1)
