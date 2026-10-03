"""The structured gate: what a recorded round contains, and what land discloses
from it at the moment of assent.

Extracted from test_close_land.py at the Sprint-17 close (constraint 8: 519 lines
against the 500 cap). The seam is the artifact — round records and their
disclosure here, land's other failure modes and bookkeeping there.
"""

import json

import pytest
from close_body_cases import (  # noqa: F401
    TestBoundedDurableBody,
    TestLandNamesEachRoundsOwnDiff,
    overflowing_findings,
    story_prior,
)
from close_helpers import (
    CLEAN,
    close,
    launches,
    make_repo,
    marker,
    marker_file,
    stub_reviewer,
)
from diff_reference_helpers import read_named_diff


class TestStructuredGate:
    """story-012a: the report replaces the VERDICT line, and land never spawns."""

    def sprint_overlap_repo(self, tmp_path, gate=False):
        shared = ".xp/system.md" if gate else "shared.py"
        repo, env, g = make_repo(tmp_path, files=f"src/thing.py, {shared}")
        g("checkout", "-q", "main")
        config = "release: sprint\nroles:\n  reviewer: claude/opus\ntests:\n"
        tier = (
            "true" if gate else "grep -q STORY_MERGED shared.py && grep -q SPRINT_MERGED shared.py"
        )
        config += f"  story: {tier}\n"
        (repo / ".xp" / "config.yml").write_text(config)
        target = repo / shared
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
        bundle = launches(tmp_path)[1]["stdin"]
        assert "-A = 1" in read_named_diff(bundle, "Cumulative diff", repo, env)

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
        diff = read_named_diff(bundle, "Cumulative diff", repo, env)
        assert "A = 2" in diff, "the story's own diff went missing"
        assert "TRUNK_ONLY_SENTINEL" not in diff, "the bundle is no longer fork-point based"

    def test_shown_sha_is_head_at_the_end_of_a_clean_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        assert marker(tmp_path)["shown_sha"] == g("rev-parse", "HEAD").stdout.strip()

    def forward_base_motion(self, tmp_path, shared=False):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        path = repo / "base-motion.py"
        path.write_text("TRUNK = 0\nSTORY = 0\n")
        g("add", "-A")
        g("commit", "-qm", "common base-motion file")
        recorded = g("rev-parse", "HEAD").stdout.strip()
        g("checkout", "-q", "story-042-branch")
        g("rebase", "main")
        g("checkout", "-q", "main")
        path.write_text(path.read_text().replace("TRUNK = 0", "TRUNK = 1"))
        g("commit", "-qam", "trunk moves")
        current = g("rev-parse", "HEAD").stdout.strip()
        g("checkout", "-q", "story-042-branch")
        g("rebase", "main")
        if shared:
            path.write_text(path.read_text().replace("STORY = 0", "STORY = 1"))
            g("commit", "-qam", "story touches trunk path")
        g("branch", "-f", "main", recorded)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        assert marker(tmp_path)["review_base"] == recorded
        g("branch", "-f", "main", current)
        assert g("merge-base", "main", "HEAD").stdout.strip() == current
        return repo, env, g, path.relative_to(repo).as_posix(), current

    def test_land_accepts_forward_base_motion_when_trunk_and_story_files_are_disjoint(
        self, tmp_path
    ):
        repo, env, _g, _path, _base = self.forward_base_motion(tmp_path)

        landed = close(repo, env, "land")

        assert landed.returncode == 0, landed.stderr
        assert len(launches(tmp_path)) == 1

    def test_land_refuses_forward_base_motion_when_trunk_and_story_changed_one_file(self, tmp_path):
        repo, env, g, path, base = self.forward_base_motion(tmp_path, shared=True)

        refused = close(repo, env, "land")

        assert refused.returncode == 2 and path in refused.stderr
        assert g("rev-parse", "main").stdout.strip() == base
        assert len(launches(tmp_path)) == 1

    def test_land_refuses_a_recorded_base_that_is_not_an_ancestor_of_todays_base(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        g("checkout", "-qb", "unrelated", "main")
        (repo / "unrelated.py").write_text("SIDE = 1\n")
        g("add", "-A")
        g("commit", "-qm", "unrelated base")
        unrelated = g("rev-parse", "HEAD").stdout.strip()
        g("checkout", "-q", "story-042-branch")
        state = json.loads(marker_file(tmp_path).read_text())
        state["review_base"] = unrelated
        marker_file(tmp_path).write_text(json.dumps(state))

        refused = close(repo, env, "land")

        assert refused.returncode == 2 and "did not cover" in refused.stderr

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
            json.dumps(
                {
                    "fixed": ["a fix that never happened"],
                    "blocking": [],
                    "schema": 2,
                    "dropped": [],
                    "debt": [],
                }
            )
        )
        stub_reviewer(tmp_path, report=None)
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert not marker_file(tmp_path).exists(), "a stale report certified an empty round"

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={
                "fixed": [],
                "blocking": ["B1: the new guard is vacuous"],
                "schema": 2,
                "dropped": [],
                "debt": [],
            },
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "B1: the new guard is vacuous" in r.stderr

    def test_land_prints_noted_items_for_filing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={
                "fixed": [],
                "blocking": [],
                "schema": 2,
                "dropped": [
                    {"finding": item, "reason": "fixture reason"}
                    for item in ["N1: this name misleads"]
                ],
                "debt": [],
            },
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "file these" not in r.stdout
        # the merge body is DESIGN §6's git-versioned audit trail: assert the ITEM,
        # not just its count — deleting "noted" from the renderer passed 192 tests
        assert (
            "dropped: N1: this name misleads — dropped: fixture reason"
            in g("log", "-1", "--format=%B", "main").stdout
        )

    def test_three_rounds_are_labelled_by_their_true_round_number(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        for i in (1, 2, 3):
            stub_reviewer(
                tmp_path,
                report={
                    "fixed": [f"round {i} fix"],
                    "blocking": [],
                    "schema": 2,
                    "dropped": [],
                    "debt": [],
                },
            )
            assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B").stdout
        for i in (1, 2, 3):
            assert f"Review round {i}" in body and f"round {i} fix" in body


class TestReviewMemory:
    def test_every_story_item_reaches_the_next_round_once(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        findings = overflowing_findings()
        stub_reviewer(tmp_path, report=findings)
        assert close(repo, env, "review").returncode == 2
        (repo / "src/thing.py").write_text("A = 3\n")
        g("commit", "-qam", "lead correction")
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0

        prior = story_prior(launches(tmp_path)[-1]["stdin"])
        for status, raw in findings.items():
            if status == "schema":
                continue
            items = [item["finding"] if isinstance(item, dict) else item for item in raw]
            if not items:
                continue
            assert prior.count(items[0]) == prior.count(items[-1]) == 1, status
            assert all(prior.count(item) == 1 for item in items), status
        assert "more, in full" not in prior

    def test_an_ordinary_round_keeps_its_prompt_and_merge_text(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        first = {
            "fixed": ["ordinary fix"],
            "blocking": ["ordinary blocker"],
            "schema": 2,
            "dropped": [
                {"finding": item, "reason": "fixture reason"} for item in ["ordinary note"]
            ],
            "debt": [],
        }
        stub_reviewer(tmp_path, report=first)
        assert close(repo, env, "review").returncode == 2
        (repo / "src/thing.py").write_text("A = 3\n")
        g("commit", "-qam", "lead correction")
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0

        round1 = (
            "Review round 1: 1 fixed · 1 blocking · 1 dropped · 0 debt\n"
            "  fixed: ordinary fix\n"
            "  blocking: ordinary blocker\n"
            "  dropped: ordinary note — dropped: fixture reason"
        )
        prior = round1 + (
            "\n\nDo NOT re-litigate a settled fix. DO verify each `fixed` item still"
            " holds in the tree you were given."
        )
        assert story_prior(launches(tmp_path)[-1]["stdin"]) == prior
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B", "main").stdout.split("\n\n", 1)[1].strip()
        assert body == round1 + "\nReview round 2: 0 fixed · 0 blocking · 0 dropped · 0 debt"


@pytest.mark.parametrize("damage", ["handoff", "checkpoint", "sequence"])
def test_land_requires_sequence_authority_after_red_retry(tmp_path, damage):
    from pathlib import Path

    from story_review_helpers import checkpoint, invoke
    from test_story_review_recovery import pending_disposition

    repo, env, git, key, events, _hooks = pending_disposition(tmp_path)
    sequence = checkpoint(env, key)
    report = Path(sequence["stages"]["solution"]["path"])
    original = report.read_bytes()
    handoff = Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json"
    saved = handoff.read_bytes()
    if damage == "handoff":
        handoff.unlink()
    else:
        state = json.loads(handoff.read_text())
        if damage == "checkpoint":
            state.pop("checkpoint")
        else:
            state["checkpoint"].pop("review_sequence")
        handoff.write_text(json.dumps(state))
    before = git("rev-parse", "main").stdout
    count = events.read_bytes()
    result = invoke(repo, env, key, "land", "--merge-mode", "local")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "sequence" in result.stderr and "restore" in result.stderr
    assert git("rev-parse", "main").stdout == before
    assert report.read_bytes() == original and events.read_bytes() == count
    handoff.write_bytes(saved)
    acknowledged = invoke(repo, env, key, "acknowledge-validation", "--reason", "service recovered")
    assert acknowledged.returncode == 0, acknowledged.stderr
    assert invoke(repo, env, key, "land", "--merge-mode", "local").returncode == 0


@pytest.mark.meta
@pytest.mark.parametrize("guard", ["authority"])
def test_land_input_guard_detects_its_fault(tmp_path, monkeypatch, guard):
    import shutil

    from close_helpers import PLUGIN

    def guarantee(root):
        root.mkdir()
        test_land_requires_sequence_authority_after_red_retry(root, "handoff")

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    target = installed / "scripts/close/review_sequence.py"
    text = target.read_text()
    old = 'if "sequence_round" in latest and ('
    new = "if False and ("
    assert old in text
    target.write_text(text.replace(old, new))
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")
