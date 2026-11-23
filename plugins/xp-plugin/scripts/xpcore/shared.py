"""GitHub publication plumbing shared by cards and finding records."""

import hashlib
import json
import re
import shutil
import socket
import subprocess

from xpcore import cards, gitx
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


def owner() -> str:
    machine = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:6]
    return f"{gitx.common_dir().parent.name}@{machine}"


def public_body(card: cards.Card) -> str:
    lines = [card.lines[0], f"Context: local to {owner()}"]
    ac = False
    for line in card.lines[1:]:
        if match := re.match(r"^([^\s:][^:]*):", line):
            ac = match[1] == "AC"
            if match[1] in {"Measure", "AC", "Files", "Acceptance", "Evidence", "Executor"}:
                lines.append(line)
        elif ac and (line.startswith(("- ", "* ", "  ", "\t")) or re.match(r"\d+\. ", line)):
            lines.append(line)
        else:
            ac = False
    return "\n".join([*lines, f"Published by: {owner()}"]) + "\n"


def cmd_publish(args) -> int:
    card = cards.find_card(args.id)
    body = public_body(card)
    _dependencies()
    _scan(card.title, body)
    _authenticate()
    try:
        if issue := card.field("Issue"):
            if not re.fullmatch(r"#\d+", issue):
                refuse("Issue must be #N; correct the local card")
            _gh("issue", "edit", issue[1:], "--body-file", "-", body=body)
            print(f"updated {issue}")
        else:
            ensure_label("card")
            url = _gh(
                "issue",
                "create",
                "--title",
                card.title,
                "--label",
                "card",
                "--body-file",
                "-",
                body=body,
            )
            match = re.search(r"/issues/(\d+)$", url)
            if not match:
                raise ValueError(f"expected issue URL, got {url!r}; inspect GitHub before retrying")
            cards.set_field(card.id, "Issue", f"#{match[1]}")
            print(url)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        refuse(f"GitHub publication failed: {exc}")
    return 0
