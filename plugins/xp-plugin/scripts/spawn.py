#!/usr/bin/env python3
"""Spawn or resume a fresh teammate in a story worktree."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))
# close must import back FUNCTION-LOCALLY: a module-level edge cycles
# (close -> spawn -> close) and fails before fail/git exist (story-008).
from bookkeep import bootstrap_command
from close import config_flat, fail, git, integration_target, story_card
from env import plugin_version
from handback import tree_state, unclean_teammate_result
from handoff import draft_path, inheritance, marker_path, report_handoff
from harness import (
    HARNESS_INSTALL,
    agent_argv,
    claude_argv,  # noqa: F401  — re-exported: story-017's argv tests import it here
    codex_argv,  # noqa: F401
    missing_harness,
    resolve_codex_sandbox,
)
from role_config import card_role, config_role
from teammate_tee import run_stream, run_teammate
from work import (
    card_title,
    chdir_repo_root,
    data_root,
    entries,
    flip_card,
    missing_plan_refusal,
    plan_path,
    slugify,
    strip_comment,
    user_ns,
)

PLUGIN_ROOT = Path(__file__).parent.parent
PROJECT_PLUGIN = Path("plugins/xp-plugin")

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


def profile_report(card: str, prompt: str, handoff: str) -> tuple[str, str]:
    """Return the lead's profile breakdown and actionable overage warning."""
    project = {
        "the story card": len(card),
        "constraints.md": len(_read(Path(".xp/constraints.md"))),
        "CLAUDE.md": len(_read(Path("CLAUDE.md"))),
    }
    if handoff:
        project["predecessor handoff"] = len(handoff)
    total = (len(prompt) + project["CLAUDE.md"] + component_metadata_chars()) // 4
    shares = " · ".join(f"{k} {v // 4}" for k, v in project.items())
    line = (
        f"profile: total {total} tokens · plugin-shipped"
        f" {plugin_shipped_chars() // 4}/{PLUGIN_SHIPPED_CAP} · {shares}"
    )
    if total <= TOTAL_TARGET:
        return line, ""
    largest = max(project, key=lambda k: project[k])
    return line, (
        f"note: teammate profile is {total} tokens, over the {TOTAL_TARGET} target."
        f" Largest project-owned contributor is {largest} ({project[largest] // 4} tokens)"
        " — yours to retire, not the plugin's."
    )


def template_role_line(role: str) -> str:
    return next(
        line
        for raw in (PLUGIN_ROOT / "templates" / "config.yml").read_text().splitlines()
        if (line := strip_comment(raw).rstrip()).lstrip().startswith(f"{role}:")
    )


def resolve_role(role: str, card: str = "", override: str = "") -> tuple[str, str, str]:
    spec = override or card_role(card, role)
    config_source = not spec
    if config_source:
        spec = config_role(role, "\0")
    if spec == "\0":
        if not Path(".xp/config.yml").exists():
            raise SystemExit(fail("refused: no .xp/config.yml here — is this an xp-managed repo?"))
        raise SystemExit(
            fail(
                f"refused: roles.{role} is absent from .xp/config.yml — your config predates"
                f" this key; add `{template_role_line(role)}` under `roles:`"
            )
        )
    parts = [p for p in spec.split("/") if p]
    if len(parts) < 2:
        if config_source:
            raise SystemExit(
                fail(
                    f"refused: roles.{role} in .xp/config.yml is malformed as {spec!r}"
                    f" — replace it with `{template_role_line(role)}`"
                )
            )
        raise SystemExit(
            fail(f"refused: cannot resolve {role} from {spec!r} — want harness/model[/effort]")
        )
    harness, model, effort = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    if harness not in HARNESS_INSTALL:
        raise SystemExit(
            fail(f"refused: harness {harness!r} — we ship {', '.join(HARNESS_INSTALL)}")
        )
    return harness, model, effort


def build_prompt(sections: list[tuple[str, str]]) -> str:
    return "\n".join(f"## {title}\n\n{body}\n" for title, body in sections)


def teammate_sections(
    card: str, story_id: str, handoff: str, plugin_root: Path
) -> list[tuple[str, str]]:
    sections = [
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        # the escalation command must be runnable: work.py is not on PATH, and
        # spawn inlines this as raw prompt text, so ${CLAUDE_PLUGIN_ROOT} would
        # arrive literal. A teammate hitting "command not found" guesses instead.
        (
            "How you work",
            _read_shipped(PLUGIN_ROOT / "TEAMMATE.md")
            .replace("{PLUGIN_ROOT}", str(plugin_root))
            .replace("{PLAN_PATH}", str(draft_path(data_root(), story_id))),
        ),
        ("Your story card", card),
        ("Constraints", _read(Path(".xp/constraints.md"))),
    ]
    if handoff:
        sections.append(("Predecessor handoff", handoff))
    return sections


def _read(path: Path) -> str:
    """Project-owned files: a consuming project may legitimately lack them."""
    return path.read_text() if path.exists() else f"(missing: {path})"


def _read_shipped(path: Path) -> str:
    """Plugin-owned prose: absence is a broken install, not a project variation.
    Soft-reading it hands the teammate "(missing: ...)" as its VALUES section."""
    if not path.exists():
        raise SystemExit(fail(f"refused: {path} is missing — the plugin install is broken"))
    return path.read_text()


def run_agent(
    argv: list[str],
    cwd: Path,
    prompt: str,
    role: str,
    harness: str,
    log_id: str,
) -> subprocess.CompletedProcess:
    """Run one role with its prompt off argv and the reviewer silence bound on."""
    env = os.environ | {"XP_ROLE": role}
    # BOTH reviewer legs: a review is the one launch both long-running AND
    # writing, and a hung one owns the lead's tree, with edit rights, forever. A
    # teammate legitimately outruns any bound, and cmd_spawn's call site has no
    # except — bounding it would kill a whole story and abandon its worktree.
    # The number is the longest SILENCE tolerated, not a total budget: run_stream
    # restarts it on every streamed line. Read from the environment because every
    # test drives these as subprocesses.
    timeout = None
    if role.endswith("reviewer"):
        timeout = float(os.environ.get("XP_AGENT_TIMEOUT", 3600))
        # The read-only bound is the ABSENT credential plus close.py's HEAD check,
        # never the permission mode — bypass stays (harness.PERMISSION_ARGV).
        env = {k: v for k, v in env.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    return run_stream(
        argv, cwd, prompt, log_id, data_root(), harness, env, timeout, widen_git=False
    )


def common_dir_widening(cwd: Path) -> list[str]:
    """Widen a linked executor worktree to its out-of-tree git common dir."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    common = Path(proc.stdout.strip())
    common = common if common.is_absolute() else (cwd / common).resolve()
    return [] if common.is_relative_to(Path(cwd).resolve()) else ["--add-dir", str(common)]


def worktree_path(story_id: str) -> Path:
    return data_root() / "worktrees" / story_id


def execution_root(tree: Path, trunk: str) -> Path:
    # Asked of TRUNK, not of `tree`: the prompt is built before the worktree is cut,
    # so an is_dir() check here answers False and silently re-ships the installed copy.
    source = PROJECT_PLUGIN / "scripts" / "spawn.py"
    exists = git("cat-file", "-e", f"{trunk}:{source}", check=False)
    return tree / PROJECT_PLUGIN if exists.returncode == 0 else PLUGIN_ROOT


def flip_to_in_progress(story_id: str) -> None:
    """close.py refuses a story that is not [in-progress], and without this that
    refusal lands only AFTER the teammate has written the whole story."""
    flip_card(story_id, "ready", "in-progress")


def not_ready_hint(status: str, story_id: str) -> str:
    if status == "in-progress":
        return (
            "An earlier spawn already flipped it, and since the plan is per-clone the"
            f" flip lives in {plan_path()} — not on the story branch, so removing the"
            " worktree and deleting the branch no longer undo it. To start this story"
            " over, put its heading back to [ready] there."
        )
    return (
        "A card starts [planned]; the plan review and then `spawn.py ready"
        f" {story_id}` are what clear it — twice in sprint-003 a card reached a teammate"
        " with no review, and only a human caught it"
    )


def cmd_in_place(story_id: str, card: str) -> int:
    """Create the story branch in the current tree without launching."""
    if git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: working tree is dirty — commit or stash first, or the"
            " uncommitted work rides onto the story branch unreviewed"
        )
    branch = story_branch(card, story_id)
    if FREE_ID.fullmatch(story_id) and current_branch() == branch:
        flip_to_in_progress(story_id)
        print(f"{branch} already current — in place, nothing launched; you are the executor")
        return 0
    if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).returncode == 0:
        return fail(f"refused: branch {branch} already exists")
    trunk = integration_target()
    made = git("checkout", "-q", "-b", branch, trunk, check=False)
    if made.returncode != 0:
        return fail(f"git checkout -b failed: {made.stderr.strip()}")
    flip_to_in_progress(story_id)
    print(f"{branch} off {trunk} — in place, nothing launched; you are the executor")
    return 0


# The shape close/free.py cuts and every free leg keys off; group 2 is the slug
# those legs take as their argument.
FREE_ID = re.compile(r"free-(\d{4}-\d\d-\d\d-(.+))")


def story_branch(card: str, story_id: str) -> str:
    if FREE_ID.fullmatch(story_id):
        return f"{user_ns()}/{story_id}"
    return f"{user_ns()}/{story_id}-{slugify(card_title(card))}"


def current_branch() -> str:
    return git("branch", "--show-current").stdout.strip()


def cmd_spawn(
    story_id: str, override: str, dry_run: bool, in_place: bool = False, resuming: bool = False
) -> int:
    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if resuming and (drift := ready().drift(story_id, card, resume().remint_route(story_id))):
        return fail(drift)
    if resuming and status not in {"ready", "in-progress"}:
        return fail(f"refused: {story_id} is [{status}], resume requires [in-progress] or [ready]")
    if not resuming and status != "ready":
        hint = not_ready_hint(status, story_id)
        return fail(f"refused: {story_id} is [{status}], spawn requires [ready]. {hint}")
    if not resuming and (drift := ready().drift(story_id, card)):
        return fail(drift)
    if in_place:
        if dry_run:
            print(
                f"would create {story_branch(card, story_id)} off {integration_target()},"
                f" flip {story_id} to [in-progress], and launch nothing"
            )
            return 0
        return cmd_in_place(story_id, card)
    harness, model, effort = resolve_role("executor", card, override)
    sandbox, problem = resolve_codex_sandbox(harness, config_flat("codex_sandbox"))
    if problem:
        return fail("refused: " + problem)
    branch = story_branch(card, story_id)
    tree = worktree_path(story_id)
    trunk = integration_target()
    plugin_root = execution_root(tree, trunk)
    reuse = bool(FREE_ID.fullmatch(story_id)) and current_branch() == branch
    argv = agent_argv(harness, model, effort, "stream-json", sandbox)
    handoff = inheritance(data_root(), story_id)
    if resuming and tree.is_dir():
        handoff += resume().inherited_evidence(tree, trunk)
    prompt = build_prompt(teammate_sections(card, story_id, handoff, plugin_root))
    report, warning = profile_report(card, prompt, handoff)
    print(report)
    if warning:
        print(warning, file=sys.stderr)
    if dry_run:
        print(" ".join(argv))
        print(prompt)
        return 0
    # Check the harness before creating a tree that a failed launch would strand.
    if gone := missing_harness(harness):
        return fail("refused: " + gone)
    # Parse bootstrap before creating a tree that a bad command would strand.
    system = Path(".xp/system.md")
    if not resuming and not system.parent.exists():
        # NOT a `mkdir -p .xp && cp`: that half-scaffold locks setup.py out for good.
        return fail(
            f"refused: no .xp/ here — is this an xp-managed repo? Restore .xp/ from"
            f" version control; xp-setup refuses over the plan at {plan_path()}"
        )
    if not resuming and not system.exists():
        return fail(
            f"refused: {system} is missing — the worktree bootstrap line lives there. Run"
            f" `cp {PLUGIN_ROOT / 'templates' / 'system.md'} {system}`,"
            " then edit its Worktree bootstrap line"
        )
    command = ""
    if not resuming:
        try:
            command, problem = bootstrap_command(system.read_text())
        except UnicodeDecodeError as exc:
            return fail(f"refused: {system} is not UTF-8 ({exc}) — rewrite it as UTF-8 text")
        if problem:
            return fail("refused: " + problem)
    # A commit-cut worktree omits dirt, including a fresh scaffold, and then the
    # teammate fails on the missing plan.
    if not resuming and (dirty := git("status", "--porcelain", check=False).stdout.strip()):
        return fail(
            "refused: commit your work before spawning — the teammate's worktree is"
            " cut from a commit, so uncommitted files (a fresh .xp/ scaffold included)"
            f" would not be in it:\n{dirty}"
        )
    held, problem = resume().acquire(data_root(), story_id)
    if problem:
        return fail(problem)
    if resuming:
        if problem := resume().validate(data_root(), story_id, tree, branch):
            held.close()
            return fail(problem)
        if status == "ready":
            flip_to_in_progress(story_id)
    else:
        if tree.exists():
            return fail(f"refused: {tree} already exists — {story_id} is already spawned")
        exists = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
        if not reuse and exists.returncode == 0:
            # Deleting the named branch is the obvious recovery, and on a free
            # patch it discards the release commits `free start` left there.
            stand = (
                f" — `git checkout {branch}` first: it is this patch's free branch,"
                " and spawn continues it rather than cutting a new one"
                if FREE_ID.fullmatch(story_id)
                else ""
            )
            return fail(f"refused: branch {branch} already exists{stand}")
        tree.parent.mkdir(parents=True, exist_ok=True)
        if reuse:
            moved = git("checkout", "-q", trunk, check=False)
            if moved.returncode:
                return fail(f"git checkout {trunk} failed: {moved.stderr.strip()}")
            print(f"lead checkout moved to {trunk}")
        args = ("worktree", "add", str(tree), branch)
        if not reuse:
            args = ("worktree", "add", "-b", branch, str(tree), trunk)
        added = git(*args, check=False)
        if added.returncode != 0:
            return fail(f"git worktree add failed: {added.stderr.strip()}")
        if command:
            done = subprocess.run(command, shell=True, cwd=tree, capture_output=True, text=True)
            if done.returncode != 0:
                print(done.stderr.strip(), file=sys.stderr)
                return fail(
                    f"refused: worktree bootstrap failed ({command!r}) — not launching"
                    f" a teammate into a broken tree. Worktree left at {tree}"
                )
        flip_to_in_progress(story_id)
    # The teammate is the FIRST writer of plans/ — it drafts before plan_review.py,
    # which is what creates the directory today — and a shell redirect does not
    # make one. Left to fail, the model's own recovery is to draft inside the
    # worktree, which is exactly the loss this path exists to prevent.
    draft_path(data_root(), story_id).parent.mkdir(parents=True, exist_ok=True)
    cut = "resumed" if resuming else ("continued, not cut" if reuse else f"off {trunk}")
    print(f"{branch} at {tree} ({cut})")
    handed_over = tree_state(tree)
    before = {eid for eid, _ in entries(data_root())}
    rc = run_teammate(argv, tree, prompt, story_id, data_root(), harness)
    # A crashed teammate is the likeliest one to leave work uncommitted.
    err = unclean_teammate_result(tree, handed_over, story_id, resuming)
    if err or rc:
        why = err or f"the teammate left a clean commit in {tree} before its harness failed"
        result = report_handoff(data_root(), story_id, before, why, rc)
        held.close()
        return result
    free_id = FREE_ID.fullmatch(story_id)
    scope = f"free {free_id.group(2)}" if free_id else f"story {story_id}"
    # The free leg reads its branch off HEAD, and spawn just moved the lead to trunk.
    where = " from that worktree" if free_id else ""
    leg = f"run `close.py {scope} review`{where}"
    if plugin_root != PLUGIN_ROOT:
        leg = (
            f"use xp-plugin {plugin_version(plugin_root)} at {plugin_root} for every close.py"
            f" leg, starting with `python3 {plugin_root}/scripts/close.py {scope} review`{where}"
        )
    print(f"{story_id} produced commit {tree_state(tree)[0]} at {tree}. Read it, then {leg}.")
    marker_path(data_root(), story_id).unlink(missing_ok=True)
    held.close()
    return rc


def ready():
    """Load the credential leaf only on its two call paths."""
    import ready as module

    return module


def resume():
    import resume as module

    return module


def main() -> int:
    if sys.argv[1:2] == ["ready"]:
        return ready().main(sys.argv[2:])
    if sys.argv[1:2] == ["resume"]:
        a = resume().parse(sys.argv[2:])
        if not chdir_repo_root():
            return fail("refused: not inside a git repository")
        return cmd_spawn(a.story_id, a.executor, a.dry_run, resuming=True)
    p = argparse.ArgumentParser(
        description=__doc__,
        epilog="ready <story-id>: after the card review, mint the card's digest and"
        " flip [planned] -> [ready]. Editing the card afterwards refuses the spawn."
        " resume <story-id>: hand a STOPPED story's own worktree to a fresh teammate.",
    )
    p.add_argument("story_id")
    p.add_argument("executor", nargs="?", default="", help="harness/model[/effort] override")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--in-place",
        action="store_true",
        help="create the story branch here and stop — the lead executes it solo",
    )
    a = p.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return cmd_spawn(a.story_id, a.executor, a.dry_run, a.in_place)


if __name__ == "__main__":
    sys.exit(main())
