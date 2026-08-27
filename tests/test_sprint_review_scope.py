import json
import shutil

from close_helpers import launches
from sprint_helpers import (
    PLUGIN,
    head,
    make_repo,
    marker_path,
    section,
    sprint,
    stage_key,
    staged_stub,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"


class TestConfirmingRound:
    def _round_one(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        staged_stub(tmp_path)
        first = sprint(repo, env, "review")
        assert first.returncode == 0, first.stderr
        return repo, env, g, len(launches(tmp_path))

    def _commit(self, repo, g):
        target = repo / "src.py"
        target.write_text(target.read_text() + "ROUND_2 = 1\n")
        assert g("add", "src.py").returncode == 0
        assert g("commit", "-qm", "round two delta").returncode == 0

    def test_one_story_shaped_reviewer_reads_the_delta_and_round_one_is_unchanged(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        first = [stage_key(r["stdin"]) for r in launches(tmp_path)]
        assert first == ["find-security", "find-state-lifecycle", "find-test-vacuity", "close"]
        self._commit(repo, g)
        staged_stub(tmp_path)

        preview = sprint(repo, env, "review", "--dry-run")
        assert preview.returncode == 0, preview.stderr
        assert preview.stdout.count("would launch:") == 1
        assert "## Checks, in order of payoff" in preview.stdout, "not the story-review shape"
        assert "## finder\n" not in preview.stdout and "## closer\n" not in preview.stdout

        assert sprint(repo, env, "review").returncode == 0
        second = launches(tmp_path)[split:]
        assert [stage_key(r["stdin"]) for r in second] == ["fix"]
        bundle = second[0]["stdin"]
        delta = section(bundle, DELTA, "Resolutions filed during the sprint")
        assert "+ROUND_2" in delta and "+B = 'SPRINT-ONLY-SENTINEL'" not in delta
        assert "every story was reviewed at its own close" in bundle.lower()
        assert "a seam between stories" in bundle

    def test_the_reviewer_fixes_and_records_all_three_buckets_in_the_same_round(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        self._commit(repo, g)
        before = head(repo, env)
        report = {
            "fixed": ["src.py no longer loses the marker"],
            "blocking": ["src.py still corrupts another marker"],
            "noted": ["src.py naming could be clearer"],
        }
        staged_stub(tmp_path, patches=[("fix", "src.py", "REVIEW_FIX = 1")], fix=report)

        result = sprint(repo, env, "review")
        assert result.returncode == 0, result.stderr
        assert [stage_key(r["stdin"]) for r in launches(tmp_path)[split:]] == ["fix"]
        assert head(repo, env) != before and "REVIEW_FIX = 1" in (repo / "src.py").read_text()
        state = json.loads(marker_path(tmp_path).read_text())
        assert state["rounds"][-1] == report
        diff = tmp_path / "data/reports/sprint/2.fix.round-2.diff"
        assert diff.is_file() and "REVIEW_FIX = 1" in diff.read_text()
        assert str(diff) in result.stdout and "landing accepts it" in result.stdout
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and report["blocking"][0] in land.stderr

    def test_a_clean_confirmation_records_no_invented_work(self, tmp_path):
        repo, env, g, split = self._round_one(tmp_path)
        self._commit(repo, g)
        staged_stub(tmp_path, fix=CLEAN)

        assert sprint(repo, env, "review").returncode == 0
        assert [stage_key(r["stdin"]) for r in launches(tmp_path)[split:]] == ["fix"]
        state = json.loads(marker_path(tmp_path).read_text())
        assert state["rounds"][-1] == CLEAN

    def test_an_unreadable_ALTITUDE_refuses_before_the_reviewer_is_launched(self, tmp_path):
        """The sprint rule lives in the charter this round does NOT carry, so it
        is read out of that file rather than copied here. Unguarded, a charter
        edit that moves the paragraph hands the confirming reviewer an empty
        altitude section — a story-altitude pass no artifact distinguishes from
        this one. Injected against a COPY, so the real reader is what refuses.
        """
        repo, env, g, split = self._round_one(tmp_path)
        self._commit(repo, g)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        agent = plugin / "agents" / "sprint-reviewer.md"
        agent.write_text(agent.read_text().replace("ALTITUDE, every stage:", "At altitude,"))
        r = sprint(repo, env, "review", close=plugin / "scripts" / "close.py")
        assert r.returncode == 2 and "ALTITUDE" in r.stderr, r.stderr
        assert len(launches(tmp_path)) == split, "launched a reviewer with no altitude"
