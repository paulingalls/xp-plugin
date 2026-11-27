"""Lesson issue publication, snapshots and ledger receipts."""

import fcntl
import json
import re
import sys
import tempfile
from pathlib import Path

from xpcore import config, gitx, shared

RECORD = re.compile(
    r"- (L[1-9]\d*) \[(sighting|proposed|applied|dropped)\] (.+?) \(seen: ([^)]+)\) -> (.+)"
)


def parse_ledger(text, malformed=None):
    records = {}
    for index, line in enumerate(text.splitlines()):
        if not re.match(r"- L(?:\d|\S* \[)", line):
            continue
        match = RECORD.fullmatch(line)
        if not match or match[1] in records:
            if malformed is None:
                raise ValueError(f"malformed or duplicate lesson: {line}")
            malformed.append(line)
            continue
        records[match[1]] = [index, match[2], match[3], match[4].split(", "), match[5]]
    return records


def issue_number(record):
    match = re.search(r"; #([1-9]\d*)$", record[4])
    return match[1] if match else ""


def origin():
    url = gitx.git("remote", "get-url", "origin", check=False)
    if not url:
        raise ValueError("origin remote is missing")
    return url


class ReceiptError(ValueError):
    pass


def file_pending(path):
    if not path.exists():
        return
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        text = path.read_text()
        for key, record in parse_ledger(text).items():
            if record[1] != "proposed" or issue_number(record):
                continue
            try:
                repo = origin()
                title = record[2]
                body = f"{key}: {title}\n\n{record[4]}\n"
                shared._dependencies()
                shared._scan(title, body)
                shared._authenticate()
                shared._gh("label", "create", "lesson", "--force", "-R", repo)
                url = shared._gh(
                    "issue",
                    "create",
                    "--title",
                    title,
                    "--label",
                    "lesson",
                    "--body-file",
                    "-",
                    "-R",
                    repo,
                    body=body,
                )
                match = re.search(r"/issues/([1-9]\d*)$", url)
                if not match:
                    raise ReceiptError(
                        f"issue created but number unavailable: {url}; "
                        "inspect GitHub and repair ledger"
                    )
                lines = text.splitlines(keepends=True)
                index = record[0]
                lines[index] = lines[index].rstrip("\r\n") + f"; #{match[1]}\n"
                try:
                    atomic(path, "".join(lines))
                except OSError as exc:
                    raise ReceiptError(
                        f"created {url}; manually add ; #{match[1]} to {key} in {path}: {exc}"
                    ) from exc
                text = "".join(lines)
                print(url)
            except (Exception, SystemExit):
                print(f"Lesson {key} filing failed in {path}", file=sys.stderr)
                raise


def atomic(path, text):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        staged.write_text(text)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def synchronize(path, snapshot):
    if not config.github_issues() or not any(
        r[1] == "proposed" and issue_number(r) for r in parse_ledger(snapshot).values()
    ):
        return snapshot
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = path.read_text()
        lines = snapshot.splitlines(keepends=True)
        for key, record in parse_ledger(snapshot).items():
            number = issue_number(record)
            if record[1] != "proposed" or not number:
                continue
            try:
                issue = json.loads(
                    shared._gh(
                        "issue", "view", number, "--json", "state,stateReason", "-R", origin()
                    )
                )
                if not isinstance(issue, dict) or not {"state", "stateReason"} <= issue.keys():
                    raise ValueError("missing issue state/stateReason")
                if issue["state"] == "OPEN":
                    continue
                if issue["state"] != "CLOSED" or issue["stateReason"] not in (
                    "COMPLETED",
                    "NOT_PLANNED",
                ):
                    raise ValueError(f"unsupported issue disposition: {issue}")
                status = "applied" if issue["stateReason"] == "COMPLETED" else "dropped"
                index = record[0]
                lines[index] = lines[index].replace("[proposed]", f"[{status}]", 1)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                print(f"Lesson {key} #{number} lookup failed; unchanged: {exc}", file=sys.stderr)
        updated = "".join(lines)
        if updated != snapshot:
            atomic(path, updated)
        return updated


def issue_input():
    try:
        repo = json.loads(shared._gh("repo", "view", origin(), "--json", "nameWithOwner"))
        owner, name = repo["nameWithOwner"].split("/")
        query = """query($owner:String!, $name:String!, $endCursor:String) {
repository(owner:$owner, name:$name) {
issues(first:100, after:$endCursor, states:[OPEN,CLOSED], labels:["bug","debt","lesson"]) {
nodes { number title state stateReason closedAt labels(first:100) { nodes { name } } }
pageInfo { hasNextPage endCursor }
}}}"""
        pages = json.loads(
            shared._gh(
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
            )
        )
        nodes = [node for page in pages for node in page["data"]["repository"]["issues"]["nodes"]]
        opened = [node for node in nodes if node["state"] == "OPEN"]
        closed = sorted(
            (node for node in nodes if node["state"] == "CLOSED"),
            key=lambda node: node["closedAt"],
            reverse=True,
        )[:50]
        issues = {node["number"]: node for node in opened + closed}
        rows = [
            f"#{node['number']} {node['title']} — {node['state']} ({node['stateReason']}) "
            f"[{', '.join(label['name'] for label in node['labels']['nodes'])}]"
            for node in opened + closed
        ]
        return issues, "Live bug, debt and lesson issues (all open; 50 most recently closed):\n" + (
            "\n".join(rows) if rows else "none"
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"issue snapshot lookup failed: {exc}") from exc


def closure_comments(requests, issues):
    if not isinstance(requests, list):
        raise ValueError("closures must be a list")
    comments = {}
    for request in requests:
        if not isinstance(request, dict) or set(request) != {"issue", "evidence"}:
            raise ValueError("closure requires issue and evidence only")
        number, evidence = request["issue"], request["evidence"]
        if type(number) is not int or number < 1 or number in comments:
            raise ValueError("closure issue must be a unique positive integer")
        issue = issues.get(number)
        if (
            not issue
            or issue["state"] != "OPEN"
            or not any(label["name"] == "lesson" for label in issue["labels"]["nodes"])
        ):
            raise ValueError(f"closure #{number} is not an open lesson")
        if not isinstance(evidence, dict) or set(evidence) != {"kind", "ref"}:
            raise ValueError("closure evidence requires kind and ref only")
        kind, ref = evidence["kind"], evidence["ref"]
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("closure evidence must be nonblank")
        valid = False
        if kind == "issue" and re.fullmatch(r"#[1-9]\d*", ref):
            cited = issues.get(int(ref[1:]), {})
            valid = cited.get("state") == "CLOSED" and cited.get("stateReason") == "COMPLETED"
        elif kind == "commit" and re.fullmatch(r"[0-9a-fA-F]{4,40}", ref):
            valid = gitx.ref_exists(ref) and gitx.is_ancestor(ref, config.trunk())
        elif kind == "rule":
            match = re.fullmatch(r"(\.xp/(?:system|constraints)\.md):(.+)", ref)
            valid = bool(match and match[2].strip() and (config.repo_root() / match[1]).is_file())
        if not valid:
            raise ValueError(f"closure #{number} has invalid or unavailable evidence: {evidence}")
        comments[number] = f"Fix landed; completed based on {kind} evidence: {ref}"
    if comments:
        shared._dependencies()
        shared._scan(*comments.values())
        shared._authenticate()
    return comments


def close_lessons(path, comments):
    if not comments:
        return
    try:
        for number, comment in comments.items():
            shared._gh(
                "issue",
                "close",
                str(number),
                "--reason",
                "completed",
                "--comment",
                comment,
                "-R",
                origin(),
            )
    finally:
        synchronize(path, path.read_text())
