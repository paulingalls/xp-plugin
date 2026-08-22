"""Shared fixtures for the test_close family.
Split at sprint-004 open: tests are production code
(constraint 8), and test_close.py measured 2,059 lines."""

import json
import subprocess
import sys
from pathlib import Path

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"

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


def stub_reviewer(tmp_path, result="findings above", exit_code=0, raw=None, report=...):
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
    payload = raw if raw is not None else json.dumps({"result": result})
    body = report if isinstance(report, str) or report is None else json.dumps(report)
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "stdin = sys.stdin.read()\n"
        f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'stdin': stdin}) + '\\n')\n"
        f"body = {body!r}\n"
        "if body is not None:\n"
        "    m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M)\n"
        "    assert m, 'the bundle named no REPORT_PATH'\n"
        "    open(m.group(1).strip(), 'w').write(body)\n"
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


def make_repo(tmp_path, status="in-progress", verify="true", branch="main"):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    g("init", "-q", "-b", branch)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    plan = tmp_path / "data" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(CARD.format(status=status, verify=verify))
    (repo / ".xp" / "config.yml").write_text(CONFIG)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
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
    tag to bump off, and a full tier. HEAD is left on main — free start's own
    precondition, which make_repo does not leave."""
    repo, env, g = make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    g("remote", "add", "origin", str(origin))
    g("checkout", "-q", "main")
    (repo / ".xp" / "config.yml").write_text(CONFIG + "  full: true\n")
    g("add", "-A")
    g("commit", "-qm", "full tier")
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
