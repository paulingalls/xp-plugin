"""Fresh-context retros and the shared project's lessons ledger."""

import fcntl
import json
import re
import sys
import tempfile
from pathlib import Path

from xpcore import bundle, cards, config, gitx, launch, shared

RECORD = re.compile(
    r"- (L[1-9]\d*) \[(sighting|proposed|applied|dropped)\] (.+?) \(seen: ([^)]+)\) -> (.+)"
)
CONTRACT = """Return only JSON:
{"sightings":[{"lesson":"L3"},{"lesson":"new:1","text":"New lesson"}],
"proposals":[{"lessons":["L3","new:1"],"text":"Action","why":{"sightings":"Supporting sightings",
"cost":"What each cost","form":"Why this form over a cheaper fix"}}]}.
Use existing IDs or unique new:<n> keys. Every proposal references returned sightings.
No other fields. Write Markdown with Misses, Sightings and Proposals to RETRO_PATH."""


def ledger_path() -> Path:
    url = gitx.git("remote", "get-url", "origin", check=False)
    if not url:
        return config.data_root() / "lessons.md"
    project = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url.lower())
    if not project or any(part in ("", ".", "..") for part in project.groups()):
        raise ValueError(f"cannot derive project from origin {url!r}")
    return Path.home() / ".xp/projects" / project[1] / project[2] / "lessons.md"


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


def recovery_rows():
    path = ledger_path()
    if not path.exists():
        return []
    text = path.read_text()
    malformed = []
    records = parse_ledger(text, malformed)
    lines = text.splitlines()
    rows = [
        lines[record[0]] + (f" — xp.py lesson file {key[1:]}" if config.github_issues() else "")
        for key, record in records.items()
        if record[1] == "proposed" and (not config.github_issues() or not issue_number(record))
    ] + malformed
    if not rows:
        return []
    disposal = (
        "close applied issues as completed; dropped as not planned with the reason"
        if config.github_issues()
        else f"edit lesson status in {path}"
    )
    return [f"\n### lessons — {disposal}", *rows]


def origin():
    url = gitx.git("remote", "get-url", "origin", check=False)
    if not url:
        raise ValueError("origin remote is missing")
    return url


def cmd_lesson_file(args):
    config.require_github_issues()
    try:
        path = ledger_path()
        with path.with_name(path.name + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            text = path.read_text()
            key = f"L{args.id}"
            records = parse_ledger(text)
            if key not in records:
                raise ValueError(f"unknown lesson {key}")
            record = records[key]
            if record[1] != "proposed":
                raise ValueError(f"{key} is not proposed")
            if issue_number(record):
                raise ValueError(f"{key} already filed as #{issue_number(record)}")
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
                raise ValueError(
                    f"issue created but number unavailable: {url}; inspect GitHub and repair ledger"
                )
            lines = text.splitlines(keepends=True)
            index = record[0]
            lines[index] = lines[index].rstrip("\r\n") + f"; #{match[1]}\n"
            try:
                atomic(path, "".join(lines))
            except OSError as exc:
                raise ValueError(
                    f"created {url}; manually add ; #{match[1]} to {key} in {path}: {exc}"
                ) from exc
            print(url)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        config.refuse(f"lesson filing failed: {exc}")


def words(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonblank text")
    return " ".join(value.split())


def shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"expected fields: {keys}")


def validate(answer, markdown, records):
    value = json.loads(answer)
    shape(value, ("sightings", "proposals"))
    if not isinstance(value["sightings"], list) or not isinstance(value["proposals"], list):
        raise ValueError("sightings and proposals must be lists")
    refs = {}
    for sighting in value["sightings"]:
        if not isinstance(sighting, dict):
            raise ValueError("invalid sighting")
        ref = sighting.get("lesson")
        if not isinstance(ref, str) or ref in refs:
            raise ValueError("invalid or duplicate lesson reference")
        if re.fullmatch(r"new:[1-9]\d*", ref):
            shape(sighting, ("lesson", "text"))
            text = words(sighting["text"])
            if "\n" in sighting["text"] or "(seen:" in text:
                raise ValueError("new lesson must be a single unambiguous line")
            refs[ref] = text
        else:
            shape(sighting, ("lesson",))
            if ref not in records:
                raise ValueError(f"unknown lesson {ref}")
            refs[ref] = records[ref][2]
    if len(value["proposals"]) > 2:
        raise ValueError("at most two proposals")
    for proposal in value["proposals"]:
        shape(proposal, ("lessons", "text", "why"))
        linked = proposal["lessons"]
        if (
            not isinstance(linked, list)
            or not linked
            or any(not isinstance(r, str) or r not in refs for r in linked)
            or len(set(linked)) != len(linked)
        ):
            raise ValueError("proposal must reference unique returned sightings")
        shape(proposal["why"], ("sightings", "cost", "form"))
        for text in (proposal["text"], *proposal["why"].values()):
            if re.search(r"#[1-9]\d*\s*$", words(text)):
                raise ValueError("proposal text must not end with an issue-number marker")
    for heading in ("Misses", "Sightings", "Proposals"):
        if not re.search(rf"^## {heading}\s*$", markdown, re.M):
            raise ValueError(f"missing {heading} section")
    return value, refs


def inputs(identifier, slate, ledger):
    data = config.data_root()
    folder = data / "sprints" / identifier
    parts = []

    def read(path):
        parts.append(
            f"{path.relative_to(data)}:\n{path.read_text()}"
            if path.is_file()
            else f"{path.relative_to(data)}: absent"
        )

    def rounds(directory, pattern):
        paths = sorted(directory.glob(pattern))
        if not paths:
            parts.append(f"{directory.name}/{pattern}: absent")
        for path in paths:
            read(path)

    read(folder / "slate-review.md")
    logs = [
        f"{identifier}-sprint-open",
        f"{identifier}-sprint-close",
        f"sprint-{identifier}-sprint-hook",
    ]
    for card in cards.read_cards(slate):
        story = data / "stories" / card.id
        read(story / "plan-review.md")
        rounds(story, "review-[0-9]*.md")
        read(story / "handback.md")
        logs.extend(
            f"{card.id}-{suffix}"
            for suffix in (
                "worktree-setup",
                "land-setup",
                "acceptance",
                "story-close",
                "worktree-teardown",
            )
        )
    for pattern in ("review-[0-9]*.*.md", "triage-[0-9]*.*.md", "handback-[0-9]*.md"):
        rounds(folder, pattern)
    read(data / "session.md")
    parts.append(f"Lessons ledger:\n{ledger or 'absent'}")
    for name in logs:
        path = data / "logs" / f"{name}.log"
        exits = []
        if path.is_file():
            for invocation in re.split(r"^\$ ", path.read_text(), flags=re.M)[1:]:
                match = re.search(r"^xp-hook-exit: (-?\d+)$", invocation, re.M)
                exits.append(match[1] if match else "unknown")
        parts.append(f"{name}.log: {', '.join(exits) if exits else 'absent'}")
    return "\n\n".join(parts)


def why_text(proposal):
    return "; ".join(f"{key}: {words(value)}" for key, value in proposal["why"].items())


def atomic(path, text):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        staged.write_text(text)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def persist(path, candidate, target, result, refs, sighting):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = path.read_text() if path.exists() else None
        lines = (previous or "").splitlines()
        records = parse_ledger(previous or "")
        removed = set()
        for key, record in list(records.items()):
            index, status, text, seen, reason = record
            if sighting not in seen:
                continue
            remaining = [entry for entry in seen if entry != sighting]
            if not remaining and (
                status == "sighting" or (status == "proposed" and not issue_number(record))
            ):
                if key not in refs:
                    removed.add(index)
                    del records[key]
                    continue
                status, reason = "sighting", "not proposed"
            elif not remaining:
                # Filed proposals and final dispositions retain their historical evidence.
                continue
            record[1], record[3], record[4] = status, remaining, reason
            lines[index] = f"- {key} [{status}] {text} (seen: {', '.join(remaining)}) -> {reason}"
        next_id = max((int(key[1:]) for key in records), default=0) + 1
        for ref, text in refs.items():
            key = ref
            applied = ref in records and records[ref][1] == "applied"
            if applied:
                text = f"Replacement for {ref}: {records[ref][2]}"
            if ref.startswith("new:") or applied:
                key = next(
                    (
                        k
                        for k, record in records.items()
                        if record[1] in ("sighting", "proposed") and words(record[2]) == text
                    ),
                    "",
                )
                if not key:
                    key = f"L{next_id}"
                    next_id += 1
                    records[key] = [len(lines), "sighting", text, [], "not proposed"]
                    lines.append("")
            if key not in records:
                raise ValueError(f"lesson disappeared: {key}")
            index, status, text, seen, reason = records[key]
            if sighting not in seen:
                seen.append(sighting)
            proposals = [p for p in result["proposals"] if ref in p["lessons"]]
            if proposals and status in ("sighting", "dropped"):
                status = "proposed"
                why = " | ".join(f"proposal: {words(p['text'])}; {why_text(p)}" for p in proposals)
                reason = why if reason == "not proposed" else f"{reason}; {why}"
            records[key] = [index, status, text, seen, reason]
            lines[index] = f"- {key} [{status}] {text} (seen: {', '.join(seen)}) -> {reason}"
        lines = [line for index, line in enumerate(lines) if index not in removed]
        atomic(path, "\n".join(lines) + ("\n" if lines else ""))
        try:
            candidate.replace(target)
        except OSError:
            if previous is None:
                path.unlink()
            else:
                atomic(path, previous)
            raise


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


def run(identifier):
    folder = config.data_root() / "sprints" / identifier
    if not (folder / "release.json").is_file():
        raise ValueError("sprint must be released first")
    path = ledger_path()
    snapshot = path.read_text() if path.exists() else ""
    snapshot = synchronize(path, snapshot)
    records = parse_ledger(snapshot)
    slate = cards.sprint_slate(identifier)
    with tempfile.NamedTemporaryFile(
        prefix=".retro-", suffix=".md", dir=folder, delete=False
    ) as stream:
        candidate = Path(stream.name)
    candidate.unlink()
    try:
        prompt = bundle.prompt(
            "retro",
            slate=slate,
            extra=inputs(identifier, slate, snapshot) + "\n" + CONTRACT,
            paths={
                "RETRO_PATH": str(candidate),
                "SIGHTING": f"{gitx.common_dir().parent.name}:{identifier}",
            },
        )
        seat = launch.run_agent("retro", prompt, config.repo_root(), f"{identifier}-retro")
        if seat.returncode or not candidate.is_file():
            raise ValueError("seat failed or wrote no fresh retro")
        result, refs = validate(seat.stdout, candidate.read_text(), records)
        target = folder / "retro.md"
        sighting = f"{gitx.common_dir().parent.name}:{identifier}"
        persist(path, candidate, target, result, refs, sighting)
        print(f"Retro: {target}")
        for proposal in result["proposals"]:
            print(f"Proposal: {words(proposal['text'])}\nWhy: {why_text(proposal)}")
        if not result["proposals"]:
            print("No proposals.")
    finally:
        candidate.unlink(missing_ok=True)


def cmd_retro(args):
    try:
        run(args.id)
        return 0
    except (Exception, SystemExit) as exc:
        print(f"Retro failed: {exc}; run xp.py retro {args.id} to retry", file=sys.stderr)
        return 1
