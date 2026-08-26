"""Shared fixtures for the test_sprint_close family.
Split at sprint-004 open: tests are production code (constraint 8)."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from close_helpers import (
    REVIEWER_EMAIL,
    REVIEWER_NAME,
    launches,
    stream_json,
    stub_reviewer,
)

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"

WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"

PLAN = """# plan
## Milestone 1
### Sprint 2 — the one under test
#### story-042 — done thing   [done]
Verify: true
#### story-043 — also done   [done]
Verify: true

### Sprint 3
#### story-099 — not this sprint   [ready]
Verify: true
"""

CONFIG = (
    "release: sprint\nsprint_branch: sprint-002\n"
    "roles:\n  reviewer: claude/opus\ntests:\n  full: true\n"
)

WORK_SECTION = "work.md entries filed during the sprint"

SPRINT_ID = "2"


def make_repo(tmp_path, plan=PLAN, config=CONFIG):
    repo = tmp_path / "repo"
    templates = Path(os.environ["XP_TEST_REPO_TEMPLATES"])
    full = plan == PLAN and config == CONFIG and (templates / "sprint-full").is_dir()
    shutil.copytree(templates / ("sprint-full" if full else "sprint"), repo)
    if not full:
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    state_plan = tmp_path / "data" / "plan.md"
    state_plan.parent.mkdir(parents=True, exist_ok=True)
    state_plan.write_text(plan)
    if full:
        return repo, env, g
    (repo / ".xp" / "config.yml").write_text(config)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "src.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "sprint-002")
    # the sprint's own work, absent from the default branch: under `release:
    # sprint` an integration_target() diff would not carry it
    (repo / "src.py").write_text("A = 1\nB = 'SPRINT-ONLY-SENTINEL'\n")
    g("add", "-A")
    g("commit", "-qm", "story work on the sprint branch")
    return repo, env, g


def sprint(repo, env, *args, sprint_id=SPRINT_ID, close=CLOSE):
    """`close` names WHICH close.py runs: the angle injection drives a copy of
    the plugin, so the refusal is proven on the real reader, not on a stub."""
    return subprocess.run(
        [sys.executable, str(close), "sprint", sprint_id, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def head(repo, env):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
    ).stdout.strip()


def marker_path(tmp_path, sprint_id=SPRINT_ID):
    return tmp_path / "data" / "markers" / "sprint" / f"{sprint_id}.json"


def record_reviews(tmp_path, repo, env, blocking=(), shown=None):
    """CONSTRUCT the state a real review leaves, so land's guard is exercised
    against a marker rather than against the absence of one."""
    path = marker_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    round_ = {"fixed": [], "blocking": list(blocking), "noted": []}
    path.write_text(json.dumps({"rounds": [round_], "shown_sha": shown or head(repo, env)}))


def stage_key(bundle):
    """The pipeline stage a launch belongs to, read off the REPORT_PATH its
    bundle names — the same string the leg passes to sprint_report_path."""
    m = re.search(r"^REPORT_PATH: (.+)$", bundle, re.M)
    return Path(m.group(1).strip()).name.split(".")[1] if m else ""


def bundles(tmp_path, stage=""):
    return [b for r in launches(tmp_path) if (b := r["stdin"]) and stage_key(b).startswith(stage)]


def staged_stub(tmp_path, patches=(), **stages):
    """A fake `claude` that answers PER STAGE, keyed off the report path.

    One body for every launch cannot tell a finder from the closing pass, so a
    planted blocker would be reported by every stage at once and the injection
    would pass against a pipeline that never ran the stage it names. Stage keys
    spell `-` as `_`: `find_security=`, `verify=`, `fix=`, `close=`, and a key
    answers every stage whose `-`-separated key it prefixes, so `find=` reaches
    every angle's finder and not only the one whose slug has no hyphen. `patches`
    entries are (stage prefix, path, appended line).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launches.jsonl"
    table = {k.replace("_", "-"): v for k, v in stages.items()}
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import difflib, json, os, re, sys\n"
        "stdin = sys.stdin.read()\n"
        f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'stdin': stdin}) + '\\n')\n"
        "m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M)\n"
        "assert m, 'the bundle named no REPORT_PATH'\n"
        "key = os.path.basename(m.group(1).strip()).split('.')[1]\n"
        f"table = {json.dumps(table)}\n"
        "clean = {'fixed': [], 'blocking': [], 'noted': []}\n"
        "hit = [v for k, v in table.items() if key == k or key.startswith(k + '-')]\n"
        "report = hit[0] if hit else clean\n"
        "open(m.group(1).strip(), 'w').write(json.dumps(report))\n"
        "pm = re.search(r'^PATCH_PATH: (.+)$', stdin, re.M)\n"
        f"for prefix, target, line in {json.dumps([list(c) for c in patches])}:\n"
        "    if key.startswith(prefix):\n"
        "        before = open(target).read().splitlines(True)\n"
        "        after = before + [line + '\\n']\n"
        "        diff = 'diff --git a/{0} b/{0}\\n'.format(target)\n"
        "        diff += ''.join(difflib.unified_diff(\n"
        "            before, after, 'a/' + target, 'b/' + target))\n"
        "        open(pm.group(1).strip(), 'w').write(diff)\n"
        f"sys.stdout.write({stream_json('findings above')!r})\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir


def commit_as_reviewer(g, message):
    """A commit git attributes to the reviewer, which is what the coverage and
    motion gates key on — the label spawn.run_agent puts on every review launch."""
    g("commit", "-qam", message, f"--author={REVIEWER_NAME} <{REVIEWER_EMAIL}>")


def work(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(WORK), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def snapshot(root: Path):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def section(bundle, title, until):
    """A named section's body. Sliced between two titles rather than split on a
    blank-line-plus-`## ` boundary, because the raw work.md section carries
    `## note` headings of its own and would cut itself in half."""
    head = f"## {title}\n\n"
    start = bundle.index(head) + len(head)
    return bundle[start : bundle.index(f"## {until}\n\n", start)]


def committing_stub(tmp_path, body):
    """A stub that writes a valid report and then moves the tree. A stub that
    never moves it certifies nothing (constraint 2)."""
    bin_dir = stub_reviewer(tmp_path)
    claude = bin_dir / "claude"
    claude.write_text(claude.read_text().replace("sys.stdout.write(", body + "\nsys.stdout.write("))
    claude.chmod(0o755)
    return bin_dir
