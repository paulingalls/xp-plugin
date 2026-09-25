import json
import shlex
import sys

import pytest
from spawn_helpers import make_repo, spawn


def fixture(tmp_path, outcomes=(0,), tier="configured", commit_second=True, litter=False):
    repo, env, git = make_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    tier_script = tmp_path / "tier.py"
    tier_script.write_text(
        "import json, os, pathlib, sys\n"
        f"path = pathlib.Path({str(events)!r})\n"
        "events = [json.loads(line) for line in path.read_text().splitlines()] "
        "if path.exists() else []\n"
        "runs = sum(event['kind'] == 'tier' for event in events)\n"
        "with path.open('a') as out:\n"
        " out.write(json.dumps({'kind': 'tier', 'cwd': os.getcwd()}) + '\\n')\n"
        f"if {litter!r}: open('tier-report.xml', 'w').write('untracked')\n"
        f"print('TIER-RED-' + str(runs + 1))\n"
        f"sys.exit(({tuple(outcomes)!r})[min(runs, {len(outcomes) - 1})])\n"
    )
    command = shlex.join([sys.executable, str(tier_script)])
    cfg = repo / ".xp/config.yml"
    if tier == "configured":
        cfg.write_text(cfg.read_text().replace("  story: true", "  story: false"))
    elif tier == "edit-me":
        cfg.write_text(cfg.read_text().replace("  story: true", "  story: EDIT-ME"))
    else:
        cfg.write_text(cfg.read_text().replace("  story: true\n", ""))
    assert git("commit", "-aqm", "lead config").returncode == 0
    assert git("branch", "-f", "main", "HEAD").returncode == 0
    binary = tmp_path / "bin/claude"
    binary.parent.mkdir(exist_ok=True)
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, subprocess, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read(); role = os.environ['XP_ROLE']\n"
        f"path = {str(events)!r}\n"
        "events = [json.loads(line) for line in open(path)] if os.path.exists(path) else []\n"
        "attempt = sum(event['kind'] == 'teammate' for event in events) + 1\n"
        "with open(path, 'a') as out:\n"
        " out.write(json.dumps({'kind': role, 'cwd': os.getcwd(), 'prompt': prompt}) + '\\n')\n"
        "if role == 'teammate':\n"
        f" if attempt == 1 and {tier == 'configured'!r}:\n"
        "  config = '.xp/config.yml'\n"
        f"  text = open(config).read().replace('  story: false', '  story: {command}')\n"
        "  open(config, 'w').write(text)\n"
        f" if attempt != 2 or {commit_second!r}:\n"
        "  os.makedirs('src', exist_ok=True)\n"
        "  open('src/thing.py', 'a').write('\\nDONE = True\\n')\n"
        "  subprocess.run(['git', 'add', 'src', '.xp'], check=True)\n"
        "  subprocess.run(['git', 'commit', '-qm', 'executor work'], check=True)\n"
        "elif role == 'reviewer':\n"
        " p = re.search(r'^REPORT_PATH: (.+)$', prompt, re.M); assert p\n"
        " report = {'fixed': [], 'blocking': [], 'noted': []}\n"
        " open(p.group(1).strip(), 'w').write(json.dumps(report))\n"
        "print(json.dumps({'type':'result','subtype':'success','result':'done'}))\n"
    )
    binary.chmod(0o755)
    return repo, env, events, command


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def marker(tmp_path):
    return json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())


def test_red_tier_retries_with_tree_command_and_output_then_reviews(tmp_path):
    repo, env, path, command = fixture(tmp_path, outcomes=(1, 0))
    result = spawn(repo, env, "story-042")
    events = read_events(path)
    assert result.returncode == 0, result.stderr
    assert [e["kind"] for e in events] == ["teammate", "tier", "teammate", "tier", "reviewer"]
    assert command in events[2]["prompt"] and "TIER-RED-1" in events[2]["prompt"]
    assert all(e["cwd"] == str(tmp_path / "data/worktrees/story-042") for e in events)
    assert marker(tmp_path)["stages"]["story-tier"] == "ran"


def test_second_red_refuses_without_third_executor(tmp_path):
    repo, env, path, command = fixture(tmp_path, outcomes=(1, 1))
    result = spawn(repo, env, "story-042")
    events = read_events(path)
    assert result.returncode == 2
    assert [e["kind"] for e in events] == ["teammate", "tier", "teammate", "tier"]
    assert command in result.stderr and "spawn.py resume" in result.stderr
    assert str(tmp_path / "data/worktrees/story-042") in result.stderr
    assert marker(tmp_path)["state"] == "STOPPED"
    assert marker(tmp_path)["stages"]["story-tier"] == "failed"


def test_retry_requires_its_own_commit(tmp_path):
    repo, env, path, _command = fixture(tmp_path, outcomes=(1, 0), commit_second=False)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 2
    assert [e["kind"] for e in read_events(path)] == ["teammate", "tier", "teammate"]
    assert "no commits of its own" in result.stderr
    assert "git worktree remove" not in result.stderr


def test_retry_tolerates_what_the_tier_run_left_untracked(tmp_path):
    repo, env, path, _command = fixture(tmp_path, outcomes=(1, 0), litter=True)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert [e["kind"] for e in read_events(path)][-1] == "reviewer"


def test_unrunnable_tier_stops_without_a_second_executor(tmp_path):
    repo, env, path, command = fixture(tmp_path, outcomes=(127,))
    result = spawn(repo, env, "story-042")
    assert result.returncode == 2
    assert [e["kind"] for e in read_events(path)] == ["teammate", "tier"]
    assert "story tier unrunnable" in result.stderr and command in result.stderr


@pytest.mark.parametrize("last,expected", [(0, 0), (1, 2)])
def test_resume_uses_same_bounded_tier_gate(tmp_path, last, expected):
    repo, env, path, command = fixture(tmp_path, outcomes=(1, 1, 1, last))
    first = spawn(repo, env, "story-042")
    assert first.returncode == 2
    resumed = spawn(repo, env, "resume", "story-042")
    events = read_events(path)
    assert resumed.returncode == expected, resumed.stderr
    assert [e["kind"] for e in events] == [
        "teammate",
        "tier",
        "teammate",
        "tier",
        "teammate",
        "tier",
        "teammate",
        "tier",
        *(["reviewer"] if last == 0 else []),
    ]
    assert command in events[6]["prompt"] and "TIER-RED-3" in events[6]["prompt"]
    assert marker(tmp_path)["stages"]["story-tier"] == ("ran" if last == 0 else "failed")


@pytest.mark.parametrize("tier", ["unset", "edit-me"])
def test_unavailable_tier_is_recorded_and_reviewer_runs(tmp_path, tier):
    repo, env, path, _command = fixture(tmp_path, tier=tier)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert [e["kind"] for e in read_events(path)] == ["teammate", "reviewer"]
    assert "no story tier ran" in result.stdout.lower()
    assert f"tests.story is {'unset' if tier == 'unset' else 'EDIT-ME'}" in result.stdout
    assert marker(tmp_path)["stages"]["story-tier"] == "skipped"
