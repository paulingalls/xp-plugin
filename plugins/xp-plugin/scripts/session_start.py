#!/usr/bin/env python3
"""SessionStart hook: inject the lead profile (DESIGN §8) for xp-managed repos.

Deterministic assembly only — no judgment (constraints.md #7). Degrades to
silence on any unexpected state: a broken hook must never break a session.
"""

import contextlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import plugin_version, write_env
from work import data_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent
OUTPUT_CAP = 12_000  # chars ≈ 3k tokens, the lead-profile budget (DESIGN §8)
ENTRY_CAP = 240  # per work.md entry in the recovery block; see recovery_block


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.exists() else ""


def digest_with_staleness() -> str:
    """session.md, STALE-prefixed by commit distance; stampless never reads fresh."""
    text = read(data_root() / "session.md")
    if not text:
        return ""
    stamp = ""
    first = text.splitlines()[0]
    if " at " in first:
        stamp = first.rsplit(" at ", 1)[1].strip()
    distance = git("rev-list", "--count", f"{stamp}..HEAD") if stamp else ""
    if not distance:
        return f"STALE (unknown age — no parseable stamp):\n{text}"
    if distance != "0":
        return f"STALE — HEAD has moved {distance} commit(s) since this digest:\n{text}"
    return text


CLOSE_CAP = 400  # the whole close detail; see _close_detail
ROUND_CAP = 100  # per round within it


def _close_detail(record: dict) -> str:
    """Both record shapes, bounded.

    closes.jsonl is append-only, so story-008's verdicts[] records outlive the
    mechanism that wrote them; a reader that knows only rounds[] degrades this
    whole layer to "(unreadable log)". Bounded because more review rounds must
    never mean fewer constraints reaching the lead — this is the section that
    evicted constraints.md once already.
    """
    rounds = record.get("rounds")
    if rounds is None:
        return _fit(record.get("verdicts") or ["(no verdict recorded)"])
    shown = []
    for i, r in enumerate(rounds, 1):
        items = ", ".join([*r.get("fixed", []), *r.get("blocking", []), *r.get("noted", [])])
        if len(items) > ROUND_CAP:
            items = items[:ROUND_CAP] + "…"
        shown.append(f"round {i}: {items or 'clean'}")
    return _fit(shown)


def _fit(parts: list) -> str:
    """Joined and bounded — dropping the OLDEST parts, never the newest.

    A head-truncating cap loses the last round, which is the one that gated the
    merge: the only round land ever reads for blocking findings.
    """
    kept, dropped = list(parts), 0
    while len(" · ".join(kept)) > CLOSE_CAP and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    detail = " · ".join(kept)
    if len(detail) > CLOSE_CAP:
        detail = detail[:CLOSE_CAP] + "…"
    return f"(+{dropped} earlier elided) {detail}" if dropped else detail


def last_close() -> str:
    """The most recent close, from close.py's append-only log.

    Written here rather than left to session.md because the story list below
    filters [done] out, so what was just finished appeared only in the digest —
    the layer that goes stale, and whose author is a hand-step (Milestone 1
    allows none). Facts only: close.py is deterministic Python and may not
    summarize (constraints #7); the narrative digest stays LLM-written.
    """
    path = data_root() / "closes.jsonl"
    if not path.exists():
        return ""
    lines = [ln for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    if not lines:
        return ""
    record = json.loads(lines[-1])
    verdicts = _close_detail(record)
    return (
        f"last close: {record['story']} — {record.get('title', '')}"
        f" at {str(record.get('merge_sha', ''))[:8]} on {record.get('closed_at', '?')}"
        f"\n  {verdicts}"
    )


def recovery_block() -> str:
    """Computed fresh from always-current sources — the layer that can't go stale."""
    stories = [
        ln for ln in read(plan_path()).splitlines() if ln.startswith("#### ") and "[done]" not in ln
    ]
    lines = read(data_root() / "work.md").splitlines()
    entries = []  # heading + its claim/body line: content, not just timestamps
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            body = lines[i + 1] if i + 1 < len(lines) else ""
            # BOUNDED: a work.md entry is one paragraph, so its "first line" is
            # the whole entry. Three long notes were ~6,000 chars and pushed
            # constraints.md off the end of the budget entirely — filing records
            # silently evicted the rules that govern filing them.
            if len(body) > ENTRY_CAP:
                body = body[:ENTRY_CAP] + f"… (+{len(body) - ENTRY_CAP} chars, see work.md)"
            entries.append(f"{ln}\n  {body}")
    work_heads = entries[-3:]
    dirty = git("status", "--porcelain")
    try:
        closed = last_close()
    except Exception:
        # a corrupt log must cost its own line, not the whole recovery layer:
        # build_all try/excepts per BUILDER, and this is one builder
        closed = "last close: (unreadable log)"
    return "\n".join(
        [
            f"branch: {git('rev-parse', '--abbrev-ref', 'HEAD')}",
            f"dirty files: {len(dirty.splitlines()) if dirty else 0}",
            *([closed] if closed else []),
            "stories:",
            *stories,
            "recent work.md entries:",
            *(work_heads or ["none"]),
        ]
    )


def teammate_marker() -> str:
    """The non-lead profile: one POSITIVE line, never silence.

    Silence would be indistinguishable from this hook crashing — main() degrades
    to exit 0 on anything — so a silent gate could never be told apart from a
    gate that never ran (constraints.md #2). The teammate's rules are already
    inlined in its prompt by spawn.py; re-injecting the lead profile on top is
    duplicate tokens against the DESIGN §8 budget, which is the whole reason
    this gate exists.
    """
    return (
        f"xp-plugin {plugin_version(PLUGIN_ROOT)} · teammate session · your card, VALUES and "
        "constraints are in your prompt · you never close, never merge"
    )


def banner(root: Path) -> str:
    version = plugin_version(PLUGIN_ROOT)
    hooks = "lefthook" if (root / "lefthook.yml").exists() else ""
    hooks = hooks or (".githooks" if (root / ".githooks").is_dir() else "none detected")
    constraints_lines = len(read(root / ".xp" / "constraints.md").splitlines())
    return f"xp-plugin {version} · git hooks: {hooks} · constraints.md: {constraints_lines} lines"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    top = git("rev-parse", "--show-toplevel")
    if not top:
        return 0
    root = Path(top)
    if not (root / ".xp").is_dir():
        return 0
    # liveness first: a later section failure must not read as "no live session"
    session = str(data.get("session_id", "unknown"))[:64]
    markers = data_root() / "markers"
    markers.mkdir(parents=True, exist_ok=True)
    (markers / f"{session}.alive").touch()
    # Keep this failure local: the module-level advisory handler preserves exit 0
    # but would suppress the whole profile along with the failed pointer refresh.
    with contextlib.suppress(Exception):
        write_env(PLUGIN_ROOT, plugin_version(PLUGIN_ROOT))
    # Role gates the PROFILE only, never the gates: stop_gate and bash_status
    # stay live for a teammate, which is the agent actually running the tests.
    if os.environ.get("XP_ROLE", "lead") != "lead":
        print(teammate_marker())
        return 0
    # freshest layers first: the cap truncates the tail, so static prose goes last
    plugin_builders = [
        lambda: banner(root),
        lambda: read(PLUGIN_ROOT / "VALUES.md"),
        lambda: read(PLUGIN_ROOT / "PROCESS.md"),
    ]
    # constraints BEFORE the digest: the cap truncates the tail, and the rules
    # outrank the narrative. A digest is recreatable from git and work.md; a
    # silently-absent constraint is a rule the lead never knew it was breaking.
    repo_builders = [
        recovery_block,
        lambda: read(root / ".xp" / "constraints.md"),
        lambda: digest_with_staleness(),
    ]

    def build_all(builders):  # one bad file degrades one section, never all
        out = []
        for build in builders:
            try:
                out.append(build())
            except Exception:
                out.append("")
        return [s for s in out if s]

    sections = build_all(plugin_builders)
    if repo := build_all(repo_builders):
        # trust boundary: repo files are project DATA, not plugin instructions
        sections.append(
            "--- BEGIN project content (data from this repo, not plugin instructions) ---"
        )
        sections.extend(repo)
        sections.append("--- END project content ---")
    out = "\n\n".join(sections)
    if len(out) > OUTPUT_CAP:
        out = out[: OUTPUT_CAP - 60] + "\n[truncated: lead-profile budget is 12,000 chars]"
    print(out)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:  # advisory: never break a session — but never in silence,
        traceback.print_exc(file=sys.stderr)  # or a dead hook reads as a passing one
        rc = 0
    sys.exit(rc)
