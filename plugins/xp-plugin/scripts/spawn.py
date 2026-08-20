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
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from close import fail, git, integration_target, story_card
from work import chdir_repo_root, data_root, slugify, user_ns

PLUGIN_ROOT = Path(__file__).parent.parent

# MEASURED at story-007 close, not assumed (every figure from a live `claude -p`):
#   auto / dontAsk  -> Bash ok, Write DENIED        -> teammate cannot write code
#   acceptEdits     -> Write ok, `git add`/`git commit` DENIED -> cannot commit
#   bypass          -> all ok
# A story loop is edit -> test -> COMMIT, so bypass is required; the weaker modes
# yield a teammate that works and then silently loses the work.
#
# No --allowedTools: measured, an allow-list under bypass restricts nothing
# (allowedTools=Bash still let Read through), and shipping it would certify a
# bound that does not exist. A DENY-list does bound under bypass (disallowedTools
# =Read denied Read while Bash passed) — recorded for when we have a defect that
# earns one. Not used for /story-close self-closing: Bash can invoke close.py
# directly, so a tool-level deny there would be theater. That hard property is
# close.py refusing XP_ROLE=teammate (story-008).
#
# THE TEAMMATE IS THEREFORE UNBOUNDED inside its throwaway worktree. Declared,
# not believed.
PERMISSION_ARGV = ["--dangerously-skip-permissions"]

# Tokens (chars//4). The cap covers prose WE ship — VALUES, TEAMMATE.md, the
# seed constraints file and always-on component metadata — because ownership is
# about who authored the prose, not which directory it lands in after install.
# Deliberately NOT a cap on the composed total: CLAUDE.md, the project's grown
# constraints.md and its cards are the consuming project's, and a plugin gate
# over prose we do not own certifies nothing (DESIGN §8 diff proposed at close).
PLUGIN_SHIPPED_CAP = 1200
COMPONENT_METADATA_CAP = 300  # so a new skill reds the component line, not TEAMMATE.md
TOTAL_TARGET = 2500  # composed profile: reported, never enforced


def component_metadata_chars() -> int:
    """Frontmatter of every skill and agent — always-on in any session that
    loads the plugin, so it taxes every spawn forever. Bodies are excluded:
    progressive disclosure loads a SKILL.md body only when invoked."""
    total = 0
    for path in sorted(PLUGIN_ROOT.glob("skills/*/SKILL.md")) + sorted(
        PLUGIN_ROOT.glob("agents/*.md")
    ):
        parts = path.read_text().split("---", 2)
        if len(parts) > 2:
            total += len(parts[1])
    return total


def plugin_shipped_chars() -> int:
    shipped = [
        PLUGIN_ROOT / "VALUES.md",
        PLUGIN_ROOT / "TEAMMATE.md",
        PLUGIN_ROOT / "templates" / "constraints.md",
    ]
    return sum(len(_read(p)) for p in shipped) + component_metadata_chars()


def profile_report(card: str, prompt: str) -> tuple[str, str]:
    """(breakdown for the lead, warning or "") — routed to the LEAD, never into
    the teammate's prompt where it is noise and unactionable. An always-identical
    table is wallpaper (constraints.md #3), so the warning is what carries news."""
    project = {
        "the story card": len(card),
        "constraints.md": len(_read(Path(".xp/constraints.md"))),
        "CLAUDE.md": len(_read(Path("CLAUDE.md"))),
    }
    ours = len(prompt) - project["the story card"] - project["constraints.md"]
    total = (len(prompt) + project["CLAUDE.md"] + component_metadata_chars()) // 4
    shares = " · ".join(f"{k} {v // 4}" for k, v in project.items())
    line = (
        f"profile: total {total} tokens · plugin-shipped {(ours + component_metadata_chars()) // 4}"
        f" · {shares}"
    )
    if total <= TOTAL_TARGET:
        return line, ""
    largest = max(project, key=lambda k: project[k])
    return line, (
        f"note: teammate profile is {total} tokens, over the {TOTAL_TARGET} target."
        f" Largest project-owned contributor is {largest} ({project[largest] // 4} tokens)"
        " — yours to retire, not the plugin's."
    )


def bootstrap_command(system_md: str) -> str:
    """The whole value must be ONE backticked command, or nothing runs.

    A substring match would execute the path in a line like
    "Worktree bootstrap: none needed - see [a backticked path]". Deterministic
    by construction: no judging prose (constraints.md #7).
    """
    for ln in system_md.splitlines():
        if "Worktree bootstrap:" in ln:
            value = ln.split("Worktree bootstrap:", 1)[1].strip().rstrip(".")
            m = re.fullmatch(r"`(.+)`", value)
            return m.group(1) if m else ""
    return ""


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


def flip_to_in_progress(tree: Path, story_id: str) -> None:
    """Flip [ready] -> [in-progress] INSIDE the worktree, as the branch's first commit.

    Milestone 1 allows no hand-step besides the two judgment points, and
    close.py refuses a story that is not [in-progress] — a refusal that would
    otherwise land only AFTER the teammate has done the whole story. Flipping
    here (not in the lead's tree) keeps spawn out of cross-tree mutation: the
    lead reads [ready] until the merge, and the flip shows up in the cumulative
    diff the reviewer reads.
    """
    plan = tree / ".xp" / "plan.md"
    out = []
    for ln in plan.read_text().splitlines(keepends=True):
        if ln.startswith(f"#### {story_id} ") and "[ready]" in ln:
            ln = ln.replace("[ready]", "[in-progress]")
        out.append(ln)
    plan.write_text("".join(out))
    for args in (["add", ".xp/plan.md"], ["commit", "-qm", f"{story_id} in-progress"]):
        subprocess.run(["git", *args], cwd=tree, capture_output=True, text=True)


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
    report, warning = profile_report(card, prompt)
    print(report)
    if warning:
        print(warning, file=sys.stderr)
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
    if command := bootstrap_command(_read(Path(".xp/system.md"))):
        done = subprocess.run(command, shell=True, cwd=tree, capture_output=True, text=True)
        if done.returncode != 0:
            print(done.stderr.strip(), file=sys.stderr)
            return fail(
                f"refused: worktree bootstrap failed ({command!r}) — not launching"
                f" a teammate into a broken tree. Worktree left at {tree}"
            )
    flip_to_in_progress(tree, story_id)
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
