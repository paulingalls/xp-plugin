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
CODEX_SANDBOXES = ("workspace-write", "danger-full-access")


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


def resolve_codex_sandbox(harness: str, configured: str) -> tuple[str, str]:
    if harness != "codex":
        return "", ""
    posture = configured or "danger-full-access"
    if posture in CODEX_SANDBOXES:
        return posture, ""
    if posture == "read-only":
        return "", (
            "codex_sandbox read-only is refused — every role this plugin launches must"
            " write its deliverable; use workspace-write or danger-full-access"
        )
    return "", (
        f"codex_sandbox {posture!r} is unrecognised — accepted values are"
        f" {CODEX_SANDBOXES[0]} and {CODEX_SANDBOXES[1]}"
    )


def codex_argv(model: str, effort: str, sandbox: str) -> list[str]:
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
    # EVERY codex role takes the caller-resolved posture; teammate_tee prints it
    # back off this argv. Under workspace-write ALL outbound network is denied —
    # DNS, loopback, the docker socket (re-measured 0.149.0 with a control,
    # 2026-08-25); `--add-dir` grants path writes, never socket-connect. The one
    # copy of the default lives in resolve_codex_sandbox above (DESIGN §3).
    argv += ["--sandbox", sandbox, "--add-dir", str(data_root())]
    argv += ["-m", model]
    if effort:  # never -e: codex has no such flag, and a wrong spelling dies on contact
        argv += ["-c", f"model_reasoning_effort={effort}"]
    return [*argv, "-"]


def agent_argv(
    harness: str, model: str, effort: str, output_format: str, sandbox: str
) -> list[str]:
    """No `role`: nothing about a launch turns on it any more. It used to pick the
    codex sandbox posture, which is how the REVIEWER came to run with no network
    at all — unprinted, and believed the other way round in writing."""
    if harness == "codex":
        return codex_argv(model, effort, sandbox)
    return claude_argv(model, effort, output_format)
