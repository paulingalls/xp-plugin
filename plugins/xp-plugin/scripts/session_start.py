#!/usr/bin/env python3
"""SessionStart hook: inject the lead profile (DESIGN §8) for xp-managed repos.

Deterministic assembly only — no judgment (constraints.md #7). Degrades to
silence on any unexpected state: a broken hook must never break a session.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import data_root

PLUGIN_ROOT = Path(__file__).parent.parent
OUTPUT_CAP = 12_000  # chars ≈ 3k tokens, the lead-profile budget (DESIGN §8)


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


def recovery_block(root: Path) -> str:
    """Computed fresh from always-current sources — the layer that can't go stale."""
    stories = [
        ln
        for ln in read(root / ".xp" / "plan.md").splitlines()
        if ln.startswith("#### ") and "[done]" not in ln
    ]
    lines = read(data_root() / "work.md").splitlines()
    entries = []  # heading + its claim/body line: content, not just timestamps
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            body = lines[i + 1] if i + 1 < len(lines) else ""
            entries.append(f"{ln}\n  {body}")
    work_heads = entries[-3:]
    dirty = git("status", "--porcelain")
    return "\n".join(
        [
            f"branch: {git('rev-parse', '--abbrev-ref', 'HEAD')}",
            f"dirty files: {len(dirty.splitlines()) if dirty else 0}",
            "stories:",
            *stories,
            "recent work.md entries:",
            *(work_heads or ["none"]),
        ]
    )


def plugin_version() -> str:
    manifest = read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
    return json.loads(manifest).get("version", "unknown") if manifest else "unknown"


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
        f"xp-plugin {plugin_version()} · teammate session · your card, VALUES and "
        "constraints are in your prompt · you never close, never merge"
    )


def banner(root: Path) -> str:
    version = plugin_version()
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
    repo_builders = [
        lambda: recovery_block(root),
        lambda: digest_with_staleness(),
        lambda: read(root / ".xp" / "constraints.md"),
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
        sys.exit(main())
    except (Exception, SystemExit):
        sys.exit(0)  # degrade to silence (SystemExit included), never break a session
