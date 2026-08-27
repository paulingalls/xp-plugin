import json
import shutil

from close_helpers import LEAD_CREDS, launches
from sprint_helpers import (
    CONFIG,
    PLAN,
    PLUGIN,
    bundles,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    sprint,
    stage_key,
    staged_stub,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"
SURVIVES = {"fixed": [], "blocking": ["silent defect"], "noted": []}


def model(launch):
    argv = launch["argv"]
    return argv[argv.index("--model") + 1]


def stage_config(role, spec):
    roles = f"  reviewer: claude/opus\n  {role}: {spec}\n"
    return CONFIG.replace("  reviewer: claude/opus\n", roles)


def test_the_config_template_carries_every_round_one_stage_role(tmp_path, monkeypatch):
    from work import config_block_value

    template = (PLUGIN / "templates" / "config.yml").read_text()
    repo, _env, _g = make_repo(tmp_path, config=template)
    monkeypatch.chdir(repo)
    for role in ("finder", "verifier", "fixer", "closer"):
        assert config_block_value("roles", role, "\0") != "\0", role


class TestRoundOneRoles:
    def _review(self, tmp_path, config=CONFIG, plan=PLAN, env_extra=None):
        repo, env, _g = make_repo(tmp_path, config=config, plan=plan)
        staged_stub(tmp_path, find=SURVIVES, verify=SURVIVES, fix=CLEAN)
        result = sprint(repo, env | (env_extra or {}), "review")
        return result, launches(tmp_path)

    def test_a_legacy_config_resolves_every_stage_to_reviewer(self, tmp_path):
        result, ran = self._review(tmp_path, env_extra=LEAD_CREDS)
        assert result.returncode == 0, result.stderr
        assert {stage_key(item["stdin"]).split("-", 1)[0] for item in ran} == {
            "find",
            "verify",
            "fix",
            "close",
        }
        assert {model(item) for item in ran} == {"opus"}
        assert {item["env"]["XP_ROLE"] for item in ran} == {"reviewer"}
        assert not [
            key
            for item in ran
            for key in item["env"]
            if key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))
        ]
        for item in ran:
            key = stage_key(item["stdin"])
            assert (tmp_path / "data" / "logs" / f"sprint-{key}-review.log").exists()

    def test_only_finders_use_the_finder_role(self, tmp_path):
        config = stage_config("finder", "claude/haiku")
        result, ran = self._review(tmp_path, config=config)
        assert result.returncode == 0, result.stderr
        assert {model(item) for item in ran if stage_key(item["stdin"]).startswith("find-")} == {
            "haiku"
        }
        others = [item for item in ran if not stage_key(item["stdin"]).startswith("find-")]
        assert {model(item) for item in others} == {"opus"}

    def test_a_card_finder_override_reaches_its_sprints_finders(self, tmp_path):
        plan = PLAN.replace("Verify: true", "Finder: claude/haiku\nVerify: true", 1)
        config = stage_config("finder", "claude/sonnet")
        result, ran = self._review(tmp_path, config=config, plan=plan)
        assert result.returncode == 0, result.stderr
        assert {model(item) for item in ran if stage_key(item["stdin"]).startswith("find-")} == {
            "haiku"
        }

    def test_a_malformed_finder_role_refuses_instead_of_falling_back(self, tmp_path):
        config = stage_config("finder", "claude")
        result, ran = self._review(tmp_path, config=config)
        assert result.returncode == 2
        assert "roles.finder" in result.stderr and "Traceback" not in result.stderr
        assert ran == []

    def test_a_late_stages_bad_role_refuses_before_any_stage_spends(self, tmp_path):
        result, ran = self._review(tmp_path, config=stage_config("closer", "claude"))
        assert result.returncode == 2
        assert "roles.closer" in result.stderr and "Traceback" not in result.stderr
        assert ran == []

    def test_a_cards_reviewer_line_does_not_retarget_the_sprint_stages(self, tmp_path):
        plan = PLAN.replace("Verify: true", "Reviewer: claude/haiku\nVerify: true", 1)
        result, ran = self._review(tmp_path, plan=plan)
        assert result.returncode == 0, result.stderr
        assert {model(item) for item in ran} == {"opus"}

    def test_stage_launches_keep_the_reviewer_silence_bound(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        bin_dir = staged_stub(tmp_path)
        claude = bin_dir / "claude"
        sleepy = "import time\ntime.sleep(0.2)\nsys.stdout.write("
        claude.write_text(claude.read_text().replace("sys.stdout.write(", sleepy))
        result = sprint(repo, env | {"XP_AGENT_TIMEOUT": "0.05"}, "review")
        assert result.returncode == 2 and "NO OUTPUT" in result.stderr

    def test_review_and_land_share_the_missing_shown_sha_refusal(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        missing = "f" * 40
        record_reviews(tmp_path, repo, env, shown=missing)
        review = sprint(repo, env, "review")
        land = sprint(repo, env, "land", "--dry-run")
        assert review.returncode == land.returncode == 2
        assert review.stderr == land.stderr
        assert missing[:8] in review.stderr and str(marker_path(tmp_path)) in review.stderr
        assert "move" in review.stderr and "Traceback" not in review.stderr
        assert bundles(tmp_path) == []


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
        assert model(second[0]) == "opus" and second[0]["env"]["XP_ROLE"] == "reviewer"
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
