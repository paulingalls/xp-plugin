"""Shared fixtures for the test_spawn family.
Split at sprint-004 open: tests are production code (constraint 8)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SPAWN = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "spawn.py"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: {files}
AC:
- Given X, When Y, Then Z
Verify: true
Executor: {executor}
"""

CONFIG = """release: sprint
roles:
  lead: claude/opus
  planner: claude/haiku/low
  executor: claude/sonnet/medium
  reviewer: claude/opus
  plan-reviewer: claude/opus

tests:
  story: true
"""


def make_repo(tmp_path, status="ready", executor="(default)", trunk="main", files="src/thing.py"):
    """A repo whose HEAD is NOT the integration target, with a divergent commit:
    a spawn that omits the base argument branches off HEAD and the test reds."""
    repo = tmp_path / "repo"
    templates = Path(os.environ["XP_TEST_REPO_TEMPLATES"])
    full = (
        status == "ready"
        and executor == "(default)"
        and trunk == "main"
        and (templates / "spawn-full").is_dir()
    )
    shutil.copytree(templates / ("spawn-full" if full else "spawn"), repo)
    if not full:
        (repo / ".git" / "HEAD").write_text(f"ref: refs/heads/{trunk}\n")
        (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    plan = tmp_path / "data" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        CARD.format(
            status="planned" if status == "ready" else status, executor=executor, files=files
        )
    )
    (plan.parent / "sprint_branch").write_text(f"{trunk}\n")
    if full:
        minted = spawn(repo, env, "ready", "story-042")
        assert minted.returncode == 0, minted.stderr
        return repo, env, g
    (repo / ".xp" / "config.yml").write_text(CONFIG)
    if status == "ready":
        # MINTED, never typed: a fixture that writes [ready] by hand hands out the
        # forgery story-023 removed, and every test below it stops walking the real
        # sequence (constraint 12). The forgery has its own test.
        minted = spawn(repo, env, "ready", "story-042")
        assert minted.returncode == 0, minted.stderr
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\n- Worktree bootstrap: none needed\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "elsewhere")
    (repo / "drift.txt").write_text("HEAD is not the trunk\n")
    g("add", "-A")
    g("commit", "-qm", "divergent")
    return repo, env, g


def stub_claude(
    tmp_path,
    commit=True,
    emit_result=True,
    write_file=False,
    add_all=True,
    break_git=False,
    execute_escalation=False,
):
    """A fake `claude` that records argv, env and stdin, then (by default)
    commits its own "work" and emits a stream-json terminal result object —
    the shape of a clean, successful teammate run. The other three knobs
    produce the shapes TestTeammateCompletion's guard must catch:
    `write_file` alone leaves an UNCOMMITTED file (dirty tree); `commit=False,
    write_file=False` leaves the tree clean but with NO commit of its own —
    the two injections the completion guard's AC calls for.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, shlex, subprocess, sys",
        "if sys.argv[1:] == ['plugin', 'list', '--json']: print("
        '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()',
        "argv = sys.argv[1:]",
        "stdin = sys.stdin.read()",
        # BEHAVIOUR follows the role AND the bundle, never XP_ROLE alone: a stub
        # that commits while asked to be the reviewer reds as "the read-only
        # reviewer changed HEAD" three files away, but XP_ROLE is INHERITED from
        # whatever agent runs the suite, and a story-reviewer running it turned two
        # tests that drive this stub bare red. RECORDING still follows the test
        # flag: the reviewer launch must not clobber the teammate's record inside a
        # spawn run, while the close-review leg's own tests read that same record.
        "spawn_review = os.environ.get('XP_ROLE') == 'reviewer' and 'REPORT_PATH: ' in stdin",
        "keep_record = not (os.environ.get('XP_SPAWN_TEST') and spawn_review)",
        f"record = {{'argv': argv, 'env': dict(os.environ), 'stdin': stdin}}; path = {str(rec)!r}",
        "json.dump(record, open(path, 'w')) if keep_record else None",
        "if spawn_review:",
        " import re",
        " match = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M); assert match",
        " report = {'fixed': [], 'blocking': [], 'noted': []}",
        " open(match.group(1).strip(), 'w').write(json.dumps(report))",
    ]
    if execute_escalation:
        body += [
            # not as the reviewer: its bundle carries no escalation line, and the
            # unguarded next() exits 1 as "reviewer exited 1" two files away.
            "line = next((ln for ln in stdin.splitlines() "
            "if ln.startswith('  File it: `')), None) if not spawn_review else None",
            "command = line.split('`', 2)[1].replace(\"'...'\", \"'fixture'\") if line else None",
            f"subprocess.run([{sys.executable!r}, *shlex.split(command)[1:]], check=True)"
            " if command else None",
        ]
    if write_file:
        body.append("open('teammate-left-this-uncommitted.txt', 'w').write('oops')")
    if commit:
        # add -A, not --allow-empty alone: a real teammate's "done" commit
        # picks up whatever it left in the tree, bootstrap byproducts included
        # — except with add_all=False, which is the teammate that stages only
        # its own files and leaves a pre-existing leftover where it found it
        if add_all:
            body.append("subprocess.run(['git', 'add', '-A']) if not spawn_review else None")
        body.append(
            "subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'teammate work'])"
            " if not spawn_review else None"
        )
    if break_git:
        body.append("open('.git', 'w').write('not a gitdir pointer')")
    if emit_result:
        body += [
            "event = {'type': 'result', 'num_turns': 3, 'duration_ms': 1200,"
            " 'total_cost_usd': 0.05, 'is_error': False}",
            "event['result'] = json.dumps(report) if spawn_review else ''",
            "print(json.dumps(event))",
        ]
    (bin_dir / "claude").write_text("\n".join(body) + "\n")
    (bin_dir / "claude").chmod(0o755)
    return rec


def spawn(repo, env, *args):
    env = dict(env, XP_SPAWN_TEST="1")
    return subprocess.run(
        [sys.executable, str(SPAWN), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def trunk_sha(repo, env, trunk="main"):
    return subprocess.run(
        ["git", "rev-parse", f"refs/heads/{trunk}"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()


def in_tree(tree, env, *args):
    return subprocess.run(
        ["git", *args], cwd=tree, env=env, capture_output=True, text=True
    ).stdout.strip()


def block_commits(repo):
    """A red pre-commit in the COMMON dir — worktrees share it, and lefthook
    installs exactly here, so this is the live configuration, not a contrivance."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'fast tests red' >&2\nexit 1\n")
    hook.chmod(0o755)


def set_system_md(repo, line):
    (repo / ".xp" / "system.md").write_text(f"# System\n{line}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "system.md"],
        cwd=repo,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent)},
    )


def stub_claude_requiring_verbose(tmp_path):
    """Mimics the REAL refusal measured at story-017's plan review: the
    installed `claude` binary exits 1 on `--output-format stream-json` without
    `--verbose`. `stub_claude` above accepts any argv, so only a stub shaped
    like this one can catch a regression back to the old, unshippable argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / "claude-real-refusal"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "if ('--output-format' in argv and argv[argv.index('--output-format') + 1] =="
        " 'stream-json' and '--verbose' not in argv):\n"
        "    print('error: --output-format stream-json requires --verbose', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        'print(\'{"type": "result", "is_error": false, "num_turns": 1}\')\n'
    )
    path.chmod(0o755)
    return path


def _total(stdout):
    for ln in stdout.splitlines():
        if ln.startswith("profile:"):
            return int(ln.split("total ", 1)[1].split(" ", 1)[0])
    raise AssertionError(f"no profile line in: {stdout[:200]}")


def stub_codex(
    tmp_path,
    commit=True,
    write_file=False,
    report=None,
    prose=("thinking", "done"),
    sandbox=None,
    findings=None,
):
    """A fake `codex` that REJECTS what the real binary rejects.

    story-017's measured loss, inherited verbatim by story-021's card: stub_claude
    accepted any argv, so the suite would have shipped a spawn that died on
    contact. This one exits 2 on an argv that DISABLES unified_exec — the
    polarity flipped when the disablement did (bug 296c3e4f), so re-adding the
    flag reds a test instead of silently costing the teammate its plan review —
    and on the claude spellings, which is what stops the two legs' argv from
    silently fusing.

    `sandbox`: the `--sandbox` value this leg must launch under. The stub dies
    when the argv carries a different one, in EITHER direction, so a confining
    posture returning reds against a real launch instead of against an argv
    assertion. None asserts nothing.

    `report`: the reviewer shape. Its dict is written to the bundle's REPORT_PATH
    THROUGH `sh -c`, per the AC — the report lives outside the workspace, so the
    thing under test is that a shell in the sandbox can reach it.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, re, subprocess, sys",
        "argv = sys.argv[1:]",
        "if argv == ['plugin', 'list', '--json']: print("
        '\'{"installed":[{"pluginId":"xp-plugin@xp-plugin",'
        '"version":"fixture"}]}\'); sys.exit()',
        "def die(m):",
        "    print('error: ' + m, file=sys.stderr); sys.exit(2)",
        "if argv[:1] != ['exec']: die('unrecognized subcommand')",
        # NOT -p: `codex exec -p` is --profile, and a stub that refuses what the real
        # binary accepts teaches the next author a bound that is not there. The claude
        # spellings below are the fusion this catches.
        "for flag in ('-e', '--plugin-dir', '--output-format', '--verbose'):",
        "    if flag in argv: die('unexpected argument ' + flag)",
        "pairs = list(zip(argv, argv[1:]))",
        "if ('--disable', 'unified_exec') in pairs:",
        "    die('unified_exec disabled: no tool call here can outlive the shell bound')",
        "posture = argv[argv.index('--sandbox') + 1] if '--sandbox' in argv else ''",
        f"want = {sandbox!r}",
        "if want is not None and posture != want:",
        "    die('launched under sandbox ' + (posture or '(none)') + ', want ' + want)",
        "stdin = sys.stdin.read()",
        # BEHAVIOUR follows the role AND the bundle, never XP_ROLE alone: a stub
        # that commits while asked to be the reviewer reds as "the read-only
        # reviewer changed HEAD" three files away, but XP_ROLE is INHERITED from
        # whatever agent runs the suite, and a story-reviewer running it turned two
        # tests that drive this stub bare red. RECORDING still follows the test
        # flag: the reviewer launch must not clobber the teammate's record inside a
        # spawn run, while the close-review leg's own tests read that same record.
        "spawn_review = os.environ.get('XP_ROLE') == 'reviewer' and 'REPORT_PATH: ' in stdin",
        "keep_record = not (os.environ.get('XP_SPAWN_TEST') and spawn_review)",
        f"record = {{'argv': argv, 'env': dict(os.environ), 'stdin': stdin}}; path = {str(rec)!r}",
        "json.dump(record, open(path, 'w')) if keep_record else None",
    ]
    if report is None:
        body += [
            "if spawn_review:",
            " m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M); assert m",
            ' open(m.group(1).strip(), \'w\').write(\'{"fixed":[],"blocking":[],"noted":[]}\')',
        ]
    if report is not None:
        body += [
            "m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M)",
            "assert m, 'the bundle named no REPORT_PATH'",
            f"subprocess.run(['sh', '-c', 'cat > \"$1\"', 'sh', m.group(1).strip()],"
            f" input={json.dumps(report)!r}, text=True, check=True)",
        ]
    if findings is not None:
        body += [
            "m = re.search(r'^FINDINGS_PATH: (.+)$', stdin, re.M)",
            "assert m, 'the bundle named no FINDINGS_PATH'",
            f"open(m.group(1).strip(), 'w').write({findings!r})",
        ]
    if write_file:
        body.append("open('teammate-left-this-uncommitted.txt', 'w').write('oops')")
    if commit:
        body.append("subprocess.run(['git', 'add', '-A']) if not spawn_review else None")
        body.append(
            "subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'teammate work'])"
            " if not spawn_review else None"
        )
    body += [
        "if '--json' not in argv: die('native JSON stream was not requested')",
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'stub-thread'}))",
    ]
    body += [
        f"print(json.dumps({{'type': 'item.completed', 'item':"
        f" {{'type': 'agent_message', 'text': {line!r}}}}}))"
        for line in prose
    ]
    (bin_dir / "codex").write_text("\n".join(body) + "\n")
    (bin_dir / "codex").chmod(0o755)
    claude = bin_dir / "claude"
    if not claude.exists():
        claude.write_text(
            "#!/usr/bin/env python3\n"
            "import json, re, sys\n"
            "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
            ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\'); sys.exit()\n'
            "stdin = sys.stdin.read(); "
            "p = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M); assert p\n"
            "report = {'fixed': [], 'blocking': [], 'noted': []}\n"
            "open(p.group(1).strip(), 'w').write(json.dumps(report))\n"
            "print(json.dumps({'type':'result','result':json.dumps(report)}))\n"
        )
        claude.chmod(0o755)
    return rec
