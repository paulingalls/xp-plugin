"""Review-round findings pinned as tests. Split from test_close.py at sprint-004 open."""

import json
import subprocess
import sys

from close_helpers import (  # noqa: F401
    CARD,
    CLOSE,
    CONFIG,
    PLUGIN,
    REVIEWER_NAME,
    WORK,
    close,
    close_bare,
    launches,
    make_repo,
    marker,
    marker_file,
    mint_ready,
    prose,
    ready_marker,
    stub_reviewer,
)
from work import flip_status


class TestStoryReviewFindings:
    """story-008 close review, run by this story's own pipeline."""

    def test_a_comment_on_the_tests_header_cannot_silence_the_story_tier(self, tmp_path):
        """G2: the twin of the roles: bug, and this copy fails OPEN — a red tier
        is skipped and the story closes green."""
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:   # fast / story / full\n  story: false\n"
        )
        g("add", "-A")
        g("commit", "-qm", "commented tests header")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_a_reviewer_that_writes_without_committing_is_also_refused(self, tmp_path):
        """G5: the `or dirtied` half was vacuous — Bash is deliberately not
        denied, so an uncommitted scratch write is the likelier defect."""
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\necho 'scratch' >> src/thing.py\nprintf '{\"result\": \"VERDICT: clean\"}'\n"
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reviewer" in r.stderr.lower()

    def test_a_dashless_card_header_does_not_poison_the_close_log(self, tmp_path):
        """G6: _log_close reimplemented card_title without its guard."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("#### story-042 — demo story", "#### story-042"))
        mint_ready(repo, env)
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert "####" not in rec["title"]

    def test_a_broken_plugin_install_refuses_instead_of_tracebacking(self, tmp_path):
        """G7: review.charter() read the agent file unguarded, in a module where
        nine tests assert no traceback reaches the lead."""
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys, pathlib; sys.path.insert(0, {str(CLOSE.parent)!r}); import review;"
                " review.PLUGIN_ROOT = pathlib.Path('/nonexistent'); review.charter()",
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0 and "Traceback" not in r.stderr

    def test_pr_mode_records_the_real_merge_and_lands_done_on_trunk(self, tmp_path):
        """G3: pr mode is the argparse DEFAULT and the only mode a release: story
        consumer gets, and no test executed it to a merge. It recorded the story
        branch's HEAD as the merge sha — on a branch gh is about to delete — and
        committed the [done] flip onto the story branch, so trunk never learned."""
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'case "$*" in *"pr merge"*)\n'
            "  git fetch -q origin main && git merge -q --no-edit FETCH_HEAD &&"
            " git push -q origin HEAD:main ;;\n"
            "esac\n"
        )
        gh.chmod(0o755)
        close(repo, env, "review")
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr + r.stdout
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        ancestor = g("merge-base", "--is-ancestor", rec["merge_sha"], "origin/main")
        assert ancestor.returncode == 0, "recorded sha is not on trunk"
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text(), "the flip never landed"


class TestStoryReviewFindings012a:
    """Blocking findings from story-012a's own close review."""

    def test_the_newest_round_survives_the_close_detail_bound(self, tmp_path):
        """B3: the cap kept the HEAD of the joined string, so one long early round
        silently dropped the round that actually gated the merge."""
        sys.path.insert(0, str(CLOSE.parent))
        import session_start

        # PAST the cap on purpose: at 174 chars against CLOSE_CAP 400 the while loop
        # never ran, and `kept.pop()` — dropping the NEWEST round — returned a
        # byte-identical string and passed. The fixture must construct truncation.
        record = {
            "rounds": [
                {"fixed": [f"round {i} " + "x" * 90], "blocking": [], "noted": []} for i in range(6)
            ]
            + [{"fixed": [], "blocking": ["R7-THE-BLOCKER-THAT-GATED-THE-MERGE"], "noted": []}]
        }
        detail = session_start._close_detail(record)
        assert "R7-THE-BLOCKER-THAT-GATED-THE-MERGE" in detail, "the newest round was dropped"
        assert "earlier elided" in detail, "nothing was truncated; the bound was not exercised"
        assert len(detail) <= session_start.CLOSE_CAP + 120

    def test_one_over_long_round_is_cut_to_the_round_cap(self, tmp_path):
        sys.path.insert(0, str(CLOSE.parent))
        import session_start

        detail = session_start._close_detail({"rounds": [{"fixed": ["y" * 900], "blocking": []}]})
        assert len(detail) <= session_start.ROUND_CAP + 40, "the per-round bound is gone"


class TestOverlapReadsTheRefTheModeMerges:
    """c1e586bc, carried onto story-018's rule: pr mode integrates on origin and
    local mode integrates the local trunk, so a guard reading the OTHER mode's ref
    is inert. One test per ref, each a disjoint/overlapping PAIR — the refusal has
    to be the file set, not the fact of a ref existing.

    story-012a's B1 (the review leg refusing on ORIGIN motion) is deliberately gone:
    motion no longer costs a round, so the per-ref claim it carried lives here.
    """

    def remote_repo(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        assert close(repo, env, "review").returncode == 0
        return repo, env, g

    def lands_on_origin_only(self, repo, g, path):
        """A commit that reached ORIGIN while the local ref stayed put, with a STALE
        tracking ref: only a real fetch can see it, which is the fault injection for
        the fetch inside merge_source."""
        g("checkout", "-q", "main")
        (repo / path).write_text("LANDED_BY_ANOTHER_STORY = 1\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        old = g("rev-parse", "HEAD~1").stdout.strip()
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        g("update-ref", "refs/remotes/origin/main", old)
        g("checkout", "-q", "story-042-branch")

    def pr_land(self, repo, env):
        return subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_pr_mode_overlap_is_computed_on_the_FETCHED_origin_ref(self, tmp_path):
        repo, env, g = self.remote_repo(tmp_path)
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'case "$*" in *"pr merge"*)\n'
            "  git fetch -q origin main && git merge -q --no-edit FETCH_HEAD &&"
            " git push -q origin HEAD:main ;;\n"
            "esac\n"
        )
        gh.chmod(0o755)
        self.lands_on_origin_only(repo, g, "unrelated.py")
        assert self.pr_land(repo, env).returncode == 0, "disjoint origin motion bought a round"

        repo, env, g = self.remote_repo(tmp_path / "overlapping")
        self.lands_on_origin_only(repo, g, "src/thing.py")
        r = self.pr_land(repo, env)
        assert r.returncode == 2 and "src/thing.py" in r.stderr
        assert "origin/main" in r.stderr, "the refusal named the ref pr mode does not merge"

    def test_local_mode_overlap_is_computed_on_the_LOCAL_ref_with_a_remote_present(self, tmp_path):
        """The remote EXISTS and never moves: the whole of c1e586bc was a guard that
        read origin here and therefore saw nothing."""
        repo, env, g = self.remote_repo(tmp_path)
        self.trunk_lands(repo, g, "unrelated.py")
        assert close(repo, env, "land").returncode == 0, "disjoint local motion bought a round"

        repo, env, g = self.remote_repo(tmp_path / "overlapping")
        self.trunk_lands(repo, g, "src/thing.py")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "src/thing.py" in r.stderr
        assert "origin/" not in r.stderr, "local mode guarded a ref it does not merge"
        assert "[done]" not in (tmp_path / "overlapping" / "data" / "plan.md").read_text()

    def trunk_lands(self, repo, g, path):
        g("checkout", "-q", "main")
        (repo / path).write_text("LANDED_BY_ANOTHER_STORY = 1\n")
        g("add", "-A")
        g("commit", "-qm", "local main moved")
        g("checkout", "-q", "story-042-branch")


class TestRoundThreeFindings:
    """Blocking findings from story-012a's third close-review round."""

    def test_trunk_motion_DURING_the_review_window_is_not_recorded_as_reviewed(self, tmp_path):
        """B1: the guard read the trunk tips before the launch and the marker re-read
        them ten minutes later, so a teammate landing during the window was recorded
        as the reviewed state and land compared equal. AC 4's defect, inside one
        review instead of across two."""
        repo, env, _g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            "NEW=$(git commit-tree HEAD^{tree} -p main -m 'teammate landed mid-review')\n"
            "git update-ref refs/heads/main $NEW\n"
            'printf \'{"result": "clean"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        # the mid-review commit carries the STORY's tree, so it overlaps by construction
        assert r.returncode == 2 and "src/thing.py" in r.stderr, "unreviewed trunk merged"

    def test_dry_run_review_does_not_delete_a_planted_report(self, tmp_path):
        """B3: the unlink ran before the dry-run return, so a preview destroyed the
        findings of a round that had been refused — the exact file the card's
        durability paragraph exists to keep."""
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        planted = reports / "story-042.round-1.json"
        planted.write_text(
            '{"fixed": ["findings from a refused round"], "blocking": [], "noted": []}'
        )
        assert close(repo, env, "review", "--dry-run").returncode == 0
        assert planted.exists(), "a pure preview deleted real findings"


class TestRoundThreeNoted:
    def test_a_json_array_report_refuses_instead_of_tracebacking(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report="[1, 2, 3]")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "not an object" in r.stderr
        assert "Traceback" not in r.stderr

    def test_each_round_writes_its_own_report_file(self, tmp_path):
        """The reports are the audit trail behind a merge body; a story-scoped path
        would clobber each earlier round and passed the whole suite."""
        repo, env, _g = make_repo(tmp_path)
        for i in (1, 2):
            stub_reviewer(tmp_path, report={"fixed": [f"round {i}"], "blocking": [], "noted": []})
            assert close(repo, env, "review").returncode == 0
        written = sorted(p.name for p in (tmp_path / "data" / "reports").glob("*.json"))
        assert written == ["story-042.round-1.json", "story-042.round-2.json"]

    def test_a_red_verify_does_not_ask_the_lead_to_file_records(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [], "noted": ["N1: punted"]})
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0
        assert "N1: punted" not in r.stdout, "filing instructions for a close that failed"


class TestTheCardIsAGateNoDiffShows:
    """story-023 bound [ready] to a digest of the card the plan reviewer cleared;
    story-019 moved the plan out of the repo. Nothing rebinds them after spawn:
    land re-read the LIVE plan and shell-executed its `Verify:` line while the
    reviewed text sat unread in the ready marker, so an edit silently changed
    what land runs and no diff recorded it — DESIGN §3b cost 4, which the digest
    story-023 shipped can now close. land already refuses when `.xp/config.yml`
    (the TIER it runs) moves; the card is the same gate, one file outside.
    """

    def minted(self, tmp_path):
        """The real sequence — which make_repo now walks for every close test,
        because a fixture that types the bracket carries no credential to check."""
        return make_repo(tmp_path)

    def test_a_verify_line_edited_after_the_review_is_never_executed(self, tmp_path):
        repo, env, _g = self.minted(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        sentinel = tmp_path / "unreviewed-ran"
        plan.write_text(plan.read_text().replace("Verify: true", f"Verify: touch {sentinel}"))
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert not sentinel.exists(), "land shell-executed a line no reviewer saw"
        assert "Verify: true" in r.stderr and str(sentinel) in r.stderr, r.stderr
        assert "[done]" not in plan.read_text()

    def test_the_card_the_reviewer_saw_still_lands(self, tmp_path):
        """The pair: a refusal that also fires on the reviewed card is a broken
        land, not a credential."""
        repo, env, _g = self.minted(tmp_path)
        assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0, "the unedited card was refused"

    def test_a_DELETED_credential_does_not_read_as_a_clean_one(self, tmp_path):
        """The gate is ONE FILE in a directory the teammate and the fixing reviewer
        both reach, and absence returned "" at land — so `rm` disarmed it in
        silence and the next Verify: line was shell-executed anyway. Its own
        migration argument expired: the digest and that tolerance ship in the same
        release, so no branch predating the credential can ever meet this code."""
        repo, env, _g = self.minted(tmp_path)
        assert close(repo, env, "review").returncode == 0
        ready_marker(tmp_path).unlink()
        plan = tmp_path / "data" / "plan.md"
        sentinel = tmp_path / "uncredentialed-ran"
        plan.write_text(plan.read_text().replace("Verify: true", f"Verify: touch {sentinel}"))
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        assert not sentinel.exists(), "land shell-executed a line nothing vouched for"
        assert "nothing minted it" in r.stderr, r.stderr
        assert "[done]" not in plan.read_text()

    def test_the_refusal_names_a_route_that_actually_re_mints(self, tmp_path):
        """A guard whose remediation does not work is a wall, and this one refuses
        a card mid-story: the heading reads [in-progress], while the leg it names
        mints from [planned]. So the route is WALKED, not asserted (constraint 12)."""
        repo, env, _g = self.minted(tmp_path)
        assert close(repo, env, "review").returncode == 0
        ready_marker(tmp_path).unlink()
        assert close(repo, env, "land").returncode == 2
        mint_ready(repo, env)
        assert close(repo, env, "land").returncode == 0, "the named recovery does not clear it"


class TestTheCardEndsUpSayingDone:
    """The [done] flip is how every other reader learns the story is finished —
    the Stop gate keys on [in-progress], the recovery block lists it, and the
    sprint close refuses to start while any member is not [done]. `flip_status`
    rewrites a TRAILING bracket and returns the text UNCHANGED when it matches
    nothing, and cmd_land neither checked the status first (as cmd_review's
    _preflight always has) nor looked at what the flip did — so the merge landed,
    the close was logged, the branch was deleted, and the card still said
    [in-progress]. Silent, and it corrupts the only record of what is done.
    """

    def test_land_refuses_a_card_that_is_not_in_progress(self, tmp_path):
        """The cause: at any other status the flip below matches nothing."""
        repo, env, g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(flip_status(plan.read_text(), "story-042", "in-progress", "done"))
        r = close(repo, env, "land")
        assert r.returncode == 2 and "[done]" in r.stderr, r.stderr
        assert "Review round" not in g("log", "main", "--format=%B").stdout, "it merged anyway"

    def test_a_flip_that_matched_nothing_is_reported_not_swallowed(self, tmp_path):
        """The residual no preflight can cover: the card's OWN Verify: line runs
        in the window between that check and the flip, and land cannot refuse
        after a merge has landed — so it names the hand-step and exits nonzero.
        Constructed through Verify because that is the one hook inside the window."""
        rewrite = "printf '#### story-042 — demo story   [done]\\n' > \"$XP_DATA/plan.md\""
        repo, env, g = make_repo(tmp_path, verify=rewrite)
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        assert "Review round" in g("log", "main", "-1", "--format=%B").stdout, "the merge is the"
        assert r.returncode == 3, r.stdout + r.stderr
        assert "flip story-042 to [done]" in r.stderr, r.stderr

    def test_a_flip_that_took_is_not_reported_as_a_hand_step(self, tmp_path):
        """The pair: crying wolf on every clean close teaches the lead to skip the
        line on the run where it is real."""
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()
