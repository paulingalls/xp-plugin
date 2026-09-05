"""The story review leg as it runs: who may launch it, which harness the card
and config pick, and what a red Verify leaves for land to read."""

import json
from itertools import pairwise

import pytest
from close_helpers import (
    CARD,
    CLAUDE_SH,
    CLEAN,
    close,
    launches,
    make_repo,
    marker,
    marker_file,
    mint_ready,
    stub_reviewer,
)
from spawn_helpers import stub_codex

VERIFIED_PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+guarded = True
"""


class TestCompletedVerifyState:
    def test_land_names_the_completed_review_verify_failure_and_tree(self, tmp_path):
        """The reviewer PATCHES, so Verify judges a tree the review was not launched
        against and the two shas differ. Without the patch either sha satisfies this,
        and land would point the lead at a tree Verify never ran on."""
        repo, env, g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, patch=VERIFIED_PATCH)
        launched = g("rev-parse", "HEAD").stdout.strip()
        assert close(repo, env, "review").returncode == 2
        verified = g("rev-parse", "HEAD").stdout.strip()
        assert verified != launched, "the reviewer patch did not move HEAD"

        refused = close(repo, env, "land")

        assert refused.returncode == 2
        assert "completed" in refused.stderr and "false" in refused.stderr
        assert verified[:8] in refused.stderr, refused.stderr
        assert launched[:8] not in refused.stderr, refused.stderr
        assert "no close in progress" not in refused.stderr

    def test_a_re_review_clears_the_verify_red_refusal(self, tmp_path):
        """What CLEARS the state land now reads. Nothing else does, so a story whose
        Verify was fixed would refuse at land forever on a tree that is green."""
        repo, env, _g = make_repo(tmp_path, verify="false")
        assert close(repo, env, "review").returncode == 2
        assert close(repo, env, "land").returncode == 2
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(CARD.format(status="planned", verify="true"))
        mint_ready(repo, env)

        assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0

    def test_story_report_schema_and_blocking_surface_ignore_clearance_key(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        report = {"fixed": [], "blocking": ["STORY-BLOCKER"], "noted": []}
        stub_reviewer(tmp_path, report=report | {"clearable_by_full": ["STORY-BLOCKER"]})
        assert close(repo, env, "review").returncode == 0
        round_ = marker(tmp_path)["rounds"][-1]
        assert round_["blocking"] == ["STORY-BLOCKER"] and "clearable_by_full" not in round_
        assert (landed := close(repo, env, "land")).returncode == 2 and landed.stderr == (
            "refused: the last review round left blocking findings:\n  STORY-BLOCKER\n"
            "Fix them (or review again once fixed) — a flag cannot clear these\n"
        )


class TestAReviewerMayNotREWRITEWhatItWasGiven:
    """012b handback N2: every motion check
    is ancestry-BLIND. A reviewer that resets past reviewed_head and re-commits
    leaves `reviewed_head..HEAD` holding only its own commits, so authorship
    passes; the tree is clean, `.xp/` is untouched, the marker is intact; and
    land's own ancestor check reads shown_sha, which was recorded AFTER the
    reviewer and is therefore an ancestor of its own rewrite by construction.
    The lead's story commits merge as if reviewed, having been deleted.
    """

    def rewriting_stub(self, tmp_path):
        (tmp_path / "bin" / "claude").write_text(
            CLAUDE_SH + "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            "git reset -q --hard HEAD~1\n"  # the lead's story work, gone
            "echo 'x = 1' > src/thing.py\n"
            "git -c user.name='xp story-reviewer' -c user.email='r@xp'"
            " commit -qam 'reviewer rewrote the branch'\n"
            'printf \'{"type": "result", "result": "clean"}\'\n'
        )
        (tmp_path / "bin" / "claude").chmod(0o755)

    def test_a_reviewer_that_rewrote_history_is_refused_and_records_nothing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        reviewed = g("rev-parse", "HEAD").stdout.strip()
        self.rewriting_stub(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert reviewed[:8] in r.stderr and "reset --hard" in r.stderr, r.stderr
        assert not marker_file(tmp_path).exists(), "recorded a round over dropped commits"
        # and the recovery it names actually restores the lead's work
        g("reset", "-q", "--hard", reviewed)
        assert "A = 2" in (repo / "src" / "thing.py").read_text()

    @pytest.mark.slow
    def test_a_read_only_reviewer_that_adds_a_commit_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "bin" / "claude").write_text(
            CLAUDE_SH + "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": ["f"], "blocking": [], "noted": []}\' > "$p"\n'
            "echo 'x = 1' >> src/thing.py\n"
            "git -c user.name='xp story-reviewer' -c user.email='r@xp' commit -qam 'fix'\n"
            'printf \'{"type": "result", "result": "fixed"}\'\n'
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        assert close(repo, env, "review").returncode == 2
        assert not marker_file(tmp_path).exists()


class TestSelfCloseRefusal:
    """story-008 AC 6: close.py's XP_ROLE refusal is the property's home."""

    def test_non_lead_roles_are_refused(self, tmp_path):
        """N3: parametrized, or this fault-injects the AC and not the widening."""
        for role in ("teammate", "reviewer", "sprint-close", ""):
            repo, env, _g = make_repo(tmp_path / f"r-{role or 'empty'}")
            r = close(repo, {**env, "XP_ROLE": role}, "review")
            assert r.returncode == 2, f"XP_ROLE={role!r} was allowed to close"
            assert "close" in r.stderr.lower()

    def test_the_lead_passes_the_same_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, {**env, "XP_ROLE": "lead"}, "review").returncode == 0


class TestCodexReviewerLeg:
    """story-021: the reviewer is harness-agnostic. Its report is read from the
    SAME round path with the SAME parse, so no caller of review.py can tell which
    harness wrote it — the divergence is the argv and nothing else."""

    def codex_repo(self, tmp_path, posture="danger-full-access", **kw):
        repo, env, g = make_repo(tmp_path)
        # The stub dies on any other posture, so every test in this class walks
        # the reviewer leg's real launch under the posture the branch ships.
        rec = stub_codex(tmp_path, commit=False, report=CLEAN, sandbox=posture, **kw)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: codex/gpt-5.6-terra/high\ntests:\n  story: true\n"
            f"codex_sandbox: {posture}\n"
        )
        g("add", "-A")
        g("commit", "-qm", "reviewer role is codex")
        return repo, env, rec

    def test_the_round_is_recorded_from_a_codex_written_report(self, tmp_path):
        repo, env, _rec = self.codex_repo(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr + r.stdout
        rounds = marker(tmp_path)["rounds"]
        # The round carries the reviewer's report AND the coverage it reviewed:
        # top-level coverage is overwritten by a later round, so a round that
        # does not carry its own cannot be disclosed once a second one exists.
        (round_,) = rounds
        assert round_ | CLEAN == round_, round_
        assert round_["reviewed_head"] and round_["shown_sha"]

    @pytest.mark.parametrize("posture", ["workspace-write", "danger-full-access"])
    def test_the_reviewer_argv_is_the_same_one_the_teammate_leg_takes(self, tmp_path, posture):
        """Not a second spawn path: same posture, same environment pins, same
        model handling. AC2 lives HERE and not at `agent_argv` — with the role
        parameter gone the two legs are one expression, so comparing them through
        the builder is f(x) == f(x). What can still red is a caller re-deriving a
        posture from its role, which is what left the reviewer with no network at
        all while the lead believed the opposite in writing."""
        repo, env, rec = self.codex_repo(tmp_path, posture)
        result = close(repo, env, "review")
        assert result.returncode == 0
        launch = json.loads(rec.read_text())
        argv = launch["argv"]
        assert ("--sandbox", posture) in list(pairwise(argv)), argv
        assert f"codex sandbox: {posture}" in result.stderr
        assert not [a for a in argv if a.startswith("sandbox_workspace_write.")], argv
        assert ("--disable", "unified_exec") not in list(pairwise(argv)), argv
        assert argv[argv.index("-m") + 1] == "gpt-5.6-terra"
        assert ("-c", "model_reasoning_effort=high") in list(pairwise(argv))
        assert launch["env"]["XP_ROLE"] == "reviewer"
        assert "REPORT_PATH:" in launch["stdin"] and "demo story" in launch["stdin"]

    def test_codex_absent_from_path_refuses_without_a_traceback(self, tmp_path):
        repo, env, _rec = self.codex_repo(tmp_path)
        (tmp_path / "bin" / "codex").unlink()
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr


class TestTheCardsReviewerLine:
    """story-026: the config's reviewer is global, so it cannot say "author codex,
    review claude" on one story and the inverse on the next. The card line is the
    `Executor:` line's twin, and the round path and parse are unchanged."""

    def test_the_card_line_beats_the_config_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: codex/gpt-5.6-terra/high\ntests:\n  story: true\n"
        )
        g("add", "-A")
        g("commit", "-qm", "reviewer role is codex")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Verify: true", "Verify: true\nReviewer: claude/opus")
        )
        mint_ready(repo, env)
        # nothing named codex is on PATH: config's default would refuse loudly
        # rather than pass this by accident
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stdout + r.stderr
        (launch,) = launches(tmp_path)
        assert launch["argv"][launch["argv"].index("--model") + 1] == "opus"
        (round_,) = marker(tmp_path)["rounds"]
        assert round_ | CLEAN == round_, round_
        assert round_["reviewed_head"] and round_["shown_sha"]
