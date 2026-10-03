#!/usr/bin/env python3
"""Story review records judgment; story land runs gates and moves refs without spawning."""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "close"))
from diff_range import render as render_diff_range
from env import sprint_branch
from lifecycle import declared_commands as verify_commands
from work import (
    data_root,
    missing_plan_refusal,
    plan_path,
    strip_comment,
    work_entries_since,
)

FREE_ID = re.compile(r"free-(\d{4}-\d\d-\d\d-(.+))")


def fail(msg: str) -> "int":
    sys.stdout.flush()
    print(msg, file=sys.stderr)
    return 2


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def salvage_dirty_refusal() -> str:
    dirty = git("status", "--porcelain").stdout.strip()
    if not dirty:
        return ""
    return (
        "the working tree may contain a dead reviewer's uninspected work; read it"
        " before committing or discarding it, then retry salvage with a clean tree;"
        " uncommitted:\n  " + dirty
    )


def story_card(plan: str, story_id: str) -> tuple[str, str]:
    lines = plan.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"#### {story_id} ")), None)
    if start is None:
        raise KeyError(f"{story_id} not found in the plan")
    if any(ln.startswith(f"#### {story_id} ") for ln in lines[start + 1 :]):
        raise KeyError(
            f"{story_id} appears more than once in the plan — readers pick the first"
            " card and the status flip rewrites the last, so delete or rename one"
        )
    rest = range(start + 1, len(lines))
    end = next((i for i in rest if lines[i].startswith(("# ", "## ", "### ", "#### "))), len(lines))
    card = "".join(lines[start:end])
    if "[" not in lines[start]:
        raise KeyError(f"{story_id} header has no [status] bracket in the plan")
    status = lines[start].rsplit("[", 1)[1].rstrip().rstrip("]")
    return card, status


def leg(story_id: str) -> tuple[str, str]:
    free = FREE_ID.fullmatch(story_id)
    return (f"free {free.group(2)}", free.group(2)) if free else (f"story {story_id}", "")


def config_flat(key: str) -> str:
    cfg = Path(".xp/config.yml")
    if not cfg.exists():
        return ""
    for ln in cfg.read_text().splitlines():
        if ln.startswith(f"{key}:"):
            return strip_comment(ln).split(":", 1)[1].strip()
    return ""


def config_has(key: str) -> bool:
    cfg = Path(".xp/config.yml")
    return cfg.exists() and any(ln.startswith(f"{key}:") for ln in cfg.read_text().splitlines())


def integration_target() -> str:
    if config_flat("release") == "sprint":
        if config_has("sprint_branch"):
            raise SystemExit(
                fail(
                    "refused: remove sprint_branch: from .xp/config.yml, THEN record"
                    " this clone's branch with `xp.py sprint <id> open` — without"
                    " that record every story merge falls back to the default branch"
                )
            )
        branch = sprint_branch()
        if branch:
            ok = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
            if ok.returncode != 0:
                print(
                    f"recorded sprint branch refs/heads/{branch} does not exist —"
                    " refusing to fall back to the default branch (a fresh clone must"
                    " open its sprint, not silently merge to trunk)",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            return branch
    return default_branch()


def default_branch() -> str:
    """`trunk:` overrides git's default; a missing configured branch never falls back."""
    if name := config_flat("trunk"):
        if git("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode:
            raise SystemExit(
                fail(
                    f"refused: trunk: {name} in .xp/config.yml, but refs/heads/{name}"
                    f" does not exist — create it, or drop the key to release to git's default"
                )
            )
        return name
    head = git("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    if head.returncode == 0:
        return head.stdout.strip().rsplit("/", 1)[1]
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode == 0:
            return name
    raise SystemExit(fail("no main/master branch found and origin/HEAD unset"))


def origin_trunk_sha(trunk: str, *, fetch: bool = True) -> str | None:
    """Fetch the PR-mode ref; local mode guards the local trunk instead."""
    if not git("remote", check=False).stdout.strip():
        return None
    if fetch:
        git("fetch", "-q", "origin", trunk, check=False)
    r = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{trunk}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def marker_path(story_id: str, *, create: bool = True) -> Path:
    p = data_root() / "markers" / f"{story_id}.close.json"
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def review_authority_sections() -> list[tuple[str, str]]:
    paths = (
        ("JUDGMENT", Path(__file__).parent.parent / "JUDGMENT.md"),
        ("VALUES", Path(__file__).parent.parent / "VALUES.md"),
        ("Constraints", Path(".xp/constraints.md")),
        ("System context", Path(".xp/system.md")),
    )
    sections = []
    for title, path in paths:
        try:
            text = path.read_text()
        except FileNotFoundError:
            raise SystemExit(
                fail(
                    f"refused: required review authority {path} is MISSING — restore its"
                    " content, then run review again"
                )
            ) from None
        except OSError:
            raise SystemExit(
                fail(
                    f"refused: required review authority {path} is UNREADABLE — make it"
                    " readable, then run review again"
                )
            ) from None
        except UnicodeDecodeError as exc:
            raise SystemExit(
                fail(
                    f"refused: required review authority {path} is NOT UTF-8 ({exc}) —"
                    " rewrite it as UTF-8 text, then run review again"
                )
            ) from None
        if not text.strip():
            raise SystemExit(
                fail(
                    f"refused: required review authority {path} is EMPTY — restore its"
                    " content, then run review again"
                )
            )
        sections.append((title, text))
    return sections


def build_bundle(card: str, base: str, report: Path, prior: str = "", notice: str = "") -> str:
    import review  # function-local: spawn -> close -> review would close a cycle

    base_epoch = int(git("show", "-s", "--format=%ct", base).stdout.strip())
    executor_log = data_root() / "logs" / f"{card.split()[1]}-executor.log"
    sections = [
        ("Your charter", review.charter()),
        ("Your report", f"REPORT_PATH: {report}"),
        ("Story card", card),
        (
            "Execution evidence",
            f"EXECUTOR_LOG: {executor_log}\nRead it when present for implementation observations.",
        ),
        *([("Before you start", notice)] if notice else []),
        ("Earlier rounds of THIS review", prior or "none — you are round 1"),
        ("Cumulative diff", render_diff_range(base, "HEAD")),
        ("work.md entries filed during the story", work_entries_since(base_epoch) or "none"),
        *review_authority_sections(),
    ]
    return "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)


def _leg_checks(story_id: str, action: str, dry_run: bool = False) -> tuple[str, str, str]:
    if action != "salvage" and git("status", "--porcelain").stdout.strip():
        return "", "", "refused: working tree is dirty — commit or stash first"
    _noun, free_slug = leg(story_id)
    card, trunk = "", default_branch() if free_slug else integration_target()
    if not plan_path().exists():
        return "", "", f"refused: {missing_plan_refusal()}"
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return "", "", f"refused: {e.args[0]}"
    # A preview writes nothing and launches nothing, so a free card may be read
    # before spawn; the bracket never proves spawn — free.cmd_review's marker does.
    previewable = dry_run and free_slug and action == "review" and status in ("planned", "ready")
    if status != "in-progress" and not previewable:
        return "", "", f"refused: {story_id} is [{status}], {action} requires [in-progress]"
    try:
        verify_commands(story_id, card)
    except ValueError as e:
        return "", "", str(e)
    if action == "review" and status == "in-progress":
        sys.path.insert(0, str(Path(__file__).parent / "spawn"))
        import ready

        if problem := ready.drift(story_id, card):
            return "", "", problem
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in (trunk, default_branch()):
        return (
            "",
            "",
            f"refused: close from a story branch, not {branch} — a self-merge is a no-op"
            " that records the verdict nowhere",
        )
    return card, trunk, ""


def cmd_review(story_id: str, dry_run: bool = False, held=None, explicit=True) -> int:
    from review_launch import check_preflight
    from review_sequence import locked, run

    def action():
        card, trunk, error = _leg_checks(story_id, "review", dry_run)
        if error:
            return fail(error)
        if error := check_preflight(dry_run):
            return fail(error)
        return run(story_id, card, trunk, dry_run, explicit)

    return action() if dry_run else locked(story_id, action, held)


def cmd_land(story_id: str, merge_mode: str, dry_run: bool) -> int:
    sys.path[:0] = [str(Path(__file__).parent / d) for d in ("close", "spawn")]
    import land

    return land.cmd_land(story_id, merge_mode, dry_run)


def main() -> int:
    from xp import main as dispatch

    return dispatch(legacy=True)


if __name__ == "__main__":
    sys.exit(main())
