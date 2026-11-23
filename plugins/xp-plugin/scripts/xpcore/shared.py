"""GitHub publication plumbing shared by cards and finding records."""

import hashlib
import json
import re
import shutil
import socket
import subprocess

from xpcore import cards, gitx
from xpcore.config import refuse, repo_root, require_github_issues

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
    require_github_issues()
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


def issue_card(body: str) -> cards.Card:
    parsed = cards.read_cards(body)
    if (
        len(parsed) != 1
        or not body.startswith(parsed[0].lines[0])
        or parsed[0].status not in cards.STATUSES
    ):
        raise ValueError("issue body must contain one valid card")
    return parsed[0]


def cmd_claim(args) -> int:
    require_github_issues()
    if not re.fullmatch(r"[0-9]+", args.id):
        refuse("card claim needs an issue number")
    try:
        issue = json.loads(_gh("issue", "view", args.id, "--json", "body,labels"))
        labels = [label["name"] for label in issue["labels"]]
        if "card" not in labels:
            raise ValueError("issue needs the card label")
        card = issue_card(issue["body"])
        holder = f"clone:{owner()}"
        others = [label[6:] for label in labels if label.startswith("clone:") and label != holder]
        if others:
            refuse(f"card held by {', '.join(others)}; ask the holder to release it")
        ensure_label(holder)
        if holder not in labels:
            _gh("issue", "edit", args.id, "--add-label", holder)
        lines = [line for line in card.lines if not line.startswith("Issue:")]
        lines.append(f"Issue: #{args.id}")
        cards.mint_free(
            card.id, "\n".join(lines), "Free" if card.id.startswith("free-") else "Claimed"
        )
        print(f"claimed #{args.id}: {card.id} by {owner()}")
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        refuse(f"GitHub claim failed: {exc}")
    return 0
