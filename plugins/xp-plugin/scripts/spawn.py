#!/usr/bin/env python3
"""Spawn a teammate on a story: worktree, clean branch, headless launch.

The piece neither harness provides. The teammate profile is INLINED into the
prompt (DESIGN §8) — paths are a fallback, never the mechanism — and the plugin
itself rides in on --plugin-dir, because a worktree `claude -p` session applies
no project-scoped marketplace enablement and would otherwise load no hooks,
agents or skills. Codex has no --plugin-dir at all, which is why the inlined
profile is the mechanism and not a convenience (DESIGN §3).
"""

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
from close import fail, git, integration_target, story_card
from harness import (
    HARNESS_INSTALL,
    agent_argv,
    claude_argv,  # noqa: F401  — re-exported: story-017's argv tests import it here
    codex_argv,  # noqa: F401
    missing_harness,
)
from teammate_tee import run_stream, run_teammate
from work import (
    card_title,
    chdir_repo_root,
    config_block_value,
    data_root,
    edit_plan,
    plan_path,
    slugify,
    stale_plan,
    user_ns,
)

PLUGIN_ROOT = Path(__file__).parent.parent

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
    total = (len(prompt) + project["CLAUDE.md"] + component_metadata_chars()) // 4
    shares = " · ".join(f"{k} {v // 4}" for k, v in project.items())
    # the CAPPED quantity, not a prompt-derived cousin of it: two computations
    # under one name let a lead read headroom the ratchet does not have
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


def bootstrap_command(system_md: str) -> tuple[str, str]:
    """(command, problem) — at most one is ever non-empty.

    ONE backticked command or nothing runs: a substring match would execute the
    path in "none needed - see [a backticked path]". Deterministic, no judging
    prose (#7). Unreadable REFUSES where absent stays silent — both were "" once,
    and a literal-substring label missed the template's own bolded form, skipping
    the bootstrap into an unprepared tree with no warning.
    """
    for ln in system_md.splitlines():
        label, sep, value = ln.partition(":")
        if not sep or label.strip().strip("*-# ").casefold() != "worktree bootstrap":
            continue
        value = value.strip().rstrip(".")
        if m := re.fullmatch(r"`(.+)`", value):
            return m.group(1), ""
        if "`" not in value and re.match(r"none\b", value, re.I):
            return "", ""
        return "", (
            f"cannot read the Worktree bootstrap line in .xp/system.md: {ln.strip()!r}"
            " — the value must be ONE backticked command, or start with 'none'"
        )
    return "", ""


def resolve_role(role: str, card: str = "", override: str = "") -> tuple[str, str, str]:
    """(harness, model, effort) — CLI override, then the card, then config roles.

    Its own block-scan rather than close.config_flat, which matches at column 0
    and cannot see `executor:` indented under `roles:`.
    """
    spec = override or _card_role(card, role) or _config_role(role)
    parts = [p for p in spec.split("/") if p]
    if len(parts) < 2:
        raise SystemExit(
            fail(f"refused: cannot resolve {role} from {spec!r} — want harness/model[/effort]")
        )
    harness, model, effort = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    if harness not in HARNESS_INSTALL:
        raise SystemExit(
            fail(f"refused: harness {harness!r} — we ship {', '.join(HARNESS_INSTALL)}")
        )
    return harness, model, effort


def _card_role(card: str, role: str) -> str:
    """`Executor:` for the executor, `Reviewer:` for the reviewer. Keyed to the
    ROLE, or one card cannot say "author codex, review claude"."""
    label = f"{role.capitalize()}:"
    for ln in card.splitlines():
        if ln.startswith(label):
            value = ln.removeprefix(label).strip()
            return "" if value == "(default)" else value
    return ""


def _config_role(role: str) -> str:
    return config_block_value("roles", role)


def build_prompt(sections: list[tuple[str, str]]) -> str:
    return "\n".join(f"## {title}\n\n{body}\n" for title, body in sections)


def teammate_sections(card: str) -> list[tuple[str, str]]:
    return [
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        # the escalation command must be runnable: work.py is not on PATH, and
        # spawn inlines this as raw prompt text, so ${CLAUDE_PLUGIN_ROOT} would
        # arrive literal. A teammate hitting "command not found" guesses instead.
        (
            "How you work",
            _read_shipped(PLUGIN_ROOT / "TEAMMATE.md").replace("{PLUGIN_ROOT}", str(PLUGIN_ROOT)),
        ),
        ("Your story card", card),
        ("Constraints", _read(Path(".xp/constraints.md"))),
    ]


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
    """Prompt on stdin: it keeps ~2k tokens out of argv and out of `ps`.

    `role` carried a default shaped for the teammate launch until story-017 moved
    that leg to teammate_tee.run_teammate. Defaulting it now hands a future caller
    XP_ROLE=teammate and no wall clock by omission — the two things the branches
    below turn on.
    """
    env = os.environ | {"XP_ROLE": role}
    # BOTH reviewer legs: a review is the one launch both long-running AND
    # writing, and a hung one owns the lead's tree, with edit rights, forever. A
    # teammate legitimately outruns any wall clock, and cmd_spawn's call site has
    # no except — bounding it would kill a whole story and abandon its worktree.
    # Read from the environment because every test drives these as subprocesses.
    timeout = None
    if role.endswith("reviewer"):
        timeout = float(os.environ.get("XP_AGENT_TIMEOUT", 3600))
    # The STORY reviewer alone: this name is the credential close.py and
    # sprint_close.py gate the merge on, and the plan reviewer never earns it.
    # EMAIL too: with the name alone, every email-keyed tool reports the lead.
    # The sprint pipeline's finders, verifiers and closing pass are NOT it: only
    # its fixer moves the tree, and a credential handed to a leg that must not
    # commit turns sprint_close's stray-authorship refusal into a rubber stamp.
    fixing = not log_id.startswith("sprint-") or log_id == "sprint-fix-review"
    if role == "reviewer" and fixing:
        from review import REVIEWER_EMAIL, REVIEWER_NAME

        env |= {
            "GIT_AUTHOR_NAME": REVIEWER_NAME,
            "GIT_COMMITTER_NAME": REVIEWER_NAME,
            "GIT_AUTHOR_EMAIL": REVIEWER_EMAIL,
            "GIT_COMMITTER_EMAIL": REVIEWER_EMAIL,
        }
    return run_stream(argv, cwd, prompt, log_id, data_root(), harness, env, timeout)


def common_dir_widening(cwd: Path) -> list[str]:
    """["--add-dir", <git common dir>] for a LINKED worktree, [] otherwise: its
    index lives at <main>/.git/worktrees/<id>/, outside workspace-write, so a
    codex agent there cannot commit (bug 0c31ac94 — the 021 probe read this as
    unnecessary because its scratch repo sat under /tmp, which the sandbox
    writes by default). A main checkout's .git is inside the workspace already;
    widening it would loosen the posture for nothing."""
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
    """close.py refuses a story that is not [in-progress], and without this that
    refusal lands only AFTER the teammate has written the whole story. No longer a
    commit on the story branch: the plan is per-clone, so nothing stages and the
    lead sees [in-progress] at once.
    """
    edit_plan(lambda text: flip_map(text, story_id))


def flip_map(text: str, story_id: str) -> str:
    from work import flip_status

    return flip_status(text, story_id, "ready", "in-progress")


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
    """Create the story branch in the CURRENT tree and stop — no worktree, no launch.

    The lead implementing a story solo (DESIGN §8) otherwise has no
    branch-creation step at all, so the work lands on the integration branch and
    close.py's trunk refusal fires only after the story is written. Loud, but the
    recovery is cheap only while nothing is pushed.
    """
    if git("status", "--porcelain").stdout.strip():
        return fail(
            "refused: working tree is dirty — commit or stash first, or the"
            " uncommitted work rides onto the story branch unreviewed"
        )
    branch = story_branch(card, story_id)
    if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).returncode == 0:
        return fail(f"refused: branch {branch} already exists")
    trunk = integration_target()
    made = git("checkout", "-q", "-b", branch, trunk, check=False)
    if made.returncode != 0:
        return fail(f"git checkout -b failed: {made.stderr.strip()}")
    flip_to_in_progress(story_id)
    print(f"{branch} off {trunk} — in place, nothing launched; you are the executor")
    return 0


def story_branch(card: str, story_id: str) -> str:
    return f"{user_ns()}/{story_id}-{slugify(card_title(card))}"


def cmd_spawn(story_id: str, override: str, dry_run: bool, in_place: bool = False) -> int:
    if not plan_path().exists():
        return fail(
            "refused: "
            + (stale_plan() or f"no plan at {plan_path()} — is this an xp-managed repo?")
        )
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if status != "ready":
        hint = not_ready_hint(status, story_id)
        return fail(f"refused: {story_id} is [{status}], spawn requires [ready]. {hint}")
    if drift := ready().drift(story_id, card):
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
    branch = story_branch(card, story_id)
    tree = worktree_path(story_id)
    argv = agent_argv(harness, model, effort, "stream-json", "executor")
    prompt = build_prompt(teammate_sections(card))
    report, warning = profile_report(card, prompt)
    print(report)
    if warning:
        print(warning, file=sys.stderr)
    if dry_run:
        print(" ".join(argv))
        print(prompt)
        return 0
    # AFTER --dry-run, like review.run: inspecting the argv a harness would take is
    # exactly what a lead does before installing it. BEFORE the worktree, though — a
    # missing binary must not cost a tree and a branch to unwind.
    if gone := missing_harness(harness):
        return fail("refused: " + gone)
    # The worktree is cut from a COMMIT, so anything uncommitted — including the
    # scaffold itself on a fresh repo — is simply absent from the teammate's tree.
    # Without this the first spawn after xp-setup tracebacks on a missing plan.md
    # and leaves the worktree behind.
    if dirty := git("status", "--porcelain", check=False).stdout.strip():
        return fail(
            "refused: commit your work before spawning — the teammate's worktree is"
            " cut from a commit, so uncommitted files (a fresh .xp/ scaffold included)"
            f" would not be in it:\n{dirty}"
        )
    if tree.exists():
        return fail(f"refused: {tree} already exists — {story_id} is already spawned")
    if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).returncode == 0:
        return fail(f"refused: branch {branch} already exists")
    trunk = integration_target()
    tree.parent.mkdir(parents=True, exist_ok=True)
    added = git("worktree", "add", "-b", branch, str(tree), trunk, check=False)
    if added.returncode != 0:
        return fail(f"git worktree add failed: {added.stderr.strip()}")
    command, problem = bootstrap_command(_read(Path(".xp/system.md")))
    if problem:
        return fail(f"refused: {problem}. Worktree left at {tree}")
    if command:
        done = subprocess.run(command, shell=True, cwd=tree, capture_output=True, text=True)
        if done.returncode != 0:
            print(done.stderr.strip(), file=sys.stderr)
            return fail(
                f"refused: worktree bootstrap failed ({command!r}) — not launching"
                f" a teammate into a broken tree. Worktree left at {tree}"
            )
    flip_to_in_progress(story_id)
    print(f"{branch} at {tree} (off {trunk})")
    handed_over = tree_state(tree)
    rc = run_teammate(argv, tree, prompt, story_id, data_root(), harness)
    # NOT `if rc: return rc` — a teammate that crashed is the likeliest one to
    # have left work uncommitted, so skipping the guard there withholds the
    # refusal exactly when it is worth most.
    if err := unclean_teammate_result(tree, handed_over, story_id):
        return fail(err)
    return rc


def tree_state(tree: Path) -> tuple[str, str]:
    """(HEAD, porcelain) — the guard's baseline. Raises rather than passing
    stdout through: a FAILED git returns empty output, which reads as an empty
    porcelain and a HEAD unequal to the flip's — clean and committed, the one
    wrong answer the guard can give."""

    def out(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=tree, capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(f"git {args[0]} failed in {tree}: {(r.stderr or r.stdout).strip()}")
        return r.stdout.strip()

    return out("rev-parse", "HEAD"), out("status", "--porcelain")


def unclean_teammate_result(tree: Path, handed_over: tuple[str, str], story_id: str) -> str:
    """ "" when the teammate left a clean, committed story behind; otherwise the
    refusal, naming both recoveries.

    Both halves measure against the tree AS HANDED OVER: raw porcelain would charge
    the teammate with whatever the bootstrap command dirtied before it started.
    """
    flip_head, handed_dirty = handed_over
    recovery = (
        f" Recover by committing by hand in {tree}, or by"
        f" `git worktree remove {tree}`, putting {story_id}'s heading back to [ready]"
        f" in {plan_path()}, and re-spawning."
    )
    try:
        head, dirty = tree_state(tree)
    except OSError as e:
        return f"refused: the story is unverified — {e}.{recovery}"
    if left := sorted(set(dirty.splitlines()) - set(handed_dirty.splitlines())):
        return "refused: the teammate left work uncommitted in {}:\n{}\n{}".format(
            tree, "\n".join(left), recovery
        )
    if head == flip_head:
        return f"refused: the teammate made no commits of its own in {tree}.{recovery}"
    return ""


def ready():
    """The credential leg, in its own leaf module under the 500-line cap
    (constraint 8). Still function-local: only `main` and one refusal reach it,
    and a module-level edge would import it on every hook that touches spawn."""
    import ready as module

    return module


def main() -> int:
    if sys.argv[1:2] == ["ready"]:
        return ready().main(sys.argv[2:])
    p = argparse.ArgumentParser(
        description=__doc__,
        epilog="ready <story-id>: after the plan review, mint the card's digest and"
        " flip [planned] -> [ready]. Editing the card afterwards refuses the spawn.",
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
