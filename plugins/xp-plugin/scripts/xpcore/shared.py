"""GitHub publication plumbing shared by cards and finding records."""

import json
import shutil
import subprocess

from xpcore.config import refuse, repo_root

GH_TIMEOUT = 30


def _dependencies() -> None:
    if not shutil.which("gh"):
        refuse("install gh and authenticate with gh auth login; GitHub publication requires GitHub")
    if not shutil.which("gitleaks"):
        refuse("install gitleaks; GitHub publication requires secret scanning")


def _scan(*texts: str) -> None:
    for text in texts:
        try:
            proc = subprocess.run(
                ["gitleaks", "stdin", "--no-banner", "--redact"],
                input=text,
                cwd=repo_root(),
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            refuse("gitleaks could not scan the payload; nothing sent to GitHub")
        if proc.returncode:
            refuse("gitleaks refused the payload; inspect it locally before filing")


def _gh(*args: str, body: str | None = None) -> str:
    try:
        proc = subprocess.run(
            ["gh", *args],
            input=body if body is not None else "",
            cwd=repo_root(),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gh timed out") from exc
    except OSError as exc:
        raise RuntimeError(f"gh unavailable: {exc}") from exc
    if proc.returncode:
        raise RuntimeError((proc.stderr + proc.stdout).strip() or f"gh exited {proc.returncode}")
    return proc.stdout.strip()


def _authenticate() -> None:
    try:
        _gh("auth", "status")
    except RuntimeError as exc:
        refuse(f"{exc}; run gh auth login")


def ensure_label(name: str) -> None:
    labels = json.loads(_gh("label", "list", "--search", name, "--json", "name") or "[]")
    if not any(label["name"] == name for label in labels):
        _gh("label", "create", name)
