"""Shared issue records, local notes and legacy resolutions; each falsifier run once."""

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from xpcore.config import data_root, refuse, repo_root
from xpcore.gitx import git

OUTPUT_CAP = 2_000
TIMEOUT = 600
GH_TIMEOUT = 30
HEADING = re.compile(r"^## (bug|debt|note|resolved) (\S+) \S+$")


def work_path() -> Path:
    return data_root() / "work.md"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_line(text: str) -> str:
    """A field is one line, so free text can never start a `## ` heading of its own."""
    return " ".join(str(text).split())


def _falsify(command: str) -> tuple[int, str]:
    """A shell line, run once from the repo root, now; the plugin never reruns the set."""
    if not command.strip():
        refuse("the falsifier is empty; pass a command whose exit code proves the claim")
    try:
        proc = subprocess.run(
            ["sh", "-c", command],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        refuse(f"falsifier ran past {TIMEOUT}s; pass a narrower command")
    if proc.returncode in (126, 127):
        # A typo is not a red: the shell says not found or not executable.
        refuse(f"falsifier exited {proc.returncode} (not found or not executable); fix it")
    output = (proc.stdout + proc.stderr)[-OUTPUT_CAP:]
    # Indented, so the falsifier's own output cannot mint a record heading.
    return proc.returncode, "\n".join(f"    {ln}" for ln in output.splitlines())


def _append(kind: str, ident: str, ts: str, body: list[str]) -> None:
    path = work_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        handle.write("\n".join([f"## {kind} {ident} {ts}", *body]) + "\n\n")
    print(f"{kind} {ident} recorded in {path}")


def _dependencies() -> None:
    if not shutil.which("gh"):
        refuse("install gh and authenticate with gh auth login; records require GitHub")
    if not shutil.which("gitleaks"):
        refuse("install gitleaks; records require secret scanning")


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


def _file(kind: str, args, extra: list[str]) -> int:
    claim = _one_line(args.claim)
    if not claim:
        refuse(f"a {kind} needs a --claim; say what is wrong")
    _dependencies()
    rc, output = _falsify(args.falsifier)
    if kind == "bug" and rc == 0:
        refuse(
            "the falsifier exited 0 (green), so it shows nothing broken; file as debt"
            " (xp.py debt), or pass a falsifier that fails while the bug exists"
        )
    if kind == "debt" and rc != 0:
        refuse(
            f"the falsifier exited {rc} (red), so this is a defect; file as bug"
            " (xp.py bug), or pass a falsifier that passes on today's code"
        )
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    body = [f"Claim: {claim}", f"Falsifier: {_one_line(args.falsifier)}"]
    body += [
        f"Files: {_one_line(args.files)}",
        *extra,
        f"Filer: {common.parent.name}",
        f"Falsifier rc: {rc}",
        output,
    ]
    payload = "\n".join(body)
    query = " ".join(re.findall(r"[a-zA-Z0-9]+", claim)[:8])
    _scan(claim, payload, query)
    _authenticate()
    print("Open issues matching claim terms:")
    try:
        print(_gh("issue", "list", "--state", "open", "--search", query) or "none")
    except RuntimeError as exc:
        print(f"advisory search unavailable: {exc}")
    try:
        labels = json.loads(_gh("label", "list", "--search", kind, "--json", "name"))
        if not any(label["name"] == kind for label in labels):
            _gh("label", "create", kind)
        print(
            _gh(
                "issue",
                "create",
                "--title",
                claim,
                "--label",
                kind,
                "--body-file",
                "-",
                body=payload,
            )
        )
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        refuse(f"GitHub filing failed: {exc}; fix gh access and retry")
    return 0


def cmd_bug(args) -> int:
    return _file("bug", args, [])


def cmd_debt(args) -> int:
    big, important = _one_line(args.too_big), _one_line(args.too_important)
    if not big or not important:
        refuse("debt must clear both bars; pass --too-big and --too-important with reasons")
    return _file("debt", args, [f"Too big: {big}", f"Too important: {important}"])


def cmd_note(args) -> int:
    text = str(args.text).strip()
    if not text:
        refuse("the note is empty; pass the text to record")
    ts = _stamp()
    ident = hashlib.sha256(f"note{ts}{text}".encode()).hexdigest()[:8]
    _append("note", ident, ts, [re.sub(r"^(?=#)", " ", text, flags=re.M)])
    return 0


def _records() -> tuple[dict[str, tuple[str, str]], set[str]]:
    """({id: (kind, claim)} for every bug and debt, {ids resolved})."""
    path = work_path()
    text = path.read_text(errors="replace") if path.is_file() else ""
    filed: dict[str, tuple[str, str]] = {}
    resolved: set[str] = set()
    current = ""
    for line in text.splitlines():
        if match := HEADING.match(line):
            kind, ident = match.groups()
            current = ident if kind in ("bug", "debt") else ""
            if kind == "resolved":
                resolved.add(ident)
            elif current:
                filed[ident] = (kind, "")
        elif current and line.startswith("Claim: ") and not filed[current][1]:
            filed[current] = (filed[current][0], line.removeprefix("Claim: "))
    return filed, resolved


def open_records() -> list[str]:
    filed, resolved = _records()
    return [
        f"{kind} {ident} — {claim[:100]}"
        for ident, (kind, claim) in filed.items()
        if ident not in resolved
    ]


def cmd_resolve(args) -> int:
    ref = args.ref.strip()
    numeric = ref.isascii() and ref.isdigit()
    if numeric:
        _dependencies()
    filed, resolved = _records()
    if not numeric and ref not in filed:
        refuse(f"no bug or debt {ref!r} in {work_path()}; run xp.py recover for the open ids")
    if not numeric and ref in resolved:
        refuse(f"{ref} is already resolved; nothing to do")
    rc, output = _falsify(args.falsifier)
    if rc != 0:
        refuse(
            f"the replacement falsifier exited {rc} (red), so {ref} still holds;"
            " fix it first, or pass the command that proves it fixed"
        )
    body = [f"Falsifier: {_one_line(args.falsifier)}", f"Falsifier rc: {rc}", output]
    if numeric:
        comment = "\n".join(body)
        _scan(comment)
        _authenticate()
        try:
            print(_gh("issue", "close", ref, "--comment", comment))
        except RuntimeError as exc:
            refuse(f"GitHub close failed: {exc}; fix gh access and retry")
    else:
        _append("resolved", ref, _stamp(), body)
    return 0


def issue_records() -> list[str]:
    if not git("rev-parse", "--show-toplevel", check=False):
        return ["GitHub open records unavailable: not inside a git repository"]
    try:
        issues = json.loads(
            _gh(
                "issue",
                "list",
                "--state",
                "open",
                "--search",
                "label:bug,debt",
                "--json",
                "number,title,labels",
                "--limit",
                "100",
            )
        )
        rows = []
        for issue in issues:
            labels = ",".join(
                label["name"] for label in issue["labels"] if label["name"] in ("bug", "debt")
            )
            rows.append(f"#{issue['number']} {labels} — {issue['title']}")
        if len(issues) == 100:
            rows.append("first 100 shown; gh issue list --label bug|debt for the rest")
        return rows
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return [f"GitHub open records unavailable: {exc}"]
