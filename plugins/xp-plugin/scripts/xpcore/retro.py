"""Fresh-context retros and the shared project's lessons ledger."""

import fcntl
import json
import re
import sys
import tempfile
from pathlib import Path

from xpcore import bundle, cards, config, gitx, launch, shared
from xpcore.lesson_issues import (
    ReceiptError,
    atomic,
    close_lessons,
    closure_comments,
    file_pending,
    issue_input,
    issue_number,
    lesson_issue,
    origin,
    parse_ledger,
    synchronize,
)


def ledger_path() -> Path:
    url = gitx.git("remote", "get-url", "origin", check=False)
    if not url:
        return config.data_root() / "lessons.md"
    project = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url.lower())
    if not project or any(part in ("", ".", "..") for part in project.groups()):
        raise ValueError(f"cannot derive project from origin {url!r}")
    return Path.home() / ".xp/projects" / project[1] / project[2] / "lessons.md"


def recovery_rows():
    path = ledger_path()
    if not path.exists():
        return []
    text = path.read_text()
    malformed = []
    records = parse_ledger(text, malformed)
    lines = text.splitlines()
    rows = [lines[record[0]] for record in records.values() if record[1] == "proposed"] + malformed
    if not rows:
        return []
    return [f"\n### lessons — edit lesson status in {path}", *rows]


def words(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonblank text")
    return " ".join(value.split())


def shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"expected fields: {keys}")


def validate(answer, markdown, records, issues=None):
    value = json.loads(answer)
    if issues is not None:
        closures = value.pop("closures", [])
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
            number = int(ref[1:]) if re.fullmatch(r"#[1-9]\d*", ref) else 0
            if lesson_issue((issues or {}).get(number), "CLOSED"):
                refs[ref] = words(f"Replacement for {ref}: {issues[number]['title']}")
                continue
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
    comments = closure_comments(closures, issues) if issues is not None else {}
    return value, refs, comments


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


def persist(path, candidate, target, result, refs, sighting):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = path.read_text() if path.exists() else None
        lines = (previous or "").splitlines()
        records = parse_ledger(previous or "")
        next_id = max((int(key[1:]) for key in records), default=0) + 1
        stale = {}
        for key, record in list(records.items()):
            index, status, text, seen, reason = record
            if sighting not in seen:
                continue
            remaining = [entry for entry in seen if entry != sighting]
            if not remaining and (
                status == "sighting" or (status == "proposed" and not issue_number(record))
            ):
                if key not in refs:
                    stale[key] = records.pop(key)
                    stale[key][1:] = ["sighting", text, [], "not proposed"]
                    continue
                status, reason = "sighting", "not proposed"
            elif not remaining:
                # Filed proposals and final dispositions retain their historical evidence.
                continue
            record[1], record[3], record[4] = status, remaining, reason
            lines[index] = f"- {key} [{status}] {text} (seen: {', '.join(remaining)}) -> {reason}"
        for ref, text in refs.items():
            key = ref
            applied = ref in records and records[ref][1] == "applied"
            if applied:
                text = f"Replacement for {ref}: {records[ref][2]}"
            if ref.startswith(("new:", "#")) or applied:
                key = next(
                    (
                        k
                        for k, record in records.items()
                        if record[1] in ("sighting", "proposed") and words(record[2]) == text
                    ),
                    "",
                )
                # A rerun that words a lesson as before keeps its ID; a new one never reuses one.
                key = key or next((k for k, r in stale.items() if words(r[2]) == text), "")
                if key in stale:
                    records[key] = stale.pop(key)
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
        removed = {record[0] for record in stale.values()}
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


def publish(path):
    if gitx.git("status", "--porcelain", "--", path.name, cwd=path.parent):
        shared._scan(path.read_text())
        gitx.git("add", path.name, cwd=path.parent)
        identity = ("-c", "user.name=xp", "-c", "user.email=xp@localhost")
        gitx.git(*identity, "commit", "-m", "Lessons", cwd=path.parent)
        gitx.git("push", "origin", "HEAD", cwd=path.parent)


def run(identifier):
    if not (config.data_root() / "sprints" / identifier / "release.json").is_file():
        raise ValueError("sprint must be released first")
    path = ledger_path()
    with tempfile.TemporaryDirectory() as temporary:
        if config.github_issues():
            if path.exists():
                raise ValueError(
                    f"merge {path} into the wiki's Lessons.md, then remove the local file"
                )
            try:
                gitx.git("clone", re.sub(r"(?:\.git)?$", ".wiki.git", origin(), count=1), temporary)
            except gitx.GitError as exc:
                url = json.loads(shared._gh("repo", "view", origin(), "--json", "url"))["url"]
                raise ValueError(f"{exc}; create the wiki's first page at {url}/wiki") from exc
            path = Path(temporary) / "Lessons.md"
        run_ledger(identifier, path)


def run_ledger(identifier, path):
    folder = config.data_root() / "sprints" / identifier
    if config.github_issues():
        file_pending(path, publish)
    snapshot = path.read_text() if path.exists() else ""
    snapshot = synchronize(path, snapshot)
    if config.github_issues():
        publish(path)
    issues, live = issue_input() if config.github_issues() else (None, "")
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
            extra=inputs(identifier, slate, snapshot) + "\n" + live,
            paths={
                "RETRO_PATH": str(candidate),
                "SIGHTING": f"{gitx.common_dir().parent.name}:{identifier}",
            },
        )
        seat = launch.run_agent("retro", prompt, config.repo_root(), f"{identifier}-retro")
        if seat.returncode or not candidate.is_file():
            raise ValueError("seat failed or wrote no fresh retro")
        result, refs, comments = validate(seat.stdout, candidate.read_text(), records, issues)
        target = folder / "retro.md"
        sighting = f"{gitx.common_dir().parent.name}:{identifier}"
        persist(path, candidate, target, result, refs, sighting)
        if config.github_issues():
            publish(path)
            try:
                close_lessons(path, comments)
            finally:
                publish(path)
            file_pending(path, publish)
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
        retry = "" if isinstance(exc, ReceiptError) else f"; run xp.py retro {args.id} to retry"
        print(f"Retro failed: {exc}{retry}", file=sys.stderr)
        return 1
