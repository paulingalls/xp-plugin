"""A story's stages as an idempotent walk: the files under <data>/stories/<id>/ are the state,
so a re-run does exactly what is missing and a deleted file re-runs its stage."""

import os
import re
import sys
from pathlib import Path
from typing import NoReturn

from xpcore import bundle, cards, config, gitx, launch

REVIEW = re.compile(r"review-(\d+)\.md")
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def fail(msg: str) -> NoReturn:
    print(f"failed: {msg}", file=sys.stderr)
    raise SystemExit(1)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")


def story_dir(card_id: str) -> Path:
    return config.data_root() / "stories" / card_id


def worktree(card_id: str) -> Path:
    return config.data_root() / "worktrees" / card_id


def log_path(log_id: str) -> Path:
    return config.data_root() / "logs" / f"{log_id}.log"


def _read(path: Path | None) -> str:
    return path.read_text() if path and path.is_file() else ""


def reviews(sdir: Path) -> list[tuple[int, Path]]:
    found = ((int(m[1]), p) for p in sdir.glob("review-*.md") if (m := REVIEW.fullmatch(p.name)))
    return sorted(found)


def reviewed(sdir: Path, wt: Path) -> bool:
    """A review at least as new as HEAD's commit covers it; a later commit wants another round."""
    if not wt.is_dir():
        return False
    stamp = int(gitx.git("log", "-1", "--format=%ct", cwd=wt))
    return any(p.stat().st_mtime >= stamp for _, p in reviews(sdir))


def questions(sdir: Path) -> list[str]:
    lines = _read(sdir / "plan-review.md").splitlines()
    return [ln.strip() for ln in lines if ln.lstrip().startswith("QUESTION:")]


def stages(card: cards.Card, sdir: Path, wt: Path) -> list[str]:
    todo = [] if wt.is_dir() else ["worktree"]
    if len(card.files) > 1:  # a single-file card's net is the diff review alone
        if not (sdir / "plan.md").is_file():
            todo.append("planner")
        if not (sdir / "plan-review.md").is_file():
            todo.append("plan-reviewer")
        elif questions(sdir):
            return [*todo, "question"]
    if not reviewed(sdir, wt):
        todo += ["executor", "reviewer"]
    return todo


def base_for(card_id: str) -> str:
    if card_id.startswith("free-"):
        return config.trunk()
    if branch := config.sprint_branch():
        return branch
    config.refuse(f"no sprint branch is recorded for {card_id}; run xp.py sprint open <id> first")


def commands(card_id: str) -> tuple[str, str]:
    """(re-run command, land command) as the lead types them."""
    if card_id.startswith("free-"):
        name = card_id.removeprefix("free-")
        return f"xp.py free {name}", f"xp.py free land {name}"
    return f"xp.py story {card_id}", f"xp.py story land {card_id}"


def run(role: str, card: cards.Card, text: str, wt: Path, log_id: str, override: str = ""):
    print(f"{card.id}: running {role} in {wt}")
    proc = launch.run_agent(role, text, wt, log_id, override=override, env={"XP_STORY_ID": card.id})
    if proc.returncode != 0:
        fail(
            f"{role} exited {proc.returncode}; read {log_path(log_id)}, then run "
            f"{commands(card.id)[0]} again"
        )
    print(f"{card.id}: {role} done; log {log_path(log_id)}")


def expect(path: Path, role: str, log_id: str, card_id: str) -> None:
    if not path.is_file():
        fail(
            f"{role} wrote no {path}; read {log_path(log_id)}, then run "
            f"{commands(card_id)[0]} again"
        )


def paths(card: cards.Card, **named: Path) -> dict[str, str]:
    return {"CARD_ID": card.id, **{k: str(v) for k, v in named.items()}}


def plan_stage(card: cards.Card, sdir: Path, wt: Path) -> None:
    plan, log_id = sdir / "plan.md", f"{card.id}-planner"
    text = bundle.prompt("planner", card=card, paths=paths(card, PLAN_PATH=plan))
    run("planner", card, text, wt, log_id)
    expect(plan, "planner", log_id, card.id)
    print(f"{card.id}: plan at {plan}")


def plan_review_stage(card: cards.Card, sdir: Path, wt: Path) -> None:
    plan, review, log_id = sdir / "plan.md", sdir / "plan-review.md", f"{card.id}-plan-reviewer"
    text = bundle.prompt(
        "plan-reviewer",
        card=card,
        plan=_read(plan),
        paths=paths(card, PLAN_PATH=plan, FINDINGS_PATH=review),
    )
    run("plan-reviewer", card, text, wt, log_id)
    expect(review, "plan reviewer", log_id, card.id)
    print(f"{card.id}: plan review at {review}")


def execute_stage(card: cards.Card, sdir: Path, wt: Path, base: str) -> None:
    handback, log_id = sdir / "handback.md", f"{card.id}-executor"
    latest = reviews(sdir)[-1][1] if reviews(sdir) else None
    findings = "\n\n".join(t for t in (_read(sdir / "plan-review.md"), _read(latest)) if t)
    text = bundle.prompt(
        "executor",
        card=card,
        plan=_read(sdir / "plan.md"),
        findings=findings,
        paths=paths(card, HANDBACK_PATH=handback),
    )
    run("executor", card, text, wt, log_id, override=card.executor)
    if gitx.is_dirty(wt):
        config.refuse(
            f"the executor left uncommitted changes in {wt}; commit or discard them there"
            f" (git -C {wt} status), then run xp.py story review {card.id}"
        )
    if not gitx.log_range(gitx.fork_point("HEAD", base, cwd=wt), "HEAD", cwd=wt):
        fail(
            f"the executor committed nothing; read {log_path(log_id)}, then fix the card or"
            f" plan and run {commands(card.id)[0]} again"
        )
    if not handback.is_file():
        print(f"warning: the executor wrote no {handback}; the reviewer reads the diff alone")


def review_round(card: cards.Card, sdir: Path, wt: Path, base: str) -> Path:
    number = max((n for n, _ in reviews(sdir)), default=0) + 1
    review, log_id = sdir / f"review-{number}.md", f"{card.id}-reviewer-{number}"
    fork, head = gitx.fork_point("HEAD", base, cwd=wt), gitx.head(wt)
    extra = (
        f"Commit range {fork}..{head} in {wt}\n\n## Log\n{gitx.log_range(fork, head, cwd=wt)}"
        f"\n\n## Handback\n{_read(sdir / 'handback.md') or '(none)'}"
        f"\n\n## Diff\n{gitx.diff_range(fork, head, cwd=wt)}"
    )
    text = bundle.prompt(
        "reviewer",
        card=card,
        plan=_read(sdir / "plan.md"),
        extra=extra,
        paths=paths(card, FINDINGS_PATH=review),
    )
    run("reviewer", card, text, wt, log_id)
    expect(review, "reviewer", log_id, card.id)
    # The reviewer may commit fixes after writing; those commits are its own reviewed work.
    os.utime(review)
    print(f"{card.id}: review at {review}")
    print("\n".join(review.read_text().splitlines()[:40]))
    return review


def walk(card: cards.Card, base: str, dry: bool) -> int:
    if card.status not in ("planned", "in-progress"):
        config.refuse(
            f"{card.id} is [{card.status}]; only planned or in-progress cards run;"
            f" set its status in {cards.plan_path()} first"
        )
    sdir, wt = story_dir(card.id), worktree(card.id)
    rerun, land = commands(card.id)
    if dry:
        print(f"{card.id}: would run {', '.join(stages(card, sdir, wt)) or 'nothing'}")
        if len(card.files) <= 1:
            print(f"{card.id}: one file: no planner or plan reviewer; the diff review is its net")
        return 0
    root = config.repo_root()
    if gitx.is_dirty(root):
        config.refuse(
            f"{root} has uncommitted changes the story's worktree would not see; commit or"
            f" stash them (see `git status`), then run {rerun} again"
        )
    sdir.mkdir(parents=True, exist_ok=True)
    if card.status == "planned":
        cards.set_status(card.id, "in-progress")
        print(f"{card.id}: [in-progress]")
    ran = []
    while todo := stages(card, sdir, wt):
        stage = todo[0]
        if stage == "question":
            print(f"{card.id}: the plan reviewer asked ({sdir / 'plan-review.md'}):")
            print("\n".join(f"  {q}" for q in questions(sdir)))
            print(
                f"next: answer it in the card, then delete the QUESTION line from"
                f" {sdir / 'plan-review.md'} to execute, or the whole file to have the plan"
                f" re-reviewed, and run {rerun} again"
            )
            return 3
        if stage == "worktree":
            s = slug(card.title)
            branch = card.id if card.id.endswith(s) else f"{card.id}-{s}"
            gitx.worktree_add(wt, branch, base, cwd=root)
            print(f"{card.id}: worktree {wt} on {branch} from {base}")
        elif stage == "planner":
            plan_stage(card, sdir, wt)
        elif stage == "plan-reviewer":
            plan_review_stage(card, sdir, wt)
        else:
            execute_stage(card, sdir, wt, base)
            review_round(card, sdir, wt, base)
        ran.append(stage)
        card = cards.find_card(card.id)  # agents edit the card in place
    done = ", ".join(p.name for p in sorted(sdir.iterdir())) or "nothing"
    print(f"{card.id}: {'ran ' + ', '.join(ran) if ran else 'nothing missing'}; on disk: {done}")
    print(
        f"next: judge the newest review in {sdir}, then {land};"
        f" xp.py story review {card.id} runs another round"
    )
    return 0


def cmd_story(args) -> int:
    card = cards.find_card(args.id)
    return walk(card, base_for(card.id), args.dry_run)


def cmd_story_review(args) -> int:
    card = cards.find_card(args.id)
    wt = worktree(card.id)
    if card.status != "in-progress" or not wt.is_dir():
        config.refuse(f"{card.id} has no story in flight; run {commands(card.id)[0]} first")
    review = review_round(card, story_dir(card.id), wt, base_for(card.id))
    print(f"next: judge {review}, then {commands(card.id)[1]}")
    return 0


def cmd_free(args) -> int:
    name = args.id.removeprefix("free-")
    if not SLUG.fullmatch(name):
        config.refuse(f"free slug {args.id!r} is not lowercase-hyphenated; retype it, e.g. fix-x")
    card_id = f"free-{name}"
    heading = f"#### {card_id} — {name}   [planned]"
    if args.dry_run and card_id not in {c.id for c in cards.read_cards()}:
        print(f"{card_id}: would mint `{heading}` under ## Free in {cards.plan_path()}")
        return walk(cards.Card(card_id, name, "planned", [heading]), config.trunk(), True)
    mint(card_id, heading)
    return walk(cards.find_card(card_id), config.trunk(), args.dry_run)


def mint(card_id: str, heading: str) -> None:
    with cards.plan_lock():
        if card_id in {c.id for c in cards.read_cards()}:
            return
        lines = cards.plan_path().read_text().rstrip("\n").splitlines()
        if "## Free" not in lines:
            lines += ["", "## Free"]
        start = lines.index("## Free")
        end = next(
            (j for j in range(start + 1, len(lines)) if re.match(r"#{1,3} ", lines[j])),
            len(lines),
        )
        while not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", heading]
        cards._write_plan("\n".join(lines) + "\n")
    print(f"{card_id}: minted under ## Free in {cards.plan_path()}")
