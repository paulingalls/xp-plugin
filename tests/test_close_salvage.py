"""story-036: the round a KILLED reviewer already earned.

Its own file: the two files the card names stand at 491 and 479 of constraint
8's 500-line cap. Salvage reads the artifacts the reviewer WRITES — the patch at
PATCH_PATH and the report — never its commits: reviewers have been read-only
since v0.7.0 (story-034), so a leg that recorded a round from a killed
reviewer's commits would launder the guard check_reviewer_motion exists to be.
"""

import json
import subprocess
import sys

from close_helpers import CLOSE, close, make_repo, marker_file, stub_reviewer

# The bound is the longest SILENCE, and it starts at launch — so the stub streams
# once it has written its artifacts, which both restarts the clock and models the
# field case: a reviewer that was producing output right up to the kill.
KILLED = {"XP_AGENT_TIMEOUT": "5"}
FIXED = {"fixed": ["tightened the guard"], "blocking": [], "noted": []}
PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+guarded = True
"""


def dying_reviewer(tmp_path, extra="", patch=PATCH):
    """A reviewer that writes its report and patch and then goes SILENT.

    It emits no terminal result, which is what the silence bound reads and what
    the field case looked like: the artifacts on disk, the process killed inside
    whatever it was doing next. A ticker streams while it works, because the
    bound starts at LAUNCH — without one a loaded machine kills the stub
    mid-write and the test measures the fixture. Its own process rather than a
    shell loop: a builtin printf writing to a pipe is block-buffered, so a
    subshell that never exits never flushes a byte of it.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ticker = tmp_path / "ticker.py"
    ticker.write_text(
        "import sys, time\n"
        "while True:\n"
        '    sys.stdout.write(\'{"type": "system"}\\n\')\n'
        "    sys.stdout.flush()\n"
        "    time.sleep(0.2)\n"
    )
    (bin_dir / "claude").write_text(
        "#!/bin/sh\n"
        '[ "$1 $2 $3" = "plugin list --json" ] && exit 1\n'
        f"{sys.executable} {ticker} &\n"
        "ticker=$!\n"
        f"echo launched >> {tmp_path / 'spawns'}\n"
        "input=$(cat)\n"
        "p=$(printf '%s' \"$input\" | sed -n 's/^REPORT_PATH: //p')\n"
        "q=$(printf '%s' \"$input\" | sed -n 's/^PATCH_PATH: //p')\n"
        f"printf '%s' '{json.dumps(FIXED)}' > \"$p\"\n"
        f"printf '%s' '{patch}' > \"$q\"\n"
        f"{extra}"
        "kill $ticker\n"
        "sleep 30\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir


def salvage(repo, env, story_id="story-042"):
    return subprocess.run(
        [sys.executable, str(CLOSE), "story", story_id, "salvage"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def report_of(tmp_path):
    (path,) = (tmp_path / "data" / "reports").glob("*.json")
    return path


class TestSalvage:
    def test_the_lead_reaches_a_round_without_a_second_review(self, tmp_path):
        """AC 9. Re-reading the diff would ask a fresh reviewer to find what the
        surviving patch already fixes, and charge a full round for it."""
        repo, env, g = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        killed = close(repo, env | KILLED, "review")
        assert killed.returncode == 2, killed.stdout
        assert not marker_file(tmp_path).exists(), "the kill recorded a round"

        rescued = salvage(repo, env)
        assert rescued.returncode == 0, rescued.stderr
        state = json.loads(marker_file(tmp_path).read_text())
        assert [r["fixed"] for r in state["rounds"]] == [["tightened the guard"]]
        spawns = (tmp_path / "spawns").read_text().splitlines()
        assert len(spawns) == 1, "salvage spawned a second reviewer"
        assert "guarded = True" in (repo / "src" / "thing.py").read_text()
        assert g("log", "-1", "--format=%an").stdout.strip() == "xp story-reviewer"

    def test_a_salvaged_round_no_longer_reads_as_refused(self, tmp_path):
        """The kill stamps the report, so a reader between the two commands is
        not told a dead round passed. A salvage clears it — the two must not
        contradict each other on disk. Content, not bytes: clearing a key
        re-serializes, and only the untouched accept path can promise bytes.
        """
        repo, env, _ = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        stamped = json.loads(report_of(tmp_path).read_text())
        assert "NO OUTPUT" in stamped["refused"], stamped

        assert salvage(repo, env).returncode == 0
        assert json.loads(report_of(tmp_path).read_text()) == FIXED

    def test_a_killed_reviewer_that_committed_is_refused(self, tmp_path):
        """AC 10, and the door this arm exists to close: review.run returns on
        the timeout BEFORE check_reviewer_motion, so a reviewer that violated
        the read-only contract survives the kill unrefused. Routing salvage
        through the same guard is what refuses it — and the refusal names the
        lead's own commits as the other reading, because the reviewer runs with
        GIT_AUTHOR_*/GIT_COMMITTER_* stripped and authorship cannot separate
        them (spawn.run_agent).
        """
        repo, env, g = make_repo(tmp_path)
        launched = g("rev-parse", "HEAD").stdout.strip()
        dying_reviewer(
            tmp_path,
            extra=(
                "echo 'the reviewer committed' >> src/other.py\n"
                "git add -A\n"
                "git -c user.name=t -c user.email=t@t commit -qm 'reviewer motion'\n"
            ),
        )
        assert close(repo, env | KILLED, "review").returncode == 2
        refused = salvage(repo, env)
        assert refused.returncode == 2, refused.stdout
        assert launched[:8] in refused.stderr, refused.stderr
        assert "no reviewer leg may do" in refused.stderr, refused.stderr
        assert "or you did since the kill" in refused.stderr, refused.stderr
        assert not marker_file(tmp_path).exists(), "a forbidden commit reached a round"

    def test_a_green_report_on_a_red_tree_is_refused_here_too(self, tmp_path):
        """Salvage runs the same round recorder, so the card's first gate binds
        it. Asserted rather than assumed: a salvage leg with its own checks is
        exactly how the timeout door was open in the first place."""
        repo, env, _ = make_repo(tmp_path, verify="false")
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        refused = salvage(repo, env)
        assert refused.returncode == 2 and "Verify red" in refused.stderr, refused.stderr
        assert not marker_file(tmp_path).exists()

    def test_nothing_to_salvage_and_something_unreadable_are_different(self, tmp_path):
        """Constraint 15. One says run the review, the other says the file on
        disk is broken — a reader sent to the wrong one hunts for a review that
        was never launched."""
        repo, env, _ = make_repo(tmp_path)
        nothing = salvage(repo, env)
        assert nothing.returncode == 2
        assert "no unrecorded review" in nothing.stderr, nothing.stderr

        stub_reviewer(tmp_path)
        marker = tmp_path / "data" / "markers" / "story-042.review-launch"
        assert close(repo, env, "review").returncode == 0
        assert not marker.exists(), "a recorded round left its launch marker behind"
        marker.write_text("{ truncated")
        broken = salvage(repo, env)
        assert broken.returncode == 2
        assert "not readable" in broken.stderr, broken.stderr
        assert "no unrecorded review" not in broken.stderr, broken.stderr

    def test_the_kill_names_salvage_only_on_the_leg_that_has_one(self, tmp_path, monkeypatch):
        """review.run's kill text is shared by four legs and only story close has a
        salvage action to offer. Plan and sprint reviews write no launch marker, so
        salvage there answers `no unrecorded review — Run review`, sending the lead
        to a STORY close review after a PLAN review died. Both halves asserted:
        dropping the advice from every leg would satisfy the second alone.
        """
        import review

        repo, env, _ = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\n  plan-reviewer: claude/opus\n"
        )
        (tmp_path / "bin" / "claude").write_text("#!/bin/sh\nsleep 30\n")  # silent by design
        monkeypatch.chdir(repo)
        for key, value in (env | {"XP_AGENT_TIMEOUT": "1"}).items():
            monkeypatch.setenv(key, value)
        # the COMMAND, never the bare word: pytest names tmp_path after the test, so
        # `salvage` is in the log path this text quotes and matches whatever it says
        for name, noun in (("story-reviewer", "story story-042"), ("plan-reviewer", "")):
            _result, err = review.run("bundle", repo, name=name, noun=noun)
            assert "produced NO OUTPUT" in err and "XP_AGENT_TIMEOUT" in err, err
            assert ("story story-042 salvage" in err) is bool(noun), (name, err)

    def test_a_launch_marker_written_before_the_noun_still_records(self, tmp_path):
        """v0.14.1 moved the leg's own land command into the launch marker, and
        salvage is the one leg that reads a marker THIS version may not have
        written: an upgrade between the kill and the rescue leaves one carrying
        no noun. Delete with the fallback.
        """
        repo, env, _ = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        launch = tmp_path / "data" / "markers" / "story-042.review-launch"
        at = json.loads(launch.read_text())
        assert at.pop("noun") == "story story-042", at
        launch.write_text(json.dumps(at))

        rescued = salvage(repo, env)
        assert rescued.returncode == 0, rescued.stderr
        assert "close.py story story-042 land" in rescued.stdout, rescued.stdout
