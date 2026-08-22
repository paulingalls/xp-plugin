"""story-019: the per-clone plan path, its lock, and its stale refusal.

Verify: pytest -q tests/test_work_plan.py

The concurrency arms are `slow`: they sleep to force an interleaving, and the
fast tier runs at every commit. Their sleeps are the WINDOW, not a guess that
the race will happen — R2-5 rejected a bare barrier because a barrier inside
the mutate deadlocks a correct implementation.
"""

import fcntl
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"

PLAN = """# Plan

#### story-aaa — first   [ready]
Files: a.py
#### story-bbb — second   [ready]
Files: b.py
"""

# Writers run as REAL subprocesses: a same-process fake would share the
# interpreter's own file handles and never exercise the flock.
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

# The defect this story's design rejects: the read happens BEFORE the lock, so
# the loser writes a plan that never saw the winner's edit. The rendezvous sits
# AT that read -- the one place a barrier cannot deadlock (R2-5/F3).
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


def writer(src, data, *args):
    return subprocess.Popen(
        [sys.executable, "-c", src.format(scripts=str(SCRIPTS)), *[str(a) for a in args]],
        env={"XP_DATA": str(data), "PATH": "/usr/bin:/bin"},
    )


def lock_is_held(data):
    lock = Path(data) / "locks" / "plan.lock"
    if not lock.exists():
        return False
    with open(lock, "r") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True  # someone else holds it -- R3-4: a held flock is invisible otherwise
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def await_held(data, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lock_is_held(data):
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def data(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN)
    return tmp_path


@pytest.mark.slow
class TestConcurrentWriters:
    def test_both_flips_survive_when_writers_overlap(self, data):
        """AC6. Writer A holds the lock for 2s -- comfortably over interpreter
        startup, so B is forced to arrive while A is inside its mutate."""
        a = writer(CORRECT_WRITER, data, "story-aaa", 2)
        assert await_held(data), "writer A never took the lock"
        b = writer(CORRECT_WRITER, data, "story-bbb", 0)
        assert a.wait(30) == 0 and b.wait(30) == 0
        final = (data / "plan.md").read_text()
        assert "story-aaa DONE" in final
        assert "story-bbb DONE" in final

    def test_a_read_outside_the_lock_loses_a_flip(self, data):
        """The same overlap against the rejected design MUST red. Without this
        the arm above greens on any implementation that happens to serialize."""
        rv = data / "rv"
        a = writer(READ_OUTSIDE_LOCK_WRITER, data, "story-aaa", rv)
        b = writer(READ_OUTSIDE_LOCK_WRITER, data, "story-bbb", rv)
        assert a.wait(30) == 0 and b.wait(30) == 0
        final = (data / "plan.md").read_text()
        assert ("story-aaa DONE" in final) != ("story-bbb DONE" in final), (
            "both flips survived a read outside the lock -- the arm above proves nothing"
        )


# AC1/AC2 run with XP_DATA UNSET so data_root() really hashes the git-common-dir;
# HOME is redirected so the developer's own ~/.xp/data is never written (R2-8).
def hashing_env(home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home)}


def git_init(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env={"PATH": "/usr/bin:/bin"})
    return path


def resolved_plan(cwd, home):
    """What the tools would read, resolved by the same code they call."""
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(SCRIPTS)!r});"
            " from work import plan_path; print(plan_path())",
        ],
        cwd=cwd,
        env=hashing_env(home),
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


class TestPerClone:
    """Two defects, one arm each, both fault-injected and measured:
    AC1 reds when plan_path() is a shared constant (one plan for every clone —
    the fight this story exists to end); AC2 reds against the IN-REPO reader,
    where a worktree gets its own .xp/plan.md instead of its clone's card."""

    def test_two_clones_of_one_repo_never_see_each_others_plan(self, tmp_path):
        a, b = git_init(tmp_path / "a"), git_init(tmp_path / "b")
        plan_a, plan_b = resolved_plan(a, tmp_path), resolved_plan(b, tmp_path)
        assert plan_a != plan_b, "two clones resolved to ONE plan — they would fight"
        for path, card in ((plan_a, "lane-A"), (plan_b, "lane-B")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Plan\n#### {card} — x   [ready]\n")
        assert "lane-A" in plan_a.read_text() and "lane-B" not in plan_a.read_text()
        assert "lane-B" in plan_b.read_text() and "lane-A" not in plan_b.read_text()

    def test_a_worktree_reads_its_CLONES_plan_not_a_copy_of_its_own(self, tmp_path):
        """The teammate must see the card the lead wrote."""
        clone = git_init(tmp_path / "clone")
        (clone / "f").write_text("x\n")
        env = hashing_env(tmp_path)
        for args in (
            ["add", "-A"],
            ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
            ["worktree", "add", "-q", str(tmp_path / "wt"), "-b", "story"],
        ):
            subprocess.run(["git", *args], cwd=clone, env=env, check=True)
        lead = resolved_plan(clone, tmp_path)
        lead.parent.mkdir(parents=True, exist_ok=True)
        lead.write_text("# Plan\n#### story-042 — the lead's card   [ready]\n")
        assert resolved_plan(tmp_path / "wt", tmp_path) == lead
        assert "the lead's card" in resolved_plan(tmp_path / "wt", tmp_path).read_text()


SPAWN = SCRIPTS / "spawn.py"


class TestStaleInRepoPlan:
    """AC4, narrowed per the card: a message in the EXISTING missing-plan refusal,
    not a new guard in every tool. Both arms are constructed, because "exits
    nonzero" alone greens against a do-nothing implementation of the message —
    only the difference between them says the guard is there.
    """

    def refusal(self, repo, home):
        r = subprocess.run(
            [sys.executable, str(SPAWN), "story-042"],
            cwd=repo,
            env=hashing_env(home),
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0, "a missing plan must refuse"
        return r.stderr + r.stdout

    def test_a_stale_in_repo_plan_names_the_migration_and_a_bare_repo_does_not(self, tmp_path):
        bare, stale = git_init(tmp_path / "bare"), git_init(tmp_path / "stale")
        (stale / ".xp").mkdir()
        (stale / ".xp" / "plan.md").write_text("# Plan\n#### story-042 — x   [ready]\n")
        bare_why, stale_why = self.refusal(bare, tmp_path), self.refusal(stale, tmp_path)
        assert bare_why != stale_why, "the same refusal for both — the message is not there"
        destination = str(resolved_plan(stale, tmp_path))
        assert destination in stale_why and ".xp/plan.md" in stale_why
        assert destination not in bare_why or "migrate" not in bare_why.lower()
