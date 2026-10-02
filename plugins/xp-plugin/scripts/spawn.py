#!/usr/bin/env python3
"""Spawn or resume a fresh teammate in a story worktree."""

import argparse
import contextlib as contextlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))
# close must import back FUNCTION-LOCALLY: a module-level edge cycles
# (close -> spawn -> close) and fails before fail/git exist (story-008).
# `card_profile`, never `profile`: this file puts scripts/spawn on sys.path, and a
# module named for a stdlib one shadows it process-wide (cProfile imports `profile`).
import card_profile as profile
import handoff as handoff_io  # noqa: F401
import story_stages as stages  # noqa: F401
from bookkeep import bootstrap_command
from close import config_flat, config_has, fail, git, integration_target, leg, story_card
from handback import story_tier as story_tier
from handback import tree_state
from handback import unclean_teammate_result as unclean_teammate_result
from handoff import draft_path, handoff_state, inheritance, mark_handoff, report_handoff
from handoff import mark_stage as mark_stage
from harness import HARNESS_INSTALL, agent_argv, missing_harness, resolve_codex_sandbox
from prompt import _read as _read
from prompt import _read_shipped as _read_shipped
from prompt import build_prompt as build_prompt
from prompt import executor_prompt as executor_prompt
from prompt import teammate_sections as _teammate_sections
from review_scope import declared_files
from role_config import card_role, config_role
from teammate_tee import AGENT_TIMEOUT_DEFAULT, run_stream
from teammate_tee import run_teammate as run_teammate
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
DEFAULT_PROFILE_TARGET = profile.DEFAULT_PROFILE_TARGET


def component_metadata_chars() -> int:
    return profile.component_metadata_chars(PLUGIN_ROOT)


def profile_report(card: str, prompt: str, handoff: str) -> tuple[str, str]:
    return profile.profile_report(card, prompt, handoff, PLUGIN_ROOT, _read, profile_target())


def profile_target() -> int:
    try:
        return profile.profile_target(config_has, config_flat)
    except ValueError as error:
        raise SystemExit(fail(f"refused: {error}")) from error


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
        if config_source:
            raise SystemExit(
                fail(
                    f"refused: roles.{role} in .xp/config.yml names unknown harness"
                    f" {harness!r} — we ship {', '.join(HARNESS_INSTALL)}; replace it"
                    f" with `{template_role_line(role)}`"
                )
            )
        raise SystemExit(
            fail(f"refused: harness {harness!r} — we ship {', '.join(HARNESS_INSTALL)}")
        )
    return harness, model, effort


def teammate_sections(
    card: str,
    story_id: str,
    handoff: str,
    plugin_root: Path,
    brief: str | None = None,
    multifile: bool = True,
) -> list[tuple[str, str]]:
    return _teammate_sections(card, story_id, handoff, plugin_root, PLUGIN_ROOT, brief, multifile)


def run_agent(
    argv: list[str],
    cwd: Path,
    prompt: str,
    role: str,
    harness: str,
    log_id: str,
    echo: bool = True,
    cancel=None,
) -> subprocess.CompletedProcess:
    """Run one role with its prompt off argv and the reviewer silence bound on."""
    env = os.environ | {"XP_ROLE": role, "XP_HARNESS": harness}
    # Never the executor or planner: cmd_spawn's call sites have no except, so a
    # bound there kills a whole story and abandons its worktree (rejected design).
    timeout = None
    if role.endswith("reviewer"):
        timeout = float(os.environ.get("XP_AGENT_TIMEOUT", AGENT_TIMEOUT_DEFAULT))
        # The read-only bound is the ABSENT credential plus close.py's HEAD check,
        # never the permission mode — bypass stays (harness.PERMISSION_ARGV).
        env = {k: v for k, v in env.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    return run_stream(
        argv,
        cwd,
        prompt,
        log_id,
        data_root(),
        harness,
        env,
        timeout,
        widen_git=False,
        echo=echo,
        cancel=cancel,
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


def flip_to_in_progress(story_id: str) -> None:
    """Both marks of a started story, together: close.py refuses a card that is not
    [in-progress], and ready.py refuses re-minting one already handed to an executor."""
    flip_card(story_id, "ready", "in-progress")
    mark_handoff(data_root(), story_id)


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


def story_branch(card: str, story_id: str) -> str:
    if leg(story_id)[1]:
        return f"{user_ns()}/{story_id}"
    return f"{user_ns()}/{story_id}-{slugify(card_title(card))}"


def cmd_spawn(story_id: str, override: str, dry_run: bool, resuming: bool = False) -> int:
    if dry_run:
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if resuming and (drift := ready().drift(story_id, card)):
        return fail(drift)
    if resuming and status not in {"ready", "in-progress"}:
        return fail(f"refused: {story_id} is [{status}], resume requires [in-progress] or [ready]")
    if not resuming and status != "ready":
        hint = not_ready_hint(status, story_id)
        return fail(f"refused: {story_id} is [{status}], spawn requires [ready]. {hint}")
    if not resuming and (drift := ready().drift(story_id, card)):
        return fail(drift)
    try:
        multifile = len(declared_files(card)) > 1
    except ValueError as error:
        repair = ready().AMEND.format(story_id)
        return fail(f"refused: {error}. Repair the Files line in {plan_path()}. {repair}")
    if (
        not resuming
        and not leg(story_id)[1]
        and (problem := ready().check_refresh(story_id, card, require_digest=False))
    ):
        return fail(problem)
    harness, model, effort = resolve_role("executor", card, override)
    sandbox, problem = resolve_codex_sandbox(harness, config_flat("codex_sandbox"))
    if problem:
        return fail("refused: " + problem)
    if gone := missing_harness(harness):
        return fail("refused: " + gone)
    argv = agent_argv(harness, model, effort, "stream-json", sandbox)
    branch = story_branch(card, story_id)
    tree = worktree_path(story_id)
    trunk = integration_target()
    free_ref = False
    inherited_state = handoff_state(data_root(), story_id)
    handoff = inheritance(data_root(), story_id, multifile=multifile)
    if resuming and tree.is_dir():
        handoff += resume().inherited_evidence(tree, trunk)
    if dry_run:
        import execution

        return execution.preview(
            sys.modules[__name__],
            story_id,
            card,
            tree,
            handoff,
            inherited_state,
            multifile,
            resuming,
            override,
        )
    # Parse bootstrap before creating a tree that a bad command would strand.
    system = Path(".xp/system.md")
    if not resuming and not system.parent.exists():
        # NOT a `mkdir -p .xp && cp`: that half-scaffold locks setup.py out for good.
        return fail(
            "refused: no .xp/ here — is this an xp-managed repo? Run `/xp-setup`; it"
            f" refuses over the plan at {plan_path()}"
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
            return fail(
                f"refused: {tree} already exists — run `spawn.py resume {story_id}` to"
                " inspect its handoff and take that tree over"
            )
        exists = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
        free_ref = bool(leg(story_id)[1]) and exists.returncode == 0
        if free_ref and git("branch", "--show-current").stdout.strip() == branch:
            return fail(
                f"refused: {branch} is checked out by the lead — return to {trunk}; spawn"
                " leaves the lead checkout untouched and continues this ref in its worktree"
            )
        if not free_ref and exists.returncode == 0:
            return fail(f"refused: branch {branch} already exists")
        tree.parent.mkdir(parents=True, exist_ok=True)
        args = (
            ("worktree", "add", str(tree), branch)
            if free_ref
            else ("worktree", "add", "-b", branch, str(tree), trunk)
        )
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
    # The external plan must survive a stopped or removed worktree.
    draft_path(data_root(), story_id).parent.mkdir(parents=True, exist_ok=True)
    cut = "resumed" if resuming else ("continued, not cut" if free_ref else f"off {trunk}")
    print(f"{branch} at {tree} ({cut})")
    handed_over = tree_state(tree)
    before = {eid for eid, _ in entries(data_root())}

    def stage_line() -> str:
        ran = (handoff_state(data_root(), story_id) or {}).get("stages", {})
        return "stages: " + (" · ".join(f"{n}={r}" for n, r in ran.items()) or "none reached")

    def stop(why: str, code: int) -> int:
        # EVERY exit: on a stop it is what says whether a plan was reviewed at all.
        print(stage_line())
        result = report_handoff(data_root(), story_id, before, why, code)
        held.close()
        return result

    import execution

    return execution.run(
        sys.modules[__name__],
        story_id,
        card,
        tree,
        handoff,
        inherited_state,
        multifile,
        resuming,
        trunk,
        handed_over,
        harness,
        argv,
        stop,
        stage_line,
        held,
        override,
    )


def ready():
    """Load the credential leaf only on its two call paths."""
    import ready as module

    return module


def resume():
    import resume as module

    return module


def main() -> int:
    if sys.argv[1:2] in (["ready"], ["amend"]):
        return ready().main(sys.argv[2:], sys.argv[1])
    if sys.argv[1:2] == ["resume"]:
        a = resume().parse(sys.argv[2:])
        if not chdir_repo_root():
            return fail("refused: not inside a git repository")
        return cmd_spawn(a.story_id, a.executor, a.dry_run, resuming=True)
    # After the subcommand dispatch, so the story_id it echoes is a story_id: ahead
    # of it, `spawn.py resume <id> --in-place` names `spawn.py resume` as the launch.
    if "--in-place" in sys.argv[1:]:
        story_id = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), "<story-id>")
        return fail(
            f"refused: --in-place was removed; run `spawn.py {story_id}` to launch"
            " the executor in its worktree"
        )
    p = argparse.ArgumentParser(
        description=__doc__,
        epilog="ready <story-id>: after the slate review, mint the card's digest and"
        " flip [planned] -> [ready]. amend <story-id> --reason: record a later card edit."
        " resume <story-id>: hand a STOPPED or FINISHED tree to a fresh teammate.",
    )
    p.add_argument("story_id")
    p.add_argument("executor", nargs="?", default="", help="harness/model[/effort] override")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return cmd_spawn(a.story_id, a.executor, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
