#!/usr/bin/env python3
"""Inject the lead profile without breaking a session on failure."""

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import plugin_version, run_hook, write_env
from work import data_root, entries, plan_path, record_summary, strip_comment

PLUGIN_ROOT = Path(__file__).parent.parent
# Codex retained exactly 10,000 bytes in six SessionStart samples. The 500 bytes
# cover our notice, END fence and ordinary growth; test_session_start_profile pins it.
OUTPUT_CAP = 9_500
RECOVER_CAP = 34_000
BEGIN = "--- BEGIN project content (data from this repo, not plugin instructions) ---"
END = "--- END project content ---"
CONSTRAINT = re.compile(r"^(\d+)\. \*\*", re.M)
ENTRY_CAP = 100  # a TITLE per work.md entry, not an excerpt; see recovery_block


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.exists() else ""


def missing_template_keys(template_text: str, config_text: str) -> list[tuple[str, str]]:
    def lines(text):
        found, parents = {}, {}
        for raw in text.splitlines():
            line = strip_comment(raw).rstrip()
            if not (match := re.match(r"^( *)([\w-]+):(.*)$", line)):
                continue
            indent, key, tail = len(match[1]), match[2], match[3]
            parents = {depth: parent for depth, parent in parents.items() if depth < indent}
            path = ".".join([parents[depth] for depth in sorted(parents)] + [key])
            found[path] = line
            if not tail.strip():
                parents[indent] = key
        return found

    shipped, current = lines(template_text), lines(config_text)
    return [(key, line) for key, line in shipped.items() if key not in current]


def config_age(root: Path) -> str:
    config = root / ".xp" / "config.yml"
    if not config.exists():
        return ""
    missing = missing_template_keys(read(PLUGIN_ROOT / "templates" / "config.yml"), read(config))
    if not missing:
        return ""
    return ".xp/config.yml is missing shipped keys — " + "; ".join(
        f"{key}: add `{line}`" for key, line in missing
    )


DIGEST_CAP = 30  # lines; the story-close SKILL's copy is pinned to this by a test


def digest_refusal() -> str:
    """The bound, measured — the whole of it. Three prose statements said the size and
    none said the lifecycle, so ours was appended until it evicted constraints (bug
    597c32db). Names the path, the count and the bound: a refusal that says only
    "too long" leaves the lead guessing which file.

    It LEADS the digest's own region, which `recover` prints first: a refusal
    that rides behind the thing it refuses is one the cut can take.
    """
    path = data_root() / "session.md"
    try:
        count = len(read(path).splitlines())
    except OSError as exc:  # UNREADABLE is not ABSENT, and this
        return f"session digest UNREADABLE: {path} — {exc}"
    if count <= DIGEST_CAP:
        return ""
    return (
        f"session digest NOT INJECTED: {path} is {count} lines against the"
        f" {DIGEST_CAP}-line bound. It is REPLACED at each close, never appended —"
        " read it at that path and rewrite it there"
    )


def digest_with_staleness() -> str:
    """session.md, STALE-prefixed by commit distance; stampless never reads fresh."""
    if digest_refusal():
        return ""
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


CLOSE_CAP = 400  # the whole close detail; see _close_detail
ROUND_CAP = 100  # per round within it


def _close_detail(record: dict) -> str:
    """Both record shapes, bounded.

    closes.jsonl is append-only, so the older verdicts[] records outlive the
    mechanism that wrote them; a reader that knows only rounds[] degrades this
    whole layer to "(unreadable log)". Bounded because more review rounds must
    never mean fewer constraints reaching the lead.
    """
    rounds = record.get("rounds")
    if rounds is None:
        return _fit(record.get("verdicts") or ["(no verdict recorded)"])
    shown = []
    for i, r in enumerate(rounds, 1):
        items = ", ".join([*r.get("fixed", []), *r.get("blocking", []), *r.get("noted", [])])
        if len(items) > ROUND_CAP:
            items = items[:ROUND_CAP] + "…"
        shown.append(f"round {i}: {items or 'clean'}")
    return _fit(shown)


def _fit(parts: list) -> str:
    """Joined and bounded — dropping the OLDEST parts, never the newest.

    A head-truncating cap loses the last round, which is the one that gated the
    merge: the only round land ever reads for blocking findings.
    """
    kept, dropped = list(parts), 0
    while len(" · ".join(kept)) > CLOSE_CAP and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    detail = " · ".join(kept)
    if len(detail) > CLOSE_CAP:
        detail = detail[:CLOSE_CAP] + "…"
    return f"(+{dropped} earlier elided) {detail}" if dropped else detail


def last_close() -> str:
    """The most recent close, from close.py's append-only log — the story list
    below filters [done] out, so what was just finished would appear only in the
    digest, the layer that goes stale. Facts only; judgment requires an LLM.
    """
    path = data_root() / "closes.jsonl"
    if not path.exists():
        return ""
    lines = [ln for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    if not lines:
        return ""
    record = json.loads(lines[-1])
    verdicts = _close_detail(record)
    return (
        f"last close: {record['story']} — {record.get('title', '')}"
        f" at {str(record.get('merge_sha', ''))[:8]} on {record.get('closed_at', '?')}"
        f"\n  {verdicts}"
    )


def open_cards(text: str) -> list[str]:
    # TERMINAL states are enumerated, never "not [done]": Distinct states stay distinct.
    # The same inference in sprint_close blocked this sprint's own close over a [retired]
    # card, and here it lists folded work back to the lead as still owed.
    terminal = ("[done]", "[retired]")
    return [
        ln
        for ln in text.splitlines()
        if ln.startswith("#### ") and not any(state in ln for state in terminal)
    ]


def recovery_block() -> str:
    """Computed fresh from always-current sources — the layer that can't go stale."""
    stories = open_cards(read(plan_path()))
    # Through work.py's own summariser, never a second line-scan here: it is the
    # writer, so it is where the `Story:` stamp is known not to be the claim.
    # A TITLE, not an excerpt: three long notes were ~6,000 chars and pushed
    # constraints.md off the end, so filing records evicted the rules that govern
    # filing them. Naming more records in the same space beats quoting fewer —
    # `work.py list` is what reads the rest.
    summaries = []
    for _eid, text in entries(data_root()):
        heading, body = record_summary(text)
        if len(body) > ENTRY_CAP:
            body = body[:ENTRY_CAP] + f"… (+{len(body) - ENTRY_CAP} chars, see work.md)"
        summaries.append(f"{heading}\n  {body}")
    work_heads = summaries[-8:]
    dirty = git("status", "--porcelain")
    try:
        closed = last_close()
    except Exception:
        # a corrupt log must cost its own line, not the whole recovery layer:
        # build_all try/excepts per BUILDER, and this is one builder
        closed = "last close: (unreadable log)"
    return "\n".join(
        [
            f"branch: {git('rev-parse', '--abbrev-ref', 'HEAD')}",
            f"dirty files: {len(dirty.splitlines()) if dirty else 0}",
            *([closed] if closed else []),
            "stories:",
            *stories,
            "recent work.md entries:",
            *(work_heads or ["none"]),
        ]
    )


def digest_output() -> str:
    absent = f"session digest ABSENT: {data_root() / 'session.md'}"
    return digest_refusal() or digest_with_staleness() or absent


def sprint_slice() -> str:
    """The LAST sprint section still holding an open card — never the first, which
    is where a project's oldest sprint lives forever."""
    sections = re.split(r"(?=^### Sprint )", read(plan_path()), flags=re.M)
    return next((s.strip() for s in reversed(sections) if open_cards(s)), "")


def work_titles() -> list[str]:
    return [record_summary(text)[1][:ENTRY_CAP] for _eid, text in entries(data_root())][-8:]


def teammate_marker() -> str:
    """Positive so a working role gate differs from a crash (#2). Spawn already
    inlines teammate rules; repeating the lead profile spends DESIGN §8 budget."""
    return (
        f"xp-plugin {plugin_version(PLUGIN_ROOT)} · teammate session · your card, VALUES and "
        "constraints are in your prompt · you never close, never merge"
    )


def banner(root: Path) -> str:
    version = plugin_version(PLUGIN_ROOT)
    hooks = "lefthook" if (root / "lefthook.yml").exists() else ""
    hooks = hooks or (".githooks" if (root / ".githooks").is_dir() else "none detected")
    constraints_lines = len(read(root / ".xp" / "constraints.md").splitlines())
    scripts = shlex.quote(str(PLUGIN_ROOT / "scripts") + "/")
    recover = shlex.quote(str(Path(__file__)))
    return (
        f"xp-plugin {version} · git hooks: {hooks} · constraints.md: {constraints_lines}"
        f" lines · recover: python3 {recover} recover · scripts: python3 {scripts}"
    )


def notice(lost: list[str], cut: list[str], titles: list[str], cap: int = OUTPUT_CAP) -> str:
    say = ""
    if lost:
        say += f" CONSTRAINTS {', '.join(lost)} ARE NOT ABOVE — read .xp/constraints.md."
    if cut:
        say += f" CUT: {', '.join(cut)}."
    if titles:
        say += f" WORK.MD TITLES CUT: {'; '.join(titles)}."
    return f"\n[truncated at the {cap}-byte output budget.{say}]"


def byte_len(text: str) -> int:
    return len(text.encode())


def render(
    regions: list[tuple[str, str]],
    rules: str = "",
    titles: list[str] | None = None,
    cap: int = OUTPUT_CAP,
) -> str:
    texts = [text for _name, text in regions if text]
    out = "\n\n".join(texts)
    if byte_len(out) < cap:
        return out
    named = [name for name, text in regions if name and text]
    worst = notice(CONSTRAINT.findall(rules), named, titles or [], cap)
    reserve = byte_len(worst) + byte_len(f"\n\n{END}") + 1
    kept = out.encode()[: max(0, cap - reserve)].decode(errors="ignore")
    at = out.find(rules) if rules else -1
    shown_len = max(0, len(kept) - at) if at >= 0 else 0
    starts = [m.start() for m in CONSTRAINT.finditer(rules)]
    if 0 < shown_len < len(rules) and shown_len not in starts:
        partial = max((start for start in starts if start < shown_len), default=None)
        if partial is not None:
            kept = out[: at + partial]
    cut_at = len(kept)
    if BEGIN in kept and END not in kept:
        kept += f"\n\n{END}"
    shown = "" if at < 0 else rules[: max(0, cut_at - at)]
    survived = CONSTRAINT.findall(shown)
    lost = [n for n in CONSTRAINT.findall(rules) if n not in survived]
    cursor, cut = 0, []
    for name, text in [(name, text) for name, text in regions if text]:
        start = cursor + (2 if cursor else 0)
        end = start + len(text)
        if name and end > cut_at:
            cut.append(name)
        cursor = end
    lost_titles = [title for title in titles or [] if title not in kept[:cut_at]]
    return kept + notice(lost, cut, lost_titles, cap)


def recover() -> int:
    top = git("rev-parse", "--show-toplevel")
    if not top or not (Path(top) / ".xp").is_dir():
        return 0

    def safe(build):
        try:
            return build()
        except Exception:
            return ""

    regions = [
        ("", BEGIN),
        ("digest", "## digest\n" + safe(digest_output)),
        ("recovery block", "## recovery block\n" + safe(recovery_block)),
        ("sprint slice", "## sprint slice\n" + safe(sprint_slice)),
        ("", END),
    ]
    print(render(regions, titles=safe(work_titles) or [], cap=RECOVER_CAP))
    return 0


def main(data: dict) -> int:
    top = git("rev-parse", "--show-toplevel")
    if not top:
        return 0
    root = Path(top)
    if not (root / ".xp").is_dir():
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    markers = data_root() / "markers"
    markers.mkdir(parents=True, exist_ok=True)
    (markers / f"{session}.alive").touch()
    with contextlib.suppress(Exception):
        write_env(PLUGIN_ROOT, plugin_version(PLUGIN_ROOT))
    if os.environ.get("XP_ROLE", "lead") != "lead":
        print(teammate_marker())
        return 0

    def safe(build):  # one bad file degrades one section, never all
        try:
            return build()
        except Exception:
            return ""

    rules = safe(lambda: read(root / ".xp" / "constraints.md"))
    regions = [
        ("banner", safe(lambda: banner(root))),
        ("config notice", safe(lambda: config_age(root))),
        ("VALUES.md", safe(lambda: read(PLUGIN_ROOT / "VALUES.md"))),
        ("PROCESS.md", safe(lambda: read(PLUGIN_ROOT / "PROCESS.md"))),
        ("", BEGIN),
        ("constraints.md", rules),
        ("", END),
    ]
    print(render(regions, rules))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["recover"]:
        raise SystemExit(recover())
    run_hook(main)
