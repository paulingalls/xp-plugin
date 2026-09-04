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

import pytest
from close_helpers import CLOSE, close, free, free_repo, make_repo, marker_file, stub_reviewer
from sprint_helpers import SPRINT_ID, sprint
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import marker_path as sprint_marker_path

# The bound is the longest SILENCE, and it starts at launch — so the stub streams
# until it has written its artifacts, which restarts the clock and models the
# field case: a reviewer that was producing output right up to the kill. One
# second still has a 30x margin over the terminal sleep without charging every
# salvage assertion five seconds for the same constructed event.
KILLED = {"XP_AGENT_TIMEOUT": "1"}
FIXED = {"fixed": ["tightened the guard"], "blocking": [], "noted": []}
PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+guarded = True
"""
NEW_FILE_PATCH = """diff --git a/src/fixed.py b/src/fixed.py
new file mode 100644
--- /dev/null
+++ b/src/fixed.py
@@ -0,0 +1 @@
+fixed = True
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
        '[ "$1 $2 $3" = "plugin list --json" ] && echo '
        '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\' && exit 0\n'
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
    @pytest.mark.slow
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

    @pytest.mark.slow
    def test_an_absent_report_wins_over_a_dirty_tree(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        dying_reviewer(tmp_path, extra='rm "$p"\n')
        assert close(repo, env | KILLED, "review").returncode == 2
        (repo / "dead-reviewer-work.py").write_text("uninspected = True\n")

        refused = salvage(repo, env)

        assert refused.returncode == 2
        assert "wrote no report" in refused.stderr, refused.stderr
        assert "working tree is dirty" not in refused.stderr, refused.stderr
        assert "git reset --hard" not in refused.stderr, refused.stderr

    @pytest.mark.slow
    def test_salvage_keeps_the_launch_card_as_its_scope_contract(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        dying_reviewer(tmp_path, patch=NEW_FILE_PATCH)
        assert close(repo, env | KILLED, "review").returncode == 2
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/thing.py", "Files: src/thing.py, src/fixed.py")
        )

        refused = salvage(repo, env)

        assert refused.returncode == 2 and "card changed" in refused.stderr, refused.stderr
        assert not (repo / "src" / "fixed.py").exists()
        assert not marker_file(tmp_path).exists(), "the widened fresh card authorized a round"

    @pytest.mark.slow
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

    @pytest.mark.slow
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

    @pytest.mark.slow
    def test_a_green_report_on_a_red_tree_is_refused_here_too(self, tmp_path):
        """Salvage runs the same round recorder, so the card's first gate binds
        it. Asserted rather than assumed: a salvage leg with its own checks is
        exactly how the timeout door was open in the first place."""
        repo, env, g = make_repo(tmp_path, verify="false")
        dying_reviewer(tmp_path)
        head = g("rev-parse", "HEAD").stdout.strip()
        assert close(repo, env | KILLED, "review").returncode == 2
        refused = salvage(repo, env)
        assert refused.returncode == 2 and "Verify red" in refused.stderr, refused.stderr
        assert not marker_file(tmp_path).exists()
        # The patch is already COMMITTED when Verify reds, and no round survives to name
        # it, so this refusal is the only disclosure the lead gets that HEAD moved.
        assert g("rev-parse", "HEAD").stdout.strip() != head, "no reviewer commit to disclose"
        assert head[:8] in refused.stderr and "reset --hard" in refused.stderr, refused.stderr

    def test_nothing_to_salvage_and_something_unreadable_are_different(self, tmp_path):
        """Constraint 15. One says run the review, the other says the file on
        disk is broken — a reader sent to the wrong one hunts for a review that
        was never launched."""
        repo, env, _ = make_repo(tmp_path)
        nothing = salvage(repo, env)
        assert nothing.returncode == 2
        assert "no unrecorded review" in nothing.stderr, nothing.stderr
        assert "story-042.round-1.json" in nothing.stderr, nothing.stderr

        stub_reviewer(tmp_path)
        marker = tmp_path / "data" / "markers" / "story-042.review-launch"
        assert close(repo, env, "review").returncode == 0
        assert not marker.exists(), "a recorded round left its launch marker behind"
        marker.write_text("{ truncated")
        broken = salvage(repo, env)
        assert broken.returncode == 2
        assert "not readable" in broken.stderr, broken.stderr
        assert "no unrecorded review" not in broken.stderr, broken.stderr

    @pytest.mark.slow
    def test_a_report_that_outlived_its_launch_marker_is_NAMED_not_denied(self, tmp_path):
        """The two states behind one refusal (constraint 15). Salvage's own advice for an
        unreadable marker is `delete it and review again`, which reaches this branch with
        the round's report still on disk. Compared against the empty-disk refusal rather
        than against a phrase: a text that merely LISTS the round-scoped paths it would
        have read names this one too, byte-identically, while claiming it is not there."""
        repo, env, _g = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        report = report_of(tmp_path)
        (tmp_path / "data" / "markers" / "story-042.review-launch").unlink()

        survived = salvage(repo, env)
        report.unlink()
        report.with_suffix(".patch").unlink()
        nothing = salvage(repo, env)

        assert survived.returncode == nothing.returncode == 2
        assert str(report) in survived.stderr, survived.stderr
        assert survived.stderr != nothing.stderr, survived.stderr

    def test_a_partly_unreadable_sprint_round_is_recorded_AND_says_what_it_lost(self, tmp_path):
        """A round rebuilt from SOME of its stages must not report success while a
        sibling report went unread. Measured: deleting both halves of that answer —
        the clause and the non-zero exit — greens the whole suite, because land
        refuses on `incomplete` either way and nothing else carries the loss."""
        repo, env, _g = sprint_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / f"{SPRINT_ID}.find-a.round-1.json").write_text(json.dumps(FIXED))
        (reports / f"{SPRINT_ID}.find-b.round-1.json").write_text("{not json")

        partial = sprint(repo, env, "salvage")

        assert partial.returncode == 2, partial.stdout
        assert "round 1 recorded incomplete after find-a" in partial.stdout, partial.stdout
        assert partial.stderr.startswith("refused:"), partial.stderr
        assert "find-b" in partial.stderr and "unreadable" in partial.stderr, partial.stderr
        round_ = json.loads(sprint_marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["fixed"] == FIXED["fixed"], round_
        assert "find-b" in round_["incomplete"], round_

    def test_free_salvage_names_the_unrecorded_round_it_searched(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        key = g("branch", "--show-current").stdout.strip().split("/", 1)[1]
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text() + f"\n### Free\n#### {key} — fix typo   [planned]\nContext: release.\n"
            "Files: src/free.py\nAC:\n- Given a patch, Then it lands.\nVerify: true\n"
        )
        (repo / "src" / "free.py").write_text("B = 1\n")
        g("add", "-A")
        g("commit", "-qm", "free work")
        assert free(repo, env, "fix-typo", "review").returncode == 0

        refused = free(repo, env, "fix-typo", "salvage")

        assert refused.returncode == 2
        assert f"{key}.round-2.json" in refused.stderr, refused.stderr

    @pytest.mark.slow
    def test_the_kill_names_salvage_only_on_the_leg_that_has_one(self, tmp_path, monkeypatch):
        """review.run's kill text is shared by four legs; only plan review has no
        salvage action. Both halves are asserted, so dropping all advice cannot pass.
        """
        import review

        repo, env, _ = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\n  plan-reviewer: claude/opus\n"
        )
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )  # reviewer argv is silent by design
        monkeypatch.chdir(repo)
        for key, value in (env | {"XP_AGENT_TIMEOUT": "1"}).items():
            monkeypatch.setenv(key, value)
        # the COMMAND, never the bare word: pytest names tmp_path after the test, so
        # `salvage` is in the log path this text quotes and matches whatever it says
        for name, noun in (
            ("story-reviewer", "story story-042"),
            ("sprint find-state", "sprint 2"),
            ("plan-reviewer", ""),
        ):
            _result, err = review.run("bundle", repo, name=name, noun=noun)
            assert "produced NO OUTPUT" in err and "XP_AGENT_TIMEOUT" in err, err
            command = f"close.py {noun} salvage"
            assert (command in err) is bool(noun), (name, err)

    @pytest.mark.slow
    def test_the_sprint_leg_ITSELF_passes_the_noun_its_kill_text_needs(self, tmp_path):
        """The case above hands review.run a noun, so it proves the `if noun` branch
        that already worked — never that the sprint leg passes one, which WAS the
        defect. Measured: delete `noun=` from sprint_close's review.run call and the
        whole suite greens. Only driving the leg end to end reds."""
        repo, env, _g = sprint_repo(tmp_path)
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )
        stub.chmod(0o755)

        killed = sprint(repo, env | KILLED, "review")

        assert killed.returncode == 2, killed.stdout
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr

    @pytest.mark.slow
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


class TestTheRouteThatDestroysWhatSalvageRescues:
    """The seam a story-scoped reader cannot see: salvage rescues a killed review's
    artifacts, and the resumed session's own next action routes straight past it.
    session_start's NEXT line reads [in-progress] + a FINISHED worktree and says
    run `/story-close`, whose step 2 is `close.py story <id> review` — and that
    unlinks the report and the patch before it spawns, with a clean tree being
    exactly what a reviewer killed after restoring it leaves. Issue #44's own
    suggested recovery, 'run review again', destroys the artifact it would have
    pointed at (bug 0b33b752), and nothing said so on the way past.
    """

    @pytest.mark.slow
    def test_a_relaunched_review_says_what_it_is_about_to_delete(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        report = report_of(tmp_path)
        patch = report.with_suffix(".patch")
        assert report.exists() and patch.exists(), "the fixture wrote no artifacts to lose"

        stub_reviewer(tmp_path)
        again = close(repo, env, "review")
        assert "salvage" in again.stderr, again.stderr
        assert str(report) in again.stderr and str(patch) in again.stderr, again.stderr

    @pytest.mark.slow
    def test_a_first_review_warns_about_nothing(self, tmp_path):
        """The pair, so the warning cannot become wallpaper printed every round:
        no launched review means no artifacts, and a line that fires either way
        is one a lead learns to skip past.
        """
        repo, env, _ = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        first = close(repo, env, "review")
        assert first.returncode == 0, first.stderr
        assert "salvage" not in first.stderr, first.stderr

    @pytest.mark.slow
    def test_the_sprint_noun_says_it_too(self, tmp_path):
        """The other implementation of the same rule, and the one issue #44 actually
        hit: sprint cmd_review's leg() unlinks `<id>.<stage>.round-N.json` before it
        spawns, so a finder's completed report is thrown away by the command a lead
        runs to recover it. Fixing only the story noun would leave the field case
        exactly as it was reported.
        """
        repo, env, _g = sprint_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        left = reports / f"{SPRINT_ID}.find-a.round-1.json"
        left.write_text(json.dumps(FIXED))
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )
        stub.chmod(0o755)

        killed = sprint(repo, env | KILLED, "review")

        assert str(left) in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr
        assert "DELETES" in killed.stderr, killed.stderr

    @pytest.mark.slow
    def test_the_sprint_noun_warns_about_nothing_on_a_first_round(self, tmp_path):
        """The pair on this noun too — a line printed every round is one a lead
        stops reading, and the kill hint below it is the one that must survive."""
        repo, env, _g = sprint_repo(tmp_path)
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )
        stub.chmod(0o755)

        killed = sprint(repo, env | KILLED, "review")

        assert "DELETES" not in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr
