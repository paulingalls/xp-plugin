"""Shared fixtures for the test_close family.
Split at sprint-004 open: tests are production code
(constraint 8), and test_close.py measured 2,059 lines."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from work import flip_status

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"

SPAWN = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "spawn.py"

WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: {verify}
"""

CONFIG = "roles:\n  reviewer: claude/opus\ntests:\n  story: true\n"

REVIEWER_NAME = "xp story-reviewer"
REVIEWER_EMAIL = "story-reviewer@xp.local"
CLEAN = {"fixed": [], "blocking": [], "noted": []}
# Injected into close.py's OWN env by the tests that assert a reviewer launch
# carries no credential: unset in the parent, the assertion passes on a spawn
# that strips nothing.
LEAD_CREDS = {"GIT_AUTHOR_NAME": "the lead", "GIT_COMMITTER_EMAIL": "lead@example.com"}
FIX_PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+x = 1
"""
XP_PATCH = """diff --git a/.xp/system.md b/.xp/system.md
--- a/.xp/system.md
+++ b/.xp/system.md
@@ -1,2 +1,3 @@
 # System
 SYSTEM-SENTINEL
+reviewer = true
"""
# Real hunks against the fixture's real content: a patch that cannot apply is
# refused by the applicability check, and would prove nothing about .xp/ scope.
CONFIG_PATCH = """diff --git a/.xp/config.yml b/.xp/config.yml
--- a/.xp/config.yml
+++ b/.xp/config.yml
@@ -3,3 +3,4 @@
 tests:
   story: true
   full: true
+  fast: true
"""
CONSTRAINTS_PATCH = """diff --git a/.xp/constraints.md b/.xp/constraints.md
--- a/.xp/constraints.md
+++ b/.xp/constraints.md
@@ -1,2 +1,3 @@
 # Constraints
 1. CONSTRAINT-SENTINEL
+2. sneaky
"""
RENAME_OUT_PATCH = """diff --git a/.xp/constraints.md b/src/moved.md
similarity index 100%
rename from .xp/constraints.md
rename to src/moved.md
"""
NEW_FILE_PATCH = """diff --git a/src/fixed.py b/src/fixed.py
new file mode 100644
--- /dev/null
+++ b/src/fixed.py
@@ -0,0 +1 @@
+F = 1
"""


def stream_json(result: str, session: str = "sess-stub") -> str:
    """What `claude --output-format stream-json --verbose` actually emits: a
    session-bearing init event, then the terminal result envelope. A stub writing
    the bare `{"result": ...}` object models no harness that exists, and a parser
    widened to accept it would call any event carrying that key the end of a run.
    """
    return "".join(
        json.dumps(e) + "\n"
        for e in (
            {"type": "system", "subtype": "init", "session_id": session},
            {"type": "result", "subtype": "success", "is_error": False, "result": result},
        )
    )


def stub_reviewer(tmp_path, result="findings above", exit_code=0, raw=None, report=..., patch=""):
    """A fake `claude` that APPENDS one JSONL record per launch.

    Append, not overwrite: an overwriting stub makes "the reviewer was not
    launched again" pass vacuously by re-reading the previous launch's record.

    `report` is what a REAL reviewer does under story-012a: find the REPORT_PATH
    line in the bundle and write its findings there. Defaults to a clean report,
    since most tests here are about what happens AFTER a review. Pass a dict for
    specific findings, a str for malformed JSON, None to write nothing at all (the
    prose-only reviewer, which the pipeline must refuse).
    """
    if report is ...:
        report = {"fixed": [], "blocking": [], "noted": []}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launches.jsonl"
    payload = raw if raw is not None else stream_json(result)
    body = report if isinstance(report, str) or report is None else json.dumps(report)
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']: sys.exit(1)\n"
        "stdin = sys.stdin.read()\n"
        f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'stdin': stdin}) + '\\n')\n"
        f"body = {body!r}\n"
        "if body is not None:\n"
        "    m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M)\n"
        "    assert m, 'the bundle named no REPORT_PATH'\n"
        "    open(m.group(1).strip(), 'w').write(body)\n"
        f"patch = {patch!r}\n"
        "m = re.search(r'^PATCH_PATH: (.+)$', stdin, re.M)\n"
        "if m:\n"
        "    open(m.group(1).strip(), 'w').write(patch)\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir


def launches(tmp_path):
    rec = tmp_path / "launches.jsonl"
    return [json.loads(ln) for ln in rec.read_text().splitlines()] if rec.exists() else []


def marker(tmp_path, story_id="story-042"):
    return json.loads((tmp_path / "data" / "markers" / f"{story_id}.close.json").read_text())


def marker_file(tmp_path, story_id="story-042"):
    return tmp_path / "data" / "markers" / f"{story_id}.close.json"


def ready_marker(tmp_path, story_id="story-042"):
    return tmp_path / "data" / "markers" / f"{story_id}.ready.json"


def mint_ready(repo, env, story_id="story-042"):
    """Clear a card through the REAL leg, then flip to [in-progress] as spawn does.
    Re-run it after a test edits a card it intends to land: an edit that outruns
    its credential is exactly what land refuses."""
    plan = Path(env["XP_DATA"]) / "plan.md"
    for was in ("ready", "in-progress"):
        plan.write_text(flip_status(plan.read_text(), f"#### {story_id} ", was, "planned"))
    minted = subprocess.run(
        [sys.executable, str(SPAWN), "ready", story_id],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert minted.returncode == 0, minted.stderr
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(flip_status(plan.read_text(), f"#### {story_id} ", "ready", "in-progress"))


def make_repo(
    tmp_path,
    status="in-progress",
    verify="true",
    branch="main",
    teardown=None,
    bootstrap=None,
    teardown_timeout=None,
    system=True,
):
    repo = tmp_path / "repo"
    templates = Path(os.environ["XP_TEST_REPO_TEMPLATES"])
    full = (
        status == "in-progress"
        and verify == "true"
        and branch == "main"
        and teardown is None
        and bootstrap is None
        and teardown_timeout is None
        and system
        and (templates / "close-full").is_dir()
    )
    shutil.copytree(templates / ("close-full" if full else "close"), repo)
    if not full:
        (repo / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
        (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    plan = tmp_path / "data" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    # [planned] first, then MINTED: a typed bracket walks past the one gate binding
    # the card's Verify commands to the reviewed text.
    landing = status == "in-progress"
    plan.write_text(CARD.format(status="planned" if landing else status, verify=verify))
    if full:
        mint_ready(repo, env)
        return repo, env, g
    timeout = f"teardown_timeout: {teardown_timeout}\n" if teardown_timeout is not None else ""
    (repo / ".xp" / "config.yml").write_text(CONFIG + timeout)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    if system:
        lines = ["# System", "SYSTEM-SENTINEL"]
        if bootstrap is not None:
            lines.append(f"**Worktree bootstrap**: {bootstrap}")
        if teardown is not None:
            lines.append(f"**Worktree teardown**: {teardown}")
        (repo / ".xp" / "system.md").write_text("\n".join(lines) + "\n")
    if landing:
        mint_ready(repo, env)
    (repo / "VALUES.md").write_text("# XP Values\nVALUES-SENTINEL\n")
    (repo / "src").mkdir()
    (repo / "src" / "thing.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "story-042-branch")
    (repo / "src" / "thing.py").write_text("A = 2\n")
    g("add", "-A")
    g("commit", "-qm", "story work")
    return repo, env, g


def worktree_land_setup(tmp_path, verify="true", **repo_options):
    repo, env, g = make_repo(tmp_path, verify=verify, **repo_options)
    assert close(repo, env, "review").returncode == 0
    tree = tmp_path / "wt"
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    g("checkout", "-q", "main")
    g("worktree", "add", str(tree), branch)
    return repo, env, g, tree, branch


def close_bare(repo, env, *args):
    """The invocation the skills actually document: no --merge-mode."""
    return subprocess.run(
        [sys.executable, str(CLOSE), "story", "story-042", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def close(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(CLOSE), "story", "story-042", *args, "--merge-mode", "local"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def prose(path: Path) -> str:
    """File text with whitespace collapsed. A prose pin that breaks when a
    paragraph is rewrapped tests the line breaks, not the rule."""
    return " ".join(path.read_text().split())


def free_repo(tmp_path):
    """make_repo, plus what a RELEASE needs: an origin, a gh recorder, a semver
    tag to bump off, and both tier keys. HEAD is left on main — free start's own
    precondition, which make_repo does not leave."""
    repo, env, g = make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    g("remote", "add", "origin", str(origin))
    g("checkout", "-q", "main")
    (repo / ".xp" / "config.yml").write_text(CONFIG + "  full: true\n")
    g("add", "-A")
    g("commit", "-qm", "release setup")
    g("tag", "v0.2.0")
    g("push", "-q", "-u", "origin", "main")
    gh = tmp_path / "bin" / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(tmp_path / 'gh.jsonl')!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    gh.chmod(0o755)
    return repo, env, g


def gh_calls(tmp_path):
    rec = tmp_path / "gh.jsonl"
    return [json.loads(ln) for ln in rec.read_text().splitlines()] if rec.exists() else []


def free(repo, env, slug, *args):
    return subprocess.run(
        [sys.executable, str(CLOSE), "free", slug, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
