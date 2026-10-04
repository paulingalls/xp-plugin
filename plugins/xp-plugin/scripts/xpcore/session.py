"""SessionStart injection and the recovery block a lead reads after a restart or compaction."""

import json
import os
import sys
import traceback
from pathlib import Path

from xpcore import cards, records
from xpcore.config import data_root, plugin_root, sprint_branch
from xpcore.gitx import git

# Codex keeps only the first 10,000 bytes of hook output; 500 spare keeps the fence intact.
BUDGET = 9_500
BEGIN, END = "--- BEGIN project content ---", "--- END project content ---"
PROSE = ("VALUES.md", "JUDGMENT.md", "PROCESS.md")
STAGES = ("plan.md", "plan-review.md", "handback.md")


def _version() -> str:
    try:
        manifest = plugin_root() / ".claude-plugin" / "plugin.json"
        return str(json.loads(manifest.read_text())["version"])
    except (OSError, ValueError, KeyError):
        return "unknown"


def recover_command() -> str:
    return f"python3 {plugin_root() / 'scripts' / 'xp.py'} recover"


def _repo() -> Path | None:
    top = git("rev-parse", "--show-toplevel", check=False)
    return Path(top) if top else None


def _banner(repo: Path | None) -> str:
    data = data_root() if repo or os.environ.get("XP_DATA") else "none outside a git repo"
    return f"xp-plugin {_version()} · recover: {recover_command()} · data: {data}\n"


def _fit(constraints: str, room: int) -> str:
    raw = constraints.encode()
    if len(raw) <= room:
        return constraints
    notice = "\n[constraints.md truncated at {} bytes; read the file]\n"
    keep = max(0, room - len(notice.format(room).encode()))
    kept = raw[:keep].decode(errors="ignore")
    return kept + notice.format(len(kept.encode()))


def injection(repo: Path | None) -> str:
    head = _banner(repo)
    for name in PROSE:
        path = plugin_root() / name
        head += "\n" + (path.read_text() if path.is_file() else f"[{name} missing]\n")
    constraints = repo / ".xp" / "constraints.md" if repo else None
    if not repo or not (repo / ".xp").is_dir():
        return head + "\nno .xp/ here: run xp.py setup\n"
    if not constraints.is_file():
        return head
    # The project's file is data, never instructions: it must not close the fence itself.
    text = constraints.read_text(errors="replace").replace(END, "[fence marker removed]")
    shell = f"\n{BEGIN}\n" + "{}" + f"\n{END}\n"
    room = BUDGET - len(head.encode()) - len(shell.format("").encode())
    return head + shell.format(_fit(text, max(0, room)))


def cmd_session_start(args) -> int:
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()  # the hook's JSON payload; drained so the writer never blocks
    except (OSError, ValueError, AttributeError):
        pass
    try:
        sys.stdout.write(injection(_repo()))
    except (Exception, SystemExit):
        # A non-zero SessionStart reads as a dead hook, never as a refusal anyone acts on.
        traceback.print_exc()
    return 0


def _stage_files(card_id: str) -> str:
    story = data_root() / "stories" / card_id
    found = [name for name in STAGES if (story / name).is_file()]
    found += sorted(p.name for p in story.glob("review-*.md"))
    return ", ".join(found) or "none yet"


def cmd_recover(args) -> int:
    digest = data_root() / "session.md"
    print(digest.read_text().rstrip() if digest.is_file() else "no session digest yet")
    print("\n## cards")
    if not cards.plan_path().is_file():
        print(f"no plan at {cards.plan_path()}")
    else:
        live = [c for c in cards.read_cards() if c.status not in ("done", "retired")]
        for card in live:
            print(f"{card.id} — {card.title} [{card.status}]")
            if card.status == "in-progress":
                print(f"  stages: {_stage_files(card.id)}")
        if not live:
            print("none open")
    print("\n## open records")
    print("\n".join(records.open_records()) or "none")
    print("\n## sprint")
    print(sprint_branch() or "none open")
    return 0
