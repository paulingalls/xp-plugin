"""The structured gate: what a recorded round contains, and what land discloses
from it at the moment of assent.

Extracted from test_close_land.py at the Sprint-17 close (constraint 8: 519 lines
against the 500 cap). The seam is the artifact — round records and their
disclosure here, land's other failure modes and bookkeeping there.
"""

import json

import pytest
from close_helpers import (
    CLEAN,
    close,
    launches,
    make_repo,
    marker,
    marker_file,
    stub_reviewer,
)


class TestStructuredGate:
    """story-012a: the report replaces the VERDICT line, and land never spawns."""

    def sprint_overlap_repo(self, tmp_path, gate=False):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        config = "release: sprint\nroles:\n  reviewer: claude/opus\ntests:\n"
        tier = (
            "true" if gate else "grep -q STORY_MERGED shared.py && grep -q SPRINT_MERGED shared.py"
        )
        config += f"  story: {tier}\n"
        (repo / ".xp" / "config.yml").write_text(config)
        target = repo / (".xp/system.md" if gate else "shared.py")
        target.write_text("TOP = 1\nKEEP_1 = 1\nKEEP_2 = 1\nKEEP_3 = 1\nBOTTOM = 1\n")
        g("add", "-A")
        g("commit", "-qm", "common sprint base")
        g("checkout", "-q", "story-042-branch")
        g("rebase", "main")
        target.write_text(target.read_text().replace("TOP = 1", "TOP = 'STORY_MERGED'"))
        g("add", "-A")
        g("commit", "-qm", "story edits shared path")
        g("branch", "sprint-001", "main")
        g("checkout", "-q", "sprint-001")
        target.write_text(target.read_text().replace("BOTTOM = 1", "BOTTOM = 'SPRINT_MERGED'"))
        g("add", "-A")
        g("commit", "-qm", "sprint edits shared path")
        (tmp_path / "data" / "sprint_branch").write_text("sprint-001\n")
        g("checkout", "-q", "story-042-branch")
        assert close(repo, env, "review").returncode == 0
        return repo, env, g, target.relative_to(repo).as_posix()

    def test_clean_sprint_overlap_runs_the_merged_tier_and_names_the_delta(self, tmp_path):
        repo, env, g, shared = self.sprint_overlap_repo(tmp_path)
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        merged = g("show", "sprint-001:shared.py").stdout
        assert "STORY_MERGED" in merged and "SPRINT_MERGED" in merged
        assert f"\n  {shared}\n" in r.stdout, "the lead was told nothing of the shared file domain"
        assert not (tmp_path / "data" / "reports" / "merge").exists()

    def test_a_clean_gate_overlap_still_refuses_before_integration(self, tmp_path):
        repo, env, g, gate = self.sprint_overlap_repo(tmp_path, gate=True)
        before = g("rev-parse", "sprint-001").stdout.strip()
        r = close(repo, env, "land")
        assert r.returncode == 2 and "overlaps files no review covered together" in r.stderr
        assert "sprint-001" in r.stderr and gate in r.stderr
        assert g("rev-parse", "sprint-001").stdout.strip() == before

    def test_a_lead_commit_after_the_review_is_REPORTED_and_merged(self, tmp_path):
        """story-018/024: the refusal here bought one round per lead fix and was the
        one member of the sha-freshness family that is neither a resolution falsifier
        nor what makes land execute the merged tree. It became a report — the
        confirming round is now a norm the lead owns, not a wall land builds."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "LEAD-FIX-AFTER-REVIEW")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "LEAD-FIX-AFTER-REVIEW" in r.stdout, "the unreviewed delta was not shown"
        assert "merging unreviewed" in r.stdout
        assert len(launches(tmp_path)) == 1, "land spawned the reviewer"

    def test_land_on_overlap_is_idempotent(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on the same file")
        g("checkout", "-q", "story-042-branch")
        first, second = close(repo, env, "land"), close(repo, env, "land")
        assert first.returncode == second.returncode == 2
        # the SAME refusal twice, not "refuses, then proceeds": land used to review
        # on the first call by construction, so a close cost two invocations minimum
        assert first.stderr == second.stderr
        assert "src/thing.py" in first.stderr
        assert len(launches(tmp_path)) == 1

    @pytest.mark.slow
    def test_a_second_round_reviews_the_whole_story_diff_not_a_delta(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "more story work")
        assert close(repo, env, "review").returncode == 0
        # `-A = 1` is the trunk-side line only a merge-base..HEAD diff carries; a
        # delta (reviewed..HEAD) would show `-A = 2`. The inverse of the assertion
        # the deleted delta path used to earn.
        assert "-A = 1" in launches(tmp_path)[1]["stdin"]

    def test_review_no_longer_refuses_while_trunk_is_ahead_of_the_merge_base(self, tmp_path):
        """story-018 AC 3: this refusal serialised every file-disjoint story on the
        sprint branch. The review's job is the STORY's diff, computed from the fork
        point — which it already did, and still does with trunk ahead."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        (repo / "other.py").write_text("TRUNK_ONLY_SENTINEL = 1\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on trunk")
        g("checkout", "-q", "story-042-branch")
        stub_reviewer(tmp_path, report=CLEAN)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        bundle = launches(tmp_path)[0]["stdin"]
        assert "A = 2" in bundle, "the story's own diff went missing"
        assert "TRUNK_ONLY_SENTINEL" not in bundle, "the bundle is no longer fork-point based"

    def test_shown_sha_is_head_at_the_end_of_a_clean_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        assert marker(tmp_path)["shown_sha"] == g("rev-parse", "HEAD").stdout.strip()

    def test_land_refuses_when_the_recorded_base_is_not_todays_merge_base(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        state = json.loads(marker_file(tmp_path).read_text())
        state["review_base"] = "0" * 40  # construct the condition; never observe it
        marker_file(tmp_path).write_text(json.dumps(state))
        r = close(repo, env, "land")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_report_items_keep_the_item_bound_and_list_cap_only_at_display(self, tmp_path):
        import bookkeep
        import review

        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={
                "fixed": ["x" * 5000],
                "blocking": [],
                "noted": [f"n{i}" for i in range(review.LIST_CAP + 5)],
            },
        )
        assert close(repo, env, "review").returncode == 0
        round1 = marker(tmp_path)["rounds"][0]
        assert len(round1["fixed"][0]) <= 400
        assert len(round1["noted"]) == review.LIST_CAP + 5
        body = bookkeep.render_merge_body([round1])
        assert "n24" not in body and "more, in full" in body

    def test_a_prose_only_reviewer_is_refused_and_its_output_is_printed_first(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, result="VERDICT: clean\nthe findings I spent ten minutes on", report=None
        )
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert "the findings I spent ten minutes on" in r.stdout, "a good review was destroyed"
        assert not marker_file(tmp_path).exists(), "a round was recorded without a report"

    def test_an_unparseable_report_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report="{not json at all")
        r = close(repo, env, "review")
        # name the real refusal: "exit 2" alone also greens on a stub that dies
        # because no REPORT_PATH was ever offered to it
        assert r.returncode == 2 and "not JSON" in r.stderr
        assert not marker_file(tmp_path).exists()

    def test_a_report_without_the_three_keys_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report={"findings": ["something"]})
        r = close(repo, env, "review")
        assert r.returncode == 2 and "blocking" in r.stderr, "the refusal must name what is missing"
        assert not marker_file(tmp_path).exists()

    def test_a_planted_report_cannot_certify_a_round_that_wrote_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        (reports / "story-042.round-1.json").write_text(
            json.dumps({"fixed": ["a fix that never happened"], "blocking": [], "noted": []})
        )
        stub_reviewer(tmp_path, report=None)
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert not marker_file(tmp_path).exists(), "a stale report certified an empty round"

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={"fixed": [], "blocking": ["B1: the new guard is vacuous"], "noted": []},
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "B1: the new guard is vacuous" in r.stderr

    def test_land_prints_noted_items_for_filing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, report={"fixed": [], "blocking": [], "noted": ["N1: this name misleads"]}
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "N1: this name misleads" in r.stdout and "JUDGMENT.md" in r.stdout
        # the merge body is DESIGN §6's git-versioned audit trail: assert the ITEM,
        # not just its count — deleting "noted" from the renderer passed 192 tests
        assert "noted: N1: this name misleads" in g("log", "-1", "--format=%B", "main").stdout

    def test_three_rounds_are_labelled_by_their_true_round_number(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        for i in (1, 2, 3):
            stub_reviewer(
                tmp_path, report={"fixed": [f"round {i} fix"], "blocking": [], "noted": []}
            )
            assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B").stdout
        for i in (1, 2, 3):
            assert f"Review round {i}" in body and f"round {i} fix" in body


class TestLandNamesEachRoundsOwnDiff:
    """Sprint-17 sprint-review blocking finding. The per-round disclosure fix landed
    in `review.disclose` and in sprint_close's callable, but land's STORY leg kept a
    single static path — so every round but the last was printed under the wrong
    assent artifact: round 1's commits above a `full diff:` naming round 2's file."""

    def test_each_disclosed_round_names_its_own_diff_file(self, tmp_path):
        """CONSTRUCTS two recorded rounds with real commits and reads what land
        printed. A static path satisfies any assertion that only counts rounds, so
        this pairs each round's commit subject with the diff filename beside it."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        state = json.loads(marker_file(tmp_path).read_text())
        shas = [g("rev-parse", "HEAD").stdout.strip()]
        for n in (1, 2):
            (repo / f"round-{n}.py").write_text(f"ROUND_{n} = True\n")
            g("add", "-A")
            g("commit", "-qm", f"REVIEWER-ROUND-{n}")
            shas.append(g("rev-parse", "HEAD").stdout.strip())
        rounds = [{**CLEAN, "reviewed_head": shas[n], "shown_sha": shas[n + 1]} for n in range(2)]
        marker_file(tmp_path).write_text(json.dumps({**state, "rounds": rounds, **rounds[-1]}))
        r = close(repo, env, "land")
        out = r.stdout
        assert "REVIEWER-ROUND-1" in out, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        first = out.index("REVIEWER-ROUND-1")
        assert "round-1.diff" in out[first : out.index("REVIEWER-ROUND-2")], (
            "round 1's commits were disclosed under another round's diff:\n" + out
        )

    def test_a_killed_first_round_does_not_shift_the_second_onto_its_diff(self, tmp_path):
        """The same defect reached through the NUMBERING rather than the path. A round
        killed mid-review records no coverage (`sprint_close.stop`, `cmd_salvage`), and
        dropping it renumbers round 2 as round 1 — so land names round-1.diff over
        round 2's commits, a file holding a different diff or none at all."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        state = json.loads(marker_file(tmp_path).read_text())
        start = g("rev-parse", "HEAD").stdout.strip()
        (repo / "round-2.py").write_text("ROUND_2 = True\n")
        g("add", "-A")
        g("commit", "-qm", "REVIEWER-ROUND-2")
        shown = g("rev-parse", "HEAD").stdout.strip()
        killed = {**CLEAN, "incomplete": "the host killed round 1"}
        done = {**CLEAN, "reviewed_head": start, "shown_sha": shown}
        marker_file(tmp_path).write_text(json.dumps({**state, "rounds": [killed, done], **done}))
        r = close(repo, env, "land")
        assert "REVIEWER-ROUND-2" in r.stdout, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        assert "round-2.diff" in r.stdout and "round-1.diff" not in r.stdout, (
            "round 2 was disclosed under the killed round's diff name:\n" + r.stdout
        )
