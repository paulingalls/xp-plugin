"""story-047: a confirming round is priced like a confirmation, not like a sweep.

Extracted from test_sprint_review.py at story-043's merge, which carried that file
to 520 against constraint 8's hard 500. story-047's own round predicted this and
named this class as the cohesive leaf to shed — over-cap means extract, never
delete tests to fit.
Verify: pytest -q tests/test_sprint_review_scope.py
"""

import json

from close_helpers import launches
from sprint_helpers import (  # noqa: F401
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    SPRINT_ID,
    WORK,
    WORK_SECTION,
    committing_stub,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    snapshot,
    sprint,
    stage_key,
    staged_stub,
    work,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"


class TestConfirmingRoundScope:
    def _round_one(self, tmp_path, finding=""):
        repo, env, g = make_repo(tmp_path)
        report = CLEAN | {"blocking": [finding] if finding else []}
        staged_stub(tmp_path, find_security=report)
        first = sprint(repo, env, "review")
        assert first.returncode == 0, first.stderr
        return repo, env, g, len(launches(tmp_path))

    def _commit(self, repo, g, path="src.py"):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(target.read_text() + "ROUND_2 = 1\n" if target.exists() else "X = 1\n")
        g("add", path)
        assert g("commit", "-qm", f"change {path}").returncode == 0

    def test_round_two_costs_fewer_launches_and_round_one_is_unchanged(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        first = [stage_key(r["stdin"]) for r in launches(tmp_path)]
        assert first == ["find-security", "find-state-lifecycle", "find-test-vacuity", "close"]
        self._commit(repo, g)
        staged_stub(tmp_path)
        preview = sprint(repo, env, "review", "--dry-run")
        assert len(launches(tmp_path)) == split and "then: the closer" in preview.stdout
        assert sprint(repo, env, "review").returncode == 0
        second = launches(tmp_path)[split:]
        assert len(second) < len(first), "a one-commit confirmation repeated the full fan-out"
        assert [stage_key(r["stdin"]) for r in second] == ["close"]
        delta = section(second[0]["stdin"], DELTA, "Resolutions filed during the sprint")
        assert "+ROUND_2" in delta and "+B = 'SPRINT-ONLY-SENTINEL'" not in delta, "re-swept"

    def test_a_rerun_finders_candidates_are_named_to_the_closer_that_judges_them(self, tmp_path):
        again = "src.py loses state still"
        repo, env, g, split = self._round_one(tmp_path, "src.py may silently lose state")
        self._commit(repo, g)
        staged_stub(tmp_path, find_security=CLEAN | {"blocking": [again]})
        assert sprint(repo, env, "review").returncode == 0
        second = launches(tmp_path)[split:]
        assert [stage_key(r["stdin"]) for r in second] == ["find-security", "close"]
        assert again in second[1]["stdin"], "the closer judges a candidate it was never handed"

    def test_scoping_reads_uncapped_findings_and_matches_the_whole_path(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        findings = [f"other-{n}.py is suspect" for n in range(20)] + ["src.py is suspect"]
        staged_stub(tmp_path, find_security=CLEAN | {"blocking": findings})
        assert sprint(repo, env, "review").returncode == 0
        split = len(launches(tmp_path))
        self._commit(repo, g)
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        assert stage_key(launches(tmp_path)[split:][0]["stdin"]) == "find-security"

        boundary = tmp_path / "boundary"
        boundary.mkdir()
        repo, env, g, split = self._round_one(boundary, "src.py is suspect")
        self._commit(repo, g, "nested/src.py")
        staged_stub(boundary)
        assert sprint(repo, env, "review").returncode == 0
        assert [stage_key(r["stdin"]) for r in launches(boundary)[split:]] == ["close"]

        renamed = tmp_path / "renamed"
        renamed.mkdir()
        repo, env, g, split = self._round_one(renamed, "src.py is suspect")
        assert g("mv", "src.py", "renamed.py").returncode == 0
        assert g("commit", "-qm", "rename src.py").returncode == 0
        staged_stub(renamed)
        assert sprint(repo, env, "review").returncode == 0
        assert stage_key(launches(renamed)[split:][0]["stdin"]) == "find-security"

    def test_an_unnamed_delta_is_explicitly_assigned_to_the_closer(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        self._commit(repo, g, "new.py")
        staged_stub(tmp_path)
        result = sprint(repo, env, "review")
        assert result.returncode == 0, result.stderr
        close = launches(tmp_path)[split:][0]["stdin"]
        mine = section(close, "Delta paths only you cover", "Findings from earlier rounds")
        assert mine.strip() == "new.py", "the diff mentions it; nothing ASSIGNS it to the closer"
        assert "new.py" in result.stdout and "unnamed delta paths" in result.stdout

    def test_a_confirmation_finding_is_recorded_and_blocks_land(self, tmp_path):
        repo, env, g, _split = self._round_one(tmp_path)
        self._commit(repo, g)
        blocker = "src.py silently corrupts the marker"
        staged_stub(tmp_path, close=CLEAN | {"blocking": [blocker]})
        assert sprint(repo, env, "review").returncode == 0
        state = json.loads(marker_path(tmp_path).read_text())
        assert state["rounds"][-1]["blocking"] == [blocker]
        assert "0/3 finders re-run" in state["rounds"][-1]["noted"][0], "the record hides the scope"
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and blocker in land.stderr

    def test_the_lead_is_told_which_finders_were_skipped_and_why(self, tmp_path):
        repo, env, g, _split = self._round_one(tmp_path, "src.py may silently lose state")
        self._commit(repo, g)
        staged_stub(tmp_path)
        result = sprint(repo, env, "review")
        assert "re-run security" in result.stdout and "src.py" in result.stdout
        assert "skip state-lifecycle" in result.stdout
        assert "no round-1 finding named a changed path" in result.stdout

    def test_absent_evidence_reruns_but_malformed_evidence_refuses(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        report = tmp_path / "data/reports/sprint/2.find-security.round-1.json"
        report.unlink()
        self._commit(repo, g)
        staged_stub(tmp_path)
        result = sprint(repo, env, "review")
        assert result.returncode == 0 and "round-1 report absent" in result.stdout
        assert stage_key(launches(tmp_path)[split:][0]["stdin"]) == "find-security"

        malformed = tmp_path / "malformed"
        malformed.mkdir()
        repo, env, g, split = self._round_one(malformed)
        report = malformed / "data/reports/sprint/2.find-security.round-1.json"
        report.write_text("not JSON")
        self._commit(repo, g)
        result = sprint(repo, env, "review")
        assert result.returncode == 2 and "not JSON" in result.stderr
        assert len(launches(malformed)) == split
        report.unlink()
        report.mkdir()
        result = sprint(repo, env, "review")
        assert result.returncode == 2 and "could not read reviewer report" in result.stderr
