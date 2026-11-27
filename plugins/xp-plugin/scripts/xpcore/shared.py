"""GitHub publication plumbing shared by cards and finding records."""

import hashlib
import json
import re
import shlex
import shutil
import socket
import subprocess

from xpcore import cards, gitx
from xpcore.config import github_issues, refuse, repo_root, require_github_issues

GH_TIMEOUT = 30
# A field name is a short title-case phrase (Not in scope); a prose line with a colon is not.
FIELD = re.compile(r"^([^\s:][^:]*):")
# Only a field the plugin reads ends a claimed Context: a prose line shaped like a field
# then stays local instead of leaking a private Context edit to the issue.
AFTER_CONTEXT = (
    "Measure:",
    "AC:",
    "Files:",
    "Acceptance:",
    "Evidence:",
    "Executor:",
    "Issue:",
    "Published by:",
)


def _dependencies() -> None:
    if not shutil.which("gh"):
        refuse("install gh and authenticate with gh auth login; GitHub publication requires GitHub")
    if not shutil.which("gitleaks"):
        refuse("install gitleaks; GitHub publication requires secret scanning")


def _scan(*texts: str) -> None:
    _dependencies()
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
    _authenticate()


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


def create_issue(title: str, label: str, body: str, *repo: str) -> tuple[str, str]:
    args = ["issue", "create", "--title", title, "--label", label, "--body-file", "-"]
    url = _gh(*args, *repo, body=body)
    match = re.search(r"/issues/(\d+)$", url)
    if not match:
        error = ValueError(f"expected issue URL, got {url!r}; inspect GitHub before retrying")
        error.url = url  # the operator's only lead on what gh created
        raise error
    return url, match[1]


def owner() -> str:
    machine = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:6]
    return f"{gitx.common_dir().parent.name}@{machine}"


def public_body(card: cards.Card) -> str:
    context = f"local to {owner()}"
    lines = [card.lines[0], f"Context: {context}"]
    ac = False
    for line in card.lines[1:]:
        if ac and (
            not line.strip()
            or line.startswith(("- ", "* ", "  ", "\t"))
            or re.match(r"\d+\. ", line)
        ):
            lines.append(line)
        elif match := FIELD.match(line):
            ac = match[1] == "AC"
            if match[1] in {"Measure", "AC", "Files", "Acceptance", "Evidence", "Executor"}:
                lines.append(line)
        else:
            ac = False
    return "\n".join([*lines, f"Published by: {owner()}"]) + "\n"


def _holders(issue: str) -> tuple[list[str], str]:
    data = json.loads(_gh("issue", "view", issue[1:], "--json", "body,labels"))
    return [x["name"][6:] for x in data["labels"] if x["name"].startswith("clone:")], data["body"]


def _push(card: cards.Card, issue: str, take: bool = False) -> None:
    """The holder's copy is the live one: never overwrite it from another clone."""
    holders, published = _holders(issue)
    if others := [h for h in holders if h != owner()]:
        refuse(f"{issue} is held by {', '.join(others)}; its text is theirs; {card.id} stays local")
    if card.field("Published by"):
        start, end = context_span(card.lines)
        public = issue_card(published).lines
        public_start, public_end = context_span(public)
        body = (
            "\n".join(card.lines[:start] + public[public_start:public_end] + card.lines[end:])
            + "\n"
        )
    else:
        body = public_body(card)
    _scan(card.title, body)
    edit = ["issue", "edit", issue[1:], "--title", card.title, "--body-file", "-"]
    if take and not holders:
        # A card this clone runs is held by it, so no other clone can claim it mid-run.
        _gh("label", "create", f"clone:{owner()}", "--force")
        edit += ["--add-label", f"clone:{owner()}"]
    _gh(*edit, body=body)
    print(f"updated {issue}")


def _issue(card: cards.Card) -> str:
    issue = card.field("Issue")
    if issue and not re.fullmatch(r"#\d+", issue):
        refuse(f"{card.id}: Issue must be #N; correct the local card")
    return issue


def sync(card: cards.Card) -> None:
    """Lifecycle republication, so review edits reach the issue without a lead remembering."""
    if not (issue := _issue(card)):
        return
    if not github_issues():
        print(f"{card.id}: github_issues is off; {issue} not updated")
        return
    try:
        _push(card, issue, take=True)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        refuse(f"GitHub update of {issue} failed: {exc}; fix gh access and retry")


def context_span(lines: list[str]) -> tuple[int, int]:
    for start, line in enumerate(lines):
        if line.startswith("Context:"):
            end = start + 1
            while end < len(lines) and not lines[end].startswith(AFTER_CONTEXT):
                end += 1
            return start, end
    return 1, 1


def cmd_publish(args) -> int:
    require_github_issues()
    card = cards.find_card(args.id)
    issue = _issue(card)
    try:
        if issue:
            _push(card, issue)
        else:
            _dependencies()
            _authenticate()
            moving = cards.publish_moves(card.id)
            body = (
                "\n".join([*card.lines, f"Published by: {owner()}"]) + "\n"
                if moving
                else public_body(card)
            )
            _scan(card.title, body)
            ensure_label("card")
            url, number = create_issue(card.title, "card", body)
            if not moving or not cards.remove_published(card):
                cards.set_field(card.id, "Issue", f"#{number}")
                if moving:
                    print(f"{card.id} kept: edited while publishing; republish to update #{number}")
            else:
                print(f"{card.id}: moved {len(card.lines)} lines to #{number}")
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
            release = " or ".join(
                f"gh issue edit {args.id} --remove-label clone:{o}" for o in others
            )
            refuse(f"card held by {', '.join(others)}; the holder releases it with {release}")
        local = cards.read_cards() if cards.plan_path().is_file() else []
        if any(c.id == card.id and c.field("Issue") != f"#{args.id}" for c in local):
            refuse(f"{card.id}: local id collision; rename it before claiming #{args.id}")
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


def complete_issues(completed: list[cards.Card], sha: str, retired=()) -> None:
    commands = []
    for card in completed:
        if not (issue := _issue(card)):
            continue
        number = issue[1:]
        comment = f"Merged as {sha}"
        if card.field("Evidence"):
            commands.extend(
                [
                    (issue, ["label", "create", "merged", "--force"]),
                    (issue, ["issue", "edit", number, "--add-label", "merged"]),
                    (issue, ["issue", "comment", number, "--body", comment]),
                ]
            )
        else:
            commands.append((issue, ["issue", "close", number, "--comment", comment]))
    for index, card in enumerate(retired):
        if not (issue := _issue(card)):
            continue
        try:
            others = [h for h in _holders(issue)[0] if h != owner()]
        except RuntimeError as exc:
            # Nothing has changed yet, so every command is still the lead's to run.
            left = [shlex.join(["gh", *cmd]) for _, cmd in commands]
            for rest in filter(None, map(_issue, retired[index:])):
                left.append(f"gh issue close {rest[1:]} --reason 'not planned'  # if unheld")
            refuse(f"{issue}: {exc}; release recorded. Finish manually:\n" + "\n".join(left))
        if others:
            # A retired card another clone holds is its work, not ours to close.
            print(f"{issue}: left open for its holder {', '.join(others)}")
            continue
        close = ["issue", "close", issue[1:], "--reason", "not planned"]
        commands.append((issue, [*close, "--comment", f"Retired unshipped at {sha}"]))
    for index, (issue, command) in enumerate(commands):
        try:
            _gh(*command)
        except RuntimeError as exc:
            remaining = "\n".join(shlex.join(["gh", *cmd]) for _, cmd in commands[index:])
            refuse(f"{issue}: {exc}; release recorded. Finish manually:\n{remaining}")


CARD_QUERY = """query($owner:String!, $repo:String!, $endCursor:String) {
  repository(owner:$owner, name:$repo) {
    issues(first:100, after:$endCursor, states:OPEN, labels:["card"]) {
      nodes { number title body labels(first:100) { nodes { name } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""


def open_cards() -> list[str]:
    try:
        pages = json.loads(
            _gh(
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-F",
                "owner={owner}",
                "-F",
                "repo={repo}",
                "-f",
                f"query={CARD_QUERY}",
            )
        )
        issues = [
            issue for page in pages for issue in page["data"]["repository"]["issues"]["nodes"]
        ]
        rows = []
        ours = owner()
        for issue in issues:
            number = issue["number"]
            try:
                card = issue_card(issue["body"])
                holders = [
                    label["name"][6:]
                    for label in issue["labels"]["nodes"]
                    if label["name"].startswith("clone:")
                ]
                holding = ", ".join(h + (" (this clone)" if h == ours else "") for h in holders)
                row = f"#{number} {card.id} — {card.title} [{card.status}]"
                row += f"; {holding or 'unclaimed'}"
                if card.field("Evidence") and any(
                    label["name"] == "merged" for label in issue["labels"]["nodes"]
                ):
                    row += f"; merged, awaiting evidence: {card.field('Evidence')}"
                rows.append(row)
            except (ValueError, KeyError, TypeError) as exc:
                rows.append(f"#{number} invalid card: {exc}")
        return rows
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return [f"GitHub shared cards unavailable: {exc}"]
