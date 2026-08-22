"""story-019: the per-clone plan path, its lock, and its stale refusal.

Verify: pytest -q tests/test_work_plan.py

The concurrency arms are `slow`: they sleep to force an interleaving, and the
fast tier runs at every commit. Their sleeps are the WINDOW, not a guess that
the race will happen — R2-5 rejected a bare barrier because a barrier inside
the mutate deadlocks a correct implementation.
"""

import fcntl
import json
import shutil
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

    def test_the_printed_migration_command_actually_runs(self, tmp_path):
        """Asserting the destination APPEARS is a token check (constraint 11): the
        first spelling printed a bare `mv` into a directory nothing had created,
        because the state root is only made when a tool first writes a marker or a
        record there — and a repo scaffolded before the move may have written
        neither. It failed on precisely the population AC4 exists for. So the
        command is EXECUTED, on a tracked plan, which is what that population has.
        """
        repo = git_init(tmp_path / "stale")
        (repo / ".xp").mkdir()
        (repo / ".xp" / "plan.md").write_text("# Plan\n#### story-042 — x   [ready]\n")
        env = hashing_env(tmp_path)
        for args in (
            ["add", "-A"],
            ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "pre-move"],
        ):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True)
        why = self.refusal(repo, tmp_path)
        command = "\n".join(ln.strip() for ln in why.splitlines() if ln.startswith("  "))
        assert command, f"the refusal printed no command:\n{why}"
        ran = subprocess.run(command, shell=True, cwd=repo, env=env, capture_output=True, text=True)
        assert ran.returncode == 0, f"{command!r} failed: {ran.stderr}"
        assert resolved_plan(repo, tmp_path).read_text().startswith("# Plan")
        assert "pre-move copy" not in self.refusal(repo, tmp_path), "still refusing the same way"


class TestCardDigest:
    """story-023: the credential spawn checks. Covers the whole card, and only
    the parts a lead can edit — the bracket and trailing whitespace move for
    reasons that are not drift."""

    CARD = "#### story-042 — demo story   [ready]\nFiles: a.py\nAC:\n- Given X, Then Y\n"

    def digest(self, card):
        from work import card_digest

        return card_digest(card)

    def test_pinned_so_a_normalization_change_is_visible(self):
        """Hard-coded, not recomputed: `assert digest(card) == card_digest(card)`
        holds against any implementation, including a constant."""
        assert self.digest(self.CARD) == "8107875cb4452bf5"

    def test_one_changed_character_below_the_heading_changes_it(self):
        assert self.digest(self.CARD.replace("Given X", "Given Z")) != self.digest(self.CARD)
        assert self.digest(self.CARD.replace("a.py", "b.py")) != self.digest(self.CARD)

    def test_the_status_bracket_is_not_part_of_it(self):
        """spawn flips [ready] -> [in-progress] right after checking the digest,
        and its own recovery text tells the lead to put the bracket back and
        re-spawn. A bracket-sensitive digest refuses that documented path."""
        for status in ("[in-progress]", "[done]", "[planned]"):
            assert self.digest(self.CARD.replace("[ready]", status)) == self.digest(self.CARD)

    def test_trailing_whitespace_is_not_drift(self):
        """The last card in the plan owns the file to EOF (close.story_card), so
        appending the next story below it would otherwise read as an edit to it."""
        assert self.digest(self.CARD + "\n\n") == self.digest(self.CARD)
        assert self.digest(self.CARD.replace("Files: a.py", "Files: a.py   ")) == self.digest(
            self.CARD
        )


class TestOneFlipRule:
    """Bug f009389a: three spellings of 'rewrite the status bracket' — mint's
    was fixed at story-023's review; spawn's and close's still rewrote a TITLE
    carrying the status text (measured live: story-023's own heading)."""

    def test_spawns_flip_leaves_a_title_containing_ready_alone(self):
        from spawn import flip_map

        plan = "#### story-x — [ready] is a credential   [ready]\n"
        out = flip_map(plan, "story-x")
        assert out == "#### story-x — [ready] is a credential   [in-progress]\n", out

    def test_lands_flip_leaves_a_title_containing_in_progress_alone(self):
        from close import _flip_status

        plan = "#### story-x — the [in-progress] dance   [in-progress]\n"
        out = _flip_status(plan, "story-x")
        assert out == "#### story-x — the [in-progress] dance   [done]\n", out


PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"


def work_env(cwd, home, data=None):
    """`work.py env` — the reader a codex lead's scripts and hooks actually call."""
    env = hashing_env(home)
    if data is not None:
        env["XP_DATA"] = str(data)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "work.py"), "env"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


class TestPluginRootHelper:
    """story-027: the env file, read by processes NOTHING spawned — which have no
    ${CLAUDE_PLUGIN_ROOT} and no Path(__file__) inside the plugin."""

    def fake_plugin(self, path, version="9.9.9"):
        (path / ".claude-plugin").mkdir(parents=True)
        (path / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
        return path

    def seed(self, data, root, version="9.9.9"):
        data.mkdir(parents=True, exist_ok=True)
        (data / "env.json").write_text(
            json.dumps({"plugin_root": str(root), "plugin_version": version})
        )
        return data / "env.json"

    def test_a_seeded_env_resolves_to_the_recorded_root(self, tmp_path):
        install = self.fake_plugin(tmp_path / "install")
        self.seed(tmp_path / "data", install)
        r = work_env(tmp_path, tmp_path, tmp_path / "data")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(install)

    def test_a_stale_root_refuses_naming_the_file_the_value_and_the_route(self, tmp_path):
        install = self.fake_plugin(tmp_path / "install")
        env_file = self.seed(tmp_path / "data", install)
        shutil.rmtree(install)
        r = work_env(tmp_path, tmp_path, tmp_path / "data")
        assert r.returncode != 0, "a dead plugin root resolved"
        assert str(install) not in r.stdout, "the dead path was returned anyway"
        for named in (str(env_file), str(install), "SessionStart"):
            assert named in r.stderr, f"the refusal never names {named}:\n{r.stderr}"

    def test_a_root_that_exists_at_another_version_refuses(self, tmp_path):
        """The cache is version-keyed, so `is_dir()` is not a check: an upgrade
        leaves the old directory in place and populated. This is the case that
        makes the recorded version load-bearing rather than decorative."""
        install = self.fake_plugin(tmp_path / "install", version="9.9.9")
        self.seed(tmp_path / "data", install, version="1.0.0")
        r = work_env(tmp_path, tmp_path, tmp_path / "data")
        assert r.returncode != 0, "a pointer at another version's install resolved"
        assert "1.0.0" in r.stderr and "9.9.9" in r.stderr, r.stderr

    def test_a_root_that_is_not_a_plugin_refuses(self, tmp_path):
        (tmp_path / "install").mkdir()
        self.seed(tmp_path / "data", tmp_path / "install")
        r = work_env(tmp_path, tmp_path, tmp_path / "data")
        assert r.returncode != 0, "a directory with no manifest resolved as a plugin"
        assert "plugin.json" in r.stderr, r.stderr

    def test_a_manifest_without_a_string_version_refuses(self, tmp_path):
        install = self.fake_plugin(tmp_path / "install", version=7)
        self.seed(tmp_path / "data", install, version=7)
        r = work_env(tmp_path, tmp_path, tmp_path / "data")
        assert r.returncode != 0, "a non-string manifest version resolved as an install"
        assert "plugin.json" in r.stderr and "SessionStart" in r.stderr, r.stderr

    def refusal_without(self, tmp_path, contents):
        data = tmp_path / "data"
        data.mkdir(parents=True, exist_ok=True)
        if contents is not None:
            (data / "env.json").write_text(contents)
        r = work_env(tmp_path, tmp_path, data)
        assert r.returncode != 0, "a missing plugin root resolved to something"
        return r.stderr

    def test_no_env_file_at_all_names_setup_as_the_seeder(self, tmp_path):
        why = self.refusal_without(tmp_path, None)
        assert "setup.py" in why, why

    def test_an_env_without_the_key_refuses_the_same_way(self, tmp_path):
        assert "setup.py" in self.refusal_without(tmp_path, "{}")

    def test_a_non_path_root_refuses_without_a_traceback(self, tmp_path):
        why = self.refusal_without(
            tmp_path, json.dumps({"plugin_root": 7, "plugin_version": "1.0.0"})
        )
        assert "env.json" in why and "7" in why and "SessionStart" in why, why
        assert "Traceback" not in why, why

    def test_the_pre_migration_and_stale_refusals_are_not_one_message(self, tmp_path):
        """One message for two states is no message — the reader is told to run
        setup when a session refresh is what it needs, or the reverse."""
        install = self.fake_plugin(tmp_path / "install")
        self.seed(tmp_path / "data", install)
        shutil.rmtree(install)
        stale = work_env(tmp_path, tmp_path, tmp_path / "data").stderr
        (tmp_path / "data" / "env.json").unlink()
        assert stale != work_env(tmp_path, tmp_path, tmp_path / "data").stderr

    def test_an_install_outside_the_repo_resolves_and_reds_when_it_moves(self, tmp_path):
        """AC5's walk, executed: a consuming-style repo with the plugin OUTSIDE the
        tree — the shape this repo's in-tree plugin can never exercise. XP_DATA is
        unset, so data_root() really hashes; HOME is tmp_path (R2-8)."""
        install = shutil.copytree(PLUGIN, tmp_path / "install")
        repo = git_init(tmp_path / "proj")
        scaffold = subprocess.run(
            [sys.executable, str(install / "scripts" / "setup.py")],
            cwd=repo,
            env=hashing_env(tmp_path),
            capture_output=True,
            text=True,
        )
        assert scaffold.returncode == 0, scaffold.stderr
        resolved = work_env(repo, tmp_path)
        assert resolved.returncode == 0, resolved.stderr
        assert resolved.stdout.strip() == str(install)
        moved = install.rename(tmp_path / "install-next")  # what a release does
        after = subprocess.run(
            [sys.executable, str(moved / "scripts" / "work.py"), "env"],
            cwd=repo,
            env=hashing_env(tmp_path),
            capture_output=True,
            text=True,
        )
        assert after.returncode != 0, "the moved-away install still resolved"
        assert str(install) in after.stderr
