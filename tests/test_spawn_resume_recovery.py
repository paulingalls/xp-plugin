"""A resumed refusal offers both reachable routes after inherited work is committed."""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import resume as resume_module
from close import leg
from spawn_helpers import SPAWN, spawn, stub_claude
from test_spawn_resume import stopped_story


def command(text, executable):
    matches = [
        (rendered, shlex.split(rendered))
        for rendered in re.findall(r"`([^`]+)`", text)
        if shlex.split(rendered)[0] == executable
    ]
    assert len(matches) == 1, matches
    return matches[0]


def close_from_named_tree(text, env):
    rendered, argv = command(text, "xp.py")
    match = re.search(rf"`{re.escape(rendered)}` from (.+?);", text)
    assert match, text
    return subprocess.run(
        [sys.executable, str(SPAWN.parent / argv[0]), *argv[1:], "--dry-run"],
        cwd=Path(match.group(1)),
        env=env,
        capture_output=True,
        text=True,
    )


def test_each_resumed_refusal_executes_its_complete_route_and_the_first_drives_the_next_lap(
    tmp_path,
):
    repo, env, _g, tree, _marker = stopped_story(tmp_path)
    (tree / "work.py").write_text("inherited work\n")
    stub_claude(tmp_path, commit=False)

    first = spawn(repo, env, "resume", "story-042")

    assert first.returncode == 2 and "inherited takeover work" in first.stderr
    subprocess.run(["git", "add", "work.py"], cwd=tree, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "adopt inherited work"], cwd=tree, env=env, check=True)
    first_close = close_from_named_tree(first.stderr, env)
    assert first_close.returncode == 0, first_close.stderr
    _rendered, resume_argv = command(first.stderr, "spawn.py")

    second = spawn(repo, env, *resume_argv[1:])

    assert second.returncode == 0, second.stderr


def test_a_free_recovery_takes_its_close_noun_from_leg(monkeypatch):
    story_id = "free-2026-09-10-fix-typo"
    calls = []

    def recording_leg(key):
        calls.append(key)
        return leg(key)

    monkeypatch.setattr(resume_module, "leg", recording_leg, raising=False)

    rendered = resume_module.handback_recovery(Path("/tmp/inherited-tree"), story_id)

    _text, argv = command(rendered, "xp.py")
    assert calls == [story_id]
    assert argv == ["xp.py", "free", "fix-typo", "review"]


def test_lead_recovery_is_not_an_executor_assignment(tmp_path):
    import json

    repo, env, _g, tree, marker = stopped_story(tmp_path)
    state = json.loads(marker.read_text())
    recovery = resume_module.handback_recovery(tree, "story-042")
    _rendered, recovery_argv = command(recovery, "spawn.py")
    state["why"] = "REQUIREMENT-FAILURE: required.txt is absent. " + recovery
    marker.write_text(json.dumps(state))
    binary = tmp_path / "bin/claude"
    stub_claude(tmp_path, commit=False)
    source = binary.read_text()
    point = "if spawn_review:\n"
    recovery_pattern = r"\s+".join(map(re.escape, recovery_argv))
    probe = (
        "import re\n"
        "if not spawn_review:\n"
        " assignment = re.sub(r'<predecessor-evidence>.*?</predecessor-evidence>', "
        "'', stdin, flags=re.S)\n"
        " assert 'REQUIREMENT-FAILURE' in stdin\n"
        f" if re.search({recovery_pattern!r}, assignment):\n"
        f"  p = subprocess.run([{sys.executable!r}, {str(SPAWN)!r}, 'resume', "
        "'story-042'], capture_output=True, text=True)\n"
        f"  open({str(tmp_path / 'lifecycle-attempt')!r}, 'w').write(p.stderr)\n"
        "  sys.exit(1)\n"
        " open('required.txt', 'w').write('implemented')\n"
        " subprocess.run(['git', 'add', 'required.txt'], check=True)\n"
        " subprocess.run(['git', 'commit', '-qm', 'repair requirement'], check=True)\n"
    )
    binary.write_text(source.replace(point, probe + point))
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert (tree / "required.txt").read_text() == "implemented"
    assert not (tmp_path / "lifecycle-attempt").exists()
