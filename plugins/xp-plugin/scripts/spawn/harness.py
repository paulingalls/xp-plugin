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

# Bypass is REQUIRED for REVIEWERS TOO, re-measured at story-034's close: under
# `--permission-mode acceptEdits` a headless claude denies Bash outright and denies
# the out-of-workspace Write its report and patch need, then exits 0 with nothing on
# disk. An --allowedTools list under bypass restricts nothing. The teammate is
# UNBOUNDED in its throwaway worktree; self-closing is close.py's refusal (story-008).
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


def codex_argv(model: str, effort: str) -> list[str]:
    """unified_exec stays ENABLED (reversed 2026-08-23, Paul; DESIGN §3): it is
    codex's persistent-session exec tool, and without it a teammate's shell call
    cannot outlive codex's per-command bound — which made TEAMMATE.md's mandatory
    plan review unrunnable on the harness that mechanism exists for. It was
    disabled to protect `PreToolUse`; this plugin ships no PreToolUse hook.
    `-` reads the prompt from stdin, keeping ~2k tokens out of `ps`."""
    argv = ["codex", "exec", "--json"]
    # Our gates ride the ENVIRONMENT (XP_ROLE, GIT_AUTHOR_*), and THREE
    # ~/.codex/config.toml keys can each strip them on their way to the shell.
    # Never ignore_default_excludes: its default drops *KEY*/*SECRET*/*TOKEN*,
    # which no gate of ours is named, and clearing it would hand a sandboxed
    # agent the lead's secrets to buy nothing.
    for pin in ("inherit=all", "exclude=[]", "include_only=[]"):
        argv += ["-c", f"shell_environment_policy.{pin}"]
    # EVERY codex role, no exceptions; teammate_tee.sandbox_line prints it. Under
    # workspace-write, docker, loopback TCP and a nested `codex exec` are each
    # denied and this one string lifts all three (measured 0.149.0) — `--add-dir`
    # does not, it grants path writes, not socket-connect capability. Why that is
    # an asymmetry removed rather than a risk class added, and what it costs a
    # consuming project until story-040: DESIGN §3. `--add-dir` is inert here and
    # kept for that story, which restores a confining posture — as is
    # spawn.common_dir_widening.
    argv += ["--sandbox", "danger-full-access", "--add-dir", str(data_root())]
    argv += ["-m", model]
    if effort:  # never -e: codex has no such flag, and a wrong spelling dies on contact
        argv += ["-c", f"model_reasoning_effort={effort}"]
    return [*argv, "-"]


def agent_argv(harness: str, model: str, effort: str, output_format: str) -> list[str]:
    """No `role`: nothing about a launch turns on it any more. It used to pick the
    codex sandbox posture, which is how the REVIEWER came to run with no network
    at all — unprinted, and believed the other way round in writing."""
    if harness == "codex":
        return codex_argv(model, effort)
    return claude_argv(model, effort, output_format)
