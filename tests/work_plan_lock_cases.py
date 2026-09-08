"""Plan-writer cases collected through test_work_plan.py."""

import fcntl
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from close import story_card  # noqa: E402
from work import card_digest  # noqa: E402

PLAN = """# Plan

#### story-aaa — first   [ready]
Files: a.py
#### story-bbb — second   [ready]
Files: b.py
"""

CORRECT_WRITER = """
import sys, time
sys.path.insert(0, {scripts!r})
from work import edit_plan
story, nap = sys.argv[1], float(sys.argv[2])
def mutate(text):
    time.sleep(nap)
    return text.replace("#### " + story + " — ", "#### " + story + " DONE — ")
edit_plan(mutate)
"""

READ_OUTSIDE_LOCK_WRITER = """
import fcntl, sys, time
sys.path.insert(0, {scripts!r})
from work import plan_path, data_root
story, rendezvous = sys.argv[1], sys.argv[2]
path = plan_path()
text = path.read_text()
import pathlib
pathlib.Path(rendezvous + "." + story).write_text("read")
while len(list(pathlib.Path(rendezvous).parent.glob("rv.*"))) < 2:
    time.sleep(0.01)
lock = data_root() / "locks" / "plan.lock"
lock.parent.mkdir(parents=True, exist_ok=True)
with open(lock, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    path.write_text(text.replace("#### " + story + " — ", "#### " + story + " DONE — "))
"""

EVENT_WRITER = """
import os, pathlib, sys, time
sys.path.insert(0, {scripts!r})
from work import edit_plan
acquired, release, mode = map(pathlib.Path, sys.argv[1:])
def mutate(text):
    acquired.write_text("held")
    if str(mode) == "die": os._exit(7)
    while not release.exists(): time.sleep(0.01)
    return text.replace("story-aaa —", "story-aaa HELD —")
edit_plan(mutate)
"""


@pytest.fixture
def plan_data(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN)
    return tmp_path


def writer(src, data, *args, capture=False):
    return subprocess.Popen(
        [sys.executable, "-c", src.format(scripts=str(SCRIPTS)), *map(str, args)],
        env={"XP_DATA": str(data), "PATH": "/usr/bin:/bin"},
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=capture,
    )


def lock_is_held(data):
    lock = Path(data) / "locks" / "plan.lock"
    if not lock.exists():
        return False
    with open(lock, "r") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def await_path(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def candidate(data, story="story-bbb", change="b.py", replacement="fresh.py"):
    card, status = story_card((data / "plan.md").read_text(), story)
    path = data / f"{story}.card"
    path.write_text(card.replace(change, replacement))
    return path, card_digest(card), status


def editor(data, story="story-bbb", path=None, digest=None, status=None, popen=False):
    if path is None:
        path, digest, status = candidate(data, story)
    argv = [
        sys.executable,
        str(SCRIPTS / "work.py"),
        "edit-card",
        story,
        "--digest",
        digest,
        "--status",
        status,
        str(path.resolve()),
    ]
    kwargs = {
        "env": {"XP_DATA": str(data), "PATH": "/usr/bin:/bin"},
        "capture_output": True,
        "text": True,
    }
    return (
        subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=kwargs["env"]
        )
        if popen
        else subprocess.run(argv, **kwargs)
    )


@pytest.mark.slow
class TestConcurrentWriters:
    def test_both_flips_survive_when_writers_overlap(self, plan_data):
        a = writer(CORRECT_WRITER, plan_data, "story-aaa", 2)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not lock_is_held(plan_data):
            time.sleep(0.01)
        assert lock_is_held(plan_data), "writer A never took the lock"
        b = writer(CORRECT_WRITER, plan_data, "story-bbb", 0)
        assert a.wait(30) == 0 and b.wait(30) == 0
        final = (plan_data / "plan.md").read_text()
        assert "story-aaa DONE" in final and "story-bbb DONE" in final

    def test_a_read_outside_the_lock_loses_a_flip(self, plan_data):
        rv = plan_data / "rv"
        a = writer(READ_OUTSIDE_LOCK_WRITER, plan_data, "story-aaa", rv)
        b = writer(READ_OUTSIDE_LOCK_WRITER, plan_data, "story-bbb", rv)
        assert a.wait(30) == 0 and b.wait(30) == 0
        final = (plan_data / "plan.md").read_text()
        assert ("story-aaa DONE" in final) != ("story-bbb DONE" in final)


class TestPlanCardEditor:
    @pytest.mark.parametrize("fault", ["status", "extra", "stale"])
    def test_refuses_invalid_or_stale_candidates_and_names_refresh(self, plan_data, fault):
        path, digest, status = candidate(plan_data)
        if fault == "status":
            path.write_text(path.read_text().replace("[ready]", "[done]"))
        elif fault == "extra":
            path.write_text(path.read_text() + story_card(PLAN, "story-aaa")[0])
        else:
            digest = "0" * 16
        before = (plan_data / "plan.md").read_text()
        result = editor(plan_data, path=path, digest=digest, status=status)
        if fault == "extra" and result.returncode == 0:
            old, _ = story_card(before, "story-bbb")
            submitted, _ = story_card(path.read_text(), "story-bbb")
            assert (plan_data / "plan.md").read_text() == before.replace(old, submitted, 1)
        else:
            assert result.returncode == 2
            assert "card refresh story-bbb" in result.stderr and "--refresh" in result.stderr
            assert (plan_data / "plan.md").read_text() == before

    def test_two_free_edits_do_not_report_held_or_stale(self, plan_data):
        first = editor(plan_data)
        assert first.returncode == 0, first.stderr
        path, digest, status = candidate(plan_data, change="fresh.py", replacement="newer.py")
        second = editor(plan_data, path=path, digest=digest, status=status)
        assert second.returncode == 0, second.stderr
        assert "held" not in second.stderr and "stale" not in second.stderr


@pytest.mark.slow
class TestPlanLockRecovery:
    def test_live_owner_is_held_then_both_edits_survive(self, plan_data):
        acquired, release = plan_data / "acquired", plan_data / "release"
        holder = writer(EVENT_WRITER, plan_data, acquired, release, "wait")
        assert await_path(acquired), "holder never entered the mutate"
        contender = editor(plan_data, popen=True)
        time.sleep(0.1)
        assert contender.poll() is None, "contender did not wait for the held flock"
        release.write_text("go")
        _out, err = contender.communicate(timeout=30)
        assert holder.wait(30) == 0 and contender.returncode == 0, err
        assert "held" in err and "stale" not in err
        assert f"pid {holder.pid}" in err
        final = (plan_data / "plan.md").read_text()
        assert "story-aaa HELD" in final and "fresh.py" in final

    def test_dead_owner_is_stale_and_recovers_without_hanging(self, plan_data):
        acquired, release = plan_data / "acquired", plan_data / "unused"
        dead = writer(EVENT_WRITER, plan_data, acquired, release, "die")
        assert await_path(acquired) and dead.wait(30) == 7
        result = editor(plan_data)
        assert result.returncode == 0, result.stderr
        assert "stale" in result.stderr and "recovered" in result.stderr
        assert "fresh.py" in (plan_data / "plan.md").read_text()
