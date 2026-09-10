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
    rendered, argv = command(text, "close.py")
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
    repo, env, g, tree, _marker = stopped_story(tmp_path)
    assert g("checkout", "-q", "main").returncode == 0
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

    assert second.returncode == 2 and "no commits" in second.stderr.lower(), second.stderr
    second_close = close_from_named_tree(second.stderr, env)
    assert second_close.returncode == 0, second_close.stderr
    command(second.stderr, "spawn.py")


def test_a_free_recovery_takes_its_close_noun_from_leg(monkeypatch):
    story_id = "free-2026-09-10-fix-typo"
    calls = []

    def recording_leg(key):
        calls.append(key)
        return leg(key)

    monkeypatch.setattr(resume_module, "leg", recording_leg, raising=False)

    rendered = resume_module.handback_recovery(Path("/tmp/inherited-tree"), story_id)

    _text, argv = command(rendered, "close.py")
    assert calls == [story_id]
    assert argv == ["close.py", *leg(story_id)[0].split(), "review"]
