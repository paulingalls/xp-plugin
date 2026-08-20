#!/usr/bin/env python3
"""SessionStart hook: inject the lead profile (DESIGN §8) for xp-managed repos.

Deterministic assembly only — no judgment (constraints.md #7). Degrades to
silence on any unexpected state: a broken hook must never break a session.
"""

import json
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
    return path.read_text() if path.exists() else ""


def digest_with_staleness(root: Path) -> str:
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
    stories = [ln for ln in read(root / ".xp" / "plan.md").splitlines() if ln.startswith("#### ")]
    work_heads = [ln for ln in read(data_root() / "work.md").splitlines() if ln.startswith("## ")][
        -3:
    ]
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


def banner(root: Path) -> str:
    manifest = read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
    version = json.loads(manifest).get("version", "unknown") if manifest else "unknown"
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
    sections = [
        banner(root),
        read(PLUGIN_ROOT / "VALUES.md"),
        read(PLUGIN_ROOT / "PROCESS.md"),
        read(root / ".xp" / "constraints.md"),
        digest_with_staleness(root),
        recovery_block(root),
    ]
    out = "\n\n".join(s for s in sections if s)
    if len(out) > OUTPUT_CAP:
        out = out[: OUTPUT_CAP - 60] + "\n[truncated: lead-profile budget is 12,000 chars]"
    print(out)
    session = str(data.get("session_id", "unknown"))[:64]
    markers = data_root() / "markers"
    markers.mkdir(parents=True, exist_ok=True)
    (markers / f"{session}.alive").touch()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # degrade to silence, never break a session
