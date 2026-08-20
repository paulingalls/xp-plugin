#!/usr/bin/env python3
"""Spawn a teammate on a story: worktree, clean branch, headless launch.

The piece neither harness provides. The teammate profile is INLINED into the
prompt (DESIGN §8) — paths are a fallback, never the mechanism — and the plugin
itself rides in on --plugin-dir, because a worktree `claude -p` session applies
no project-scoped marketplace enablement and would otherwise load no hooks,
agents or skills.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from close import fail, git, integration_target, story_card
from work import chdir_repo_root, data_root, slugify, user_ns

PLUGIN_ROOT = Path(__file__).parent.parent

# Headless denies tool permission requests by default, which yields a teammate
# that writes prose and exits 0. --allowedTools is an ALLOW-list under a full
# bypass and therefore bounds nothing; the teammate is declared UNBOUNDED until
# the story-close smoke measures which of {auto, dontAsk, bypass} is required.
PERMISSION_ARGV = ["--dangerously-skip-permissions"]


def resolve_role(role: str, card: str = "", override: str = "") -> tuple[str, str, str]:
    """(harness, model, effort) — CLI override, then the card, then config roles.

    Its own block-scan rather than close.config_flat, which matches at column 0
    and cannot see `executor:` indented under `roles:`.
    """
    spec = override or _card_executor(card) or _config_role(role)
    parts = [p for p in spec.split("/") if p]
    if len(parts) < 2:
        raise SystemExit(
            fail(f"refused: cannot resolve {role} from {spec!r} — want harness/model[/effort]")
        )
    harness, model, effort = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    if harness != "claude":
        raise SystemExit(fail(f"refused: harness {harness!r} — the codex leg is Sprint 3"))
    return harness, model, effort


def _card_executor(card: str) -> str:
    for ln in card.splitlines():
        if ln.startswith("Executor:"):
            value = ln.removeprefix("Executor:").strip()
            return "" if value == "(default)" else value
    return ""


def _config_role(role: str) -> str:
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    in_roles = False
    for ln in cfg.read_text().splitlines():
        if ln.rstrip() == "roles:":
            in_roles = True
        elif in_roles and ln.strip().startswith(f"{role}:"):
            return ln.split(f"{role}:", 1)[1].split("#")[0].strip()
        elif in_roles and ln and not ln.startswith(" "):
            in_roles = False
    return ""


def card_title(card: str) -> str:
    header = card.splitlines()[0]
    return header.split("— ", 1)[1].split(" [")[0].strip() if "— " in header else ""


def build_prompt(sections: list[tuple[str, str]]) -> str:
    return "\n".join(f"## {title}\n\n{body}\n" for title, body in sections)


def teammate_sections(card: str) -> list[tuple[str, str]]:
    return [
        ("VALUES", _read(PLUGIN_ROOT / "VALUES.md")),
        ("How you work", _read(PLUGIN_ROOT / "TEAMMATE.md")),
        ("Your story card", card),
        ("Constraints", _read(Path(".xp/constraints.md"))),
    ]


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else f"(missing: {path})"


def claude_argv(model: str, effort: str, output_format: str = "json") -> list[str]:
    """The single owner of flag spellings — story-008 launches a reviewer through it."""
    argv = ["claude", "-p", "--plugin-dir", str(PLUGIN_ROOT), *PERMISSION_ARGV]
    argv += ["--output-format", output_format, "--model", model]
    return argv + (["--effort", effort] if effort else [])


def run_agent(argv: list[str], cwd: Path, prompt: str) -> subprocess.CompletedProcess:
    """Prompt on stdin: it keeps ~2k tokens out of argv and out of `ps`."""
    env = os.environ | {"XP_ROLE": "teammate"}
    return subprocess.run(argv, cwd=cwd, input=prompt, text=True, env=env)


def worktree_path(story_id: str) -> Path:
    return data_root() / "worktrees" / story_id


def cmd_spawn(story_id: str, override: str, dry_run: bool) -> int:
    if not Path(".xp/plan.md").exists():
        return fail("refused: no .xp/plan.md here — is this an xp-managed repo?")
    try:
        card, status = story_card(Path(".xp/plan.md").read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if status != "ready":
        return fail(f"refused: {story_id} is [{status}], spawn requires [ready]")
    _harness, model, effort = resolve_role("executor", card, override)
    branch = f"{user_ns()}/{story_id}-{slugify(card_title(card))}"
    tree = worktree_path(story_id)
    argv = claude_argv(model, effort)
    prompt = build_prompt(teammate_sections(card))
    if dry_run:
        print(" ".join(argv))
        print(prompt)
        return 0
    if tree.exists():
        return fail(f"refused: {tree} already exists — {story_id} is already spawned")
    if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).returncode == 0:
        return fail(f"refused: branch {branch} already exists")
    trunk = integration_target()
    tree.parent.mkdir(parents=True, exist_ok=True)
    added = git("worktree", "add", "-b", branch, str(tree), trunk, check=False)
    if added.returncode != 0:
        return fail(f"git worktree add failed: {added.stderr.strip()}")
    print(f"{branch} at {tree} (off {trunk})")
    return run_agent(argv, tree, prompt).returncode


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("story_id")
    p.add_argument("executor", nargs="?", default="", help="harness/model[/effort] override")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return cmd_spawn(a.story_id, a.executor, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
