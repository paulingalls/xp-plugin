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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "spawn"))
# close must import back FUNCTION-LOCALLY: a module-level edge cycles
# (close -> spawn -> close) and fails before fail/git exist (story-008).
from bookkeep import bootstrap_command, worktree_command
from close import fail, git, integration_target, story_card
from handoff import draft_path, inheritance, marker_path, report_handoff
from harness import (
    HARNESS_INSTALL,
    agent_argv,
    claude_argv,  # noqa: F401  — re-exported: story-017's argv tests import it here
    codex_argv,  # noqa: F401
    missing_harness,
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
    """(breakdown for the lead, warning or "") — routed to the LEAD, never into
    the teammate's prompt where it is noise and unactionable. An always-identical
    table is wallpaper (constraints.md #3), so the warning is what carries news.

    `handoff` is listed only when there IS one, and it is taken as an argument
    rather than re-derived: a contributor the breakdown cannot see is one the
    overage warning blames some other file for."""
    project = {
        "the story card": len(card),
        "constraints.md": len(_read(Path(".xp/constraints.md"))),
        "CLAUDE.md": len(_read(Path("CLAUDE.md"))),
    }
    if handoff:
        project["predecessor handoff"] = len(handoff)
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


def teammate_sections(card: str, story_id: str, handoff: str) -> list[tuple[str, str]]:
    sections = [
        ("VALUES", _read_shipped(PLUGIN_ROOT / "VALUES.md")),
        # the escalation command must be runnable: work.py is not on PATH, and
        # spawn inlines this as raw prompt text, so ${CLAUDE_PLUGIN_ROOT} would
        # arrive literal. A teammate hitting "command not found" guesses instead.
        (
            "How you work",
            _read_shipped(PLUGIN_ROOT / "TEAMMATE.md")
            .replace("{PLUGIN_ROOT}", str(PLUGIN_ROOT))
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
    """Prompt on stdin: it keeps ~2k tokens out of argv and out of `ps`.

    `role` takes no default: one would hand a caller XP_ROLE=teammate and no wall
    clock by omission — the two things the branches below turn on.
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
        # The read-only bound is the ABSENT credential plus close.py's HEAD check,
        # never the permission mode — bypass stays (harness.PERMISSION_ARGV).
        env = {k: v for k, v in env.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    return run_stream(
        argv, cwd, prompt, log_id, data_root(), harness, env, timeout, widen_git=False
    )


def common_dir_widening(cwd: Path) -> list[str]:
    """["--add-dir", <git common dir>] for a LINKED executor worktree, [] otherwise: its
    index lives at <main>/.git/worktrees/<id>/, outside workspace-write, so a
    codex teammate there cannot commit (bug 0c31ac94; a /tmp scratch repo hides it,
    since the sandbox writes /tmp anyway). A main checkout's .git is inside the
    workspace already; widening it would loosen the posture for nothing."""
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
        return fail("refused: " + missing_plan_refusal())
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
    argv = agent_argv(harness, model, effort, "stream-json")
    handoff = inheritance(data_root(), story_id)
    prompt = build_prompt(teammate_sections(card, story_id, handoff))
    report, warning = profile_report(card, prompt, handoff)
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
    # Parsed here and RUN below: reading the line needs no tree, and refusing
    # after `worktree add` leaves a tree and a branch whose only effect is that
    # the corrected retry refuses with "already spawned" instead.
    system = Path(".xp/system.md")
    if not system.parent.exists():
        # NOT a `mkdir -p .xp && cp`: that half-scaffold locks setup.py out for good.
        return fail(
            f"refused: no .xp/ here — is this an xp-managed repo? Restore .xp/ from"
            f" version control; xp-setup refuses over the plan at {plan_path()}"
        )
    if not system.exists():
        return fail(
            f"refused: {system} is missing — the worktree bootstrap line lives there. Run"
            f" `cp {PLUGIN_ROOT / 'templates' / 'system.md'} {system}`,"
            " then edit its Worktree bootstrap line"
        )
    try:
        command, problem = bootstrap_command(system.read_text())
    except UnicodeDecodeError as exc:
        return fail(f"refused: {system} is not UTF-8 ({exc}) — rewrite it as UTF-8 text")
    if problem:
        return fail("refused: " + problem)
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
    print(f"{branch} at {tree} (off {trunk})")
    handed_over = tree_state(tree)
    before = {eid for eid, _ in entries(data_root())}
    rc = run_teammate(argv, tree, prompt, story_id, data_root(), harness)
    # NOT `if rc: return rc` — a teammate that crashed is the likeliest one to
    # have left work uncommitted, so skipping the guard there withholds the
    # refusal exactly when it is worth most.
    if err := unclean_teammate_result(tree, handed_over, story_id):
        return report_handoff(data_root(), story_id, before, err, rc)
    marker_path(data_root(), story_id).unlink(missing_ok=True)
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
    system = tree / ".xp/system.md"
    try:
        text = system.read_text() if system.exists() else ""
        teardown, problem = worktree_command(text, "teardown")
    except UnicodeDecodeError as exc:
        teardown, problem = "", f"Could not read {system}: {exc}"
    discard = f"`git worktree remove {tree}`"
    if teardown:
        discard = (
            f"running {teardown!r} and then `git worktree remove {tree}`"
            " (add --force if teardown leaves files behind)"
        )
    recovery = (
        f" Recover by committing by hand in {tree}, or by {discard}, putting"
        f" {story_id}'s heading back to [ready] in {plan_path()}, and re-spawning."
        + (f" {problem}." if problem else "")
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
