#!/usr/bin/env python3
"""Every argv the plugin launches, and the PATH check that precedes it.

The one place the two harnesses are allowed to differ: everything downstream —
the completion contract, the tee's log, the report — is shared.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from work import data_root

PLUGIN_ROOT = Path(__file__).parent.parent.parent

# Bypass is REQUIRED, measured: acceptEdits denies `git add`/`git commit`, and an
# --allowedTools list under bypass restricts nothing. The teammate is UNBOUNDED in
# its throwaway worktree; self-closing is close.py's refusal (story-008), not a deny.
PERMISSION_ARGV = ["--dangerously-skip-permissions"]

HARNESS_INSTALL = {
    "claude": "https://claude.com/product/claude-code",
    "codex": "npm install -g @openai/codex",
}


def missing_harness(harness: str) -> str:
    """Text, not an exit code: the spawn turns it into rc 2 before the worktree
    is cut, while review.run must return it as an error tuple — a SystemExit
    there would skip close.py's abort/undo block."""
    if shutil.which(harness):
        return ""
    return (
        f"{harness} is not on PATH — install it ({HARNESS_INSTALL[harness]})"
        " or point the role at a harness that is"
    )


def claude_argv(model: str, effort: str, output_format: str = "json") -> list[str]:
    """`stream-json` REQUIRES `--verbose` — measured at story-017, not assumed."""
    argv = ["claude", "-p", "--plugin-dir", str(PLUGIN_ROOT), *PERMISSION_ARGV]
    argv += ["--output-format", output_format, "--model", model]
    if output_format == "stream-json":
        argv.append("--verbose")
    return argv + (["--effort", effort] if effort else [])


def codex_argv(model: str, effort: str, network: bool = False) -> list[str]:
    """`--disable unified_exec` is non-negotiable (DESIGN §3): without it
    `write_stdin` bypasses every PreToolUse gate. One `--add-dir` here; a LINKED
    worktree gains a second at launch (spawn.common_dir_widening, bug 0c31ac94 —
    note 6193855e's probe was confounded by /tmp being sandbox-writable).
    `-` reads the prompt from stdin, keeping ~2k tokens out of `ps`."""
    argv = ["codex", "exec", "--json", "--disable", "unified_exec"]
    # Our gates ride the ENVIRONMENT (XP_ROLE, GIT_AUTHOR_*), and THREE
    # ~/.codex/config.toml keys can each strip them on their way to the shell.
    # Never ignore_default_excludes: its default drops *KEY*/*SECRET*/*TOKEN*,
    # which no gate of ours is named, and clearing it would hand a sandboxed
    # agent the lead's secrets to buy nothing.
    for pin in ("inherit=all", "exclude=[]", "include_only=[]"):
        argv += ["-c", f"shell_environment_policy.{pin}"]
    argv += ["--sandbox", "workspace-write", "--add-dir", str(data_root())]
    # The EXECUTOR alone: workspace-write blocks DNS (curl EXIT=6, measured
    # 0.149.0) and it is the only leg that nests a headless plan review.
    if network:
        argv += ["-c", "sandbox_workspace_write.network_access=true"]
    argv += ["-m", model]
    if effort:  # never -e: codex has no such flag, and a wrong spelling dies on contact
        argv += ["-c", f"model_reasoning_effort={effort}"]
    return [*argv, "-"]


def agent_argv(
    harness: str, model: str, effort: str, output_format: str, role: str = ""
) -> list[str]:
    """`role`, never `output_format`, picks the sandbox posture — stream-json is
    executor-only by accident, and a format change would move what is permitted."""
    if harness == "codex":
        return codex_argv(model, effort, network=role == "executor")
    return claude_argv(model, effort, output_format)
