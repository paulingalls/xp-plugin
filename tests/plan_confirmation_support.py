"""Real spawn fixtures with independent plan-review results."""

import json
import subprocess

from spawn_helpers import make_repo, set_system_md, spawn
from test_plan_findings_handoff import staged_harness

QUESTION = "Which lease value does the human authorize?"
REASON = "Honesty prevents silent loss by retaining the lease guard."


def consumer(
    tmp_path,
    harness="claude",
    initial_status="edited",
    initial_question=QUESTION,
    dirty=False,
):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    seen = staged_harness(tmp_path)
    binary = tmp_path / "bin/claude"
    text = binary.read_text()
    start = text.index("elif role == 'plan-reviewer':")
    end = text.index("elif role == 'teammate':")
    initial = dict(
        status=initial_status,
        human_question=initial_question,
        reasons=[] if initial_status == "clean" else [REASON],
        summary="",
    )
    text = (
        text[:start]
        + (
            "elif role == 'plan-reviewer':\n"
            " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
            " draft = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M).group(1)\n"
            " if 'replacement requested' in open(draft).read():\n"
            "  verdict = dict(status='clean', human_question=None, reasons=[], "
            "summary='replacement reviewed')\n"
            " else:\n"
            f"  if {initial_status != 'clean'!r}:\n"
            f"   open(draft, 'a').write('guard retained\\nReason: {REASON}\\n')\n"
            f"  verdict = {initial!r}\n"
            " open(p.group(1), 'w').write(json.dumps(verdict))\n"
        )
        + text[end:]
    )
    text = text.replace(
        "open(p.group(1), 'a').write('# plan\\nrun diagnostic check\\n')",
        "open(p.group(1), 'w').write('# plan\\nlease = undecided\\n' + "
        "('replacement requested\\n' if os.path.exists("
        + repr(str(tmp_path / "replace"))
        + ") else ''))",
    )
    text = text.replace(
        "event['findings_path'] =",
        "event['draft'] = open(os.path.join(os.path.dirname(p.group(1)), "
        "'story-042.plan.md')).read()\n"
        " event['findings_path'] =",
    )
    if initial_question is None:
        text = text.replace(
            "elif role == 'teammate':",
            "elif role == 'teammate':\n if os.path.exists("
            + repr(str(tmp_path / "executor-stop"))
            + "): sys.exit(1)",
        )
        (tmp_path / "executor-stop").touch()
    if dirty:
        set_system_md(repo, "- Worktree bootstrap: `printf 'dirty baseline' > dirty.txt`")
        subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    text = text.replace(
        "if role == 'planner':",
        "if role == 'planner':\n",
    )
    binary.write_text(text)
    if harness == "codex":
        config = repo / ".xp/config.yml"
        config.write_text(config.read_text().replace("claude/", "codex/"))
        subprocess.run(
            ["git", "commit", "-am", "codex roles"],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
        text = text.replace(
            '[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]',
            '{"installed":[{"pluginId":"xp-plugin@xp-plugin","version":"fixture"}]}',
        )
        text = text.replace(
            "print(json.dumps({'type':'result','subtype':'success','result':'done'}))",
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}))\n"
            "print(json.dumps({'type':'turn.completed','usage':{}}))",
        )
        binary = tmp_path / "bin/codex"
        binary.write_text(text)
        binary.chmod(0o755)
    return repo, env, seen


def amend(tmp_path, repo, env, launch=spawn):
    card = tmp_path / "data/plan.md"
    card.write_text(
        card.read_text().replace("Context: demo.", "Context: human authorizes lease = 17.")
    )
    result = launch(repo, env, "amend", "story-042", "--reason", "human ruling: lease 17")
    assert result.returncode == 0, result.stderr


def events(seen):
    return [json.loads(line) for line in seen.read_text().splitlines()]


def submodule_consumer(tmp_path, harness):
    repo, env, seen = consumer(tmp_path, harness=harness)
    dependency = tmp_path / "dependency"
    subprocess.run(["git", "clone", "-q", str(repo), str(dependency)], env=env, check=True)
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(dependency), "vendor"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "commit", "-am", "add dependency"], cwd=repo, env=env, check=True)
    set_system_md(
        repo,
        "- Worktree bootstrap: `git -c protocol.file.allow=always submodule update --init "
        "&& printf baseline > vendor/runtime.cfg`",
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    return repo, env, seen


def late_launch(tmp_path, target, mutation=None, publication=False):
    import sys

    from plan_review_install import installed_launch

    installed_launch(tmp_path, mutation, "scripts/spawn/execution.py")
    scripts = tmp_path / "cache/xp-plugin/fixture/scripts"
    injection = """
import plan_acceptance, spawn
original = spawn.profile_report

def perturb(*args):
    result = original(*args)
    record = plan_acceptance.latest('story-042')
    if record:
        target = TARGET
        if target == 'findings':
            Path(record['findings']).write_text(Path(record['findings']).read_text() + ' ')
        elif target == 'lost-findings':
            Path(record['findings']).unlink()
        elif target == 'tree':
            from work import data_root
            path = data_root() / 'worktrees/story-042/.xp/system.md'
            path.write_text('late repository motion')
        elif target == 'card':
            from work import plan_path
            text = plan_path().read_text().replace('Context: demo.', 'Context: unreviewed scope.')
            plan_path().write_text(text)
        elif target == 'credential':
            from work import ready_marker_path
            ready_marker_path('story-042').write_text('{}')
    return result
spawn.profile_report = perturb
"""
    if publication:
        injection = """
import plan_acceptance, spawn
original = plan_acceptance.apply_card

def perturb(*args, **kwargs):
    result = original(*args, **kwargs)
    if plan_acceptance.latest('story-042'):
        Path('.xp/system.md').write_text('motion between card and credential publication')
    return result
plan_acceptance.apply_card = perturb
"""
    injection = injection.replace("TARGET", repr(target))

    def launch(repo, env, *args):
        code = (
            f"import sys; from pathlib import Path; sys.path[:0] = "
            f"[{str(scripts)!r}, {str(scripts / 'spawn')!r}]\n"
            + injection
            + '\nsys.argv = ["spawn.py", *sys.argv[1:]]\nraise SystemExit(spawn.main())'
        )
        return subprocess.run(
            [sys.executable, "-c", code, *args],
            cwd=repo,
            env=env | {"XP_SPAWN_TEST": "1"},
            capture_output=True,
            text=True,
        )

    return launch
