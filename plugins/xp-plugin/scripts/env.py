#!/usr/bin/env python3
"""The data root and its env.json: where a project's runtime state lives, and
which plugin install put it there.

Separate from work.py because anything the plugin did NOT spawn — a codex-native
lead's scripts, a hook outside a spawn — starts here: it can derive the data root
from git alone, and everything else it needs is recorded in it.
"""

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

# HERE because env.py is the only shipped module free of the `str | None` 3.9 dies on.
if sys.version_info < (3, 11):
    raise SystemExit(
        f"refused: xp-plugin needs Python 3.11+, and this is"
        f" {sys.version_info[0]}.{sys.version_info[1]}"
        f" ({sys.executable}). Point `python3` at a newer interpreter."
    )


def run_hook(main) -> None:
    if sys.stdin.isatty():
        print(f"{Path(sys.argv[0]).name} is a hook; invoke it with a JSON payload on stdin.")
        raise SystemExit(0)
    try:
        rc = main(json.load(sys.stdin))
    except Exception:  # advisory: never break a session — but never in silence,
        traceback.print_exc(file=sys.stderr)  # or a dead hook reads as a passing one
        rc = 0
    raise SystemExit(rc)


def refuse_direct_invocation(invocation: str) -> None:
    print(
        f"refused: {Path(sys.argv[0]).name} is an internal module; use `{invocation}`",
        file=sys.stderr,
    )
    raise SystemExit(2)


def data_root() -> Path:
    if env := os.environ.get("XP_DATA"):
        return Path(env)
    proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if proc.returncode != 0:
        print("not inside a git repository and XP_DATA is unset", file=sys.stderr)
        raise SystemExit(2)
    common = proc.stdout.strip()
    project_id = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:12]
    return Path.home() / ".xp" / "data" / project_id


def env_path() -> Path:
    return data_root() / "env.json"


def sprint_branch_path() -> Path:
    return data_root() / "sprint_branch"


def sprint_branch() -> str:
    path = sprint_branch_path()
    try:
        branch = path.read_text().strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        _refuse_env(f"{path} is not readable ({exc}) — repair or remove it.")
    if not branch:
        _refuse_env(f"{path} is empty — remove it, then open the sprint again.")
    return branch


def record_sprint_branch(branch: str) -> None:
    path = sprint_branch_path()
    if recorded := sprint_branch():
        if recorded != branch:
            _refuse_env(
                f"{path} records {recorded}, not {branch} — clear it only after that sprint lands"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(branch + "\n")


def clear_sprint_branch() -> None:
    sprint_branch_path().unlink(missing_ok=True)


def plugin_version(root: Path) -> str:
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    except (OSError, ValueError):
        return "unknown"
    if not isinstance(manifest, dict):
        return "unknown"
    version = manifest.get("version")
    return version if isinstance(version, str) and version else "unknown"


def write_env(root: Path, version: str) -> None:
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text())
    except FileNotFoundError:
        current = {}
    current["plugin_root"] = str(root)
    current["plugin_version"] = version
    # Per-writer temp name: a lead session and a spawned teammate's SessionStart
    # share one data root, and one temp name turns last-writer-wins into a torn file.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


REFRESH = (
    "refresh it by starting a session on the harness whose install you want"
    " — SessionStart rewrites both entries"
)


def _refuse_env(reason: str) -> None:
    print(f"refused: {reason}", file=sys.stderr)
    raise SystemExit(2)


def plugin_root() -> Path:
    """The INSTALLED plugin root, for anything with no ${CLAUDE_PLUGIN_ROOT} and no
    Path(__file__) inside the plugin — a codex lead's scripts, hooks outside a spawn.

    Refuses rather than guessing: the codex cache is version-keyed, so a moved
    install is the EXPECTED state and a fallback would silently run another
    version's code. One case stays invisible here and is bounded by the
    every-session refresh instead — a KEPT old cache directory whose manifest
    still matches the recorded version reads as live, because it is self-consistent.
    """
    path = env_path()
    try:
        recorded = json.loads(path.read_text())
    except FileNotFoundError:
        recorded = {}
    except (OSError, ValueError) as exc:
        _refuse_env(
            f"{path} is not a readable env.json ({exc}) — repair or remove it, then {REFRESH}."
        )
    if not isinstance(recorded, dict):
        _refuse_env(f"{path} must contain a JSON object — repair or remove it, then {REFRESH}.")
    if not recorded.get("plugin_root"):
        _refuse_env(
            f"no plugin root recorded in {path} — setup.py seeds it at scaffold and every"
            f" SessionStart refreshes it. Run the installed plugin's scripts/setup.py in"
            f" this repo, or {REFRESH}."
        )
    raw_root = recorded["plugin_root"]
    if not isinstance(raw_root, str):
        _refuse_env(f"{path} records invalid plugin_root {raw_root!r} — {REFRESH}.")
    root = Path(raw_root)
    if not root.is_dir():
        _refuse_env(f"{path} records plugin_root {root}, and it is gone — {REFRESH}.")
    found = plugin_version(root)
    if found == "unknown":
        _refuse_env(
            f"{path} records plugin_root {root}, which has no readable"
            f" .claude-plugin/plugin.json — that is not an install. {REFRESH}."
        )
    if found != recorded.get("plugin_version"):
        _refuse_env(
            f"{path} records plugin_version {recorded.get('plugin_version')} but {root}"
            f" is {found} — the pointer and the install disagree. {REFRESH}."
        )
    return root


if __name__ == "__main__":
    refuse_direct_invocation("work.py env")
