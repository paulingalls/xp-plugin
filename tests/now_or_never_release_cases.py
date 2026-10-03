import json

import pytest
from close_helpers import close, make_repo, stub_reviewer
from now_or_never_helpers import debt, report
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import marker_path, sprint, staged_stub


class TestReleaseBoundaries:
    def test_disposition_does_not_clear_recorded_blocker(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report=report(
                blocking=["unmet AC"], dropped=[{"finding": "unmet AC", "reason": "claims waiver"}]
            ),
        )
        assert close(repo, env, "review").returncode == 2
        before = g("rev-parse", "main").stdout
        result = close(repo, env, "land")
        assert result.returncode == 2 and "unmet AC" in result.stderr
        assert g("rev-parse", "main").stdout == before

    def test_unmet_ac_is_not_waived_by_disposition(self, tmp_path):
        repo, env, _ = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, report=report(dropped=[{"finding": "AC", "reason": "loud"}]))
        assert close(repo, env, "review").returncode == 2
        assert close(repo, env, "land").returncode == 2
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_story_lead_motion_is_disclosed_but_gate_motion_refuses(self, tmp_path):
        for gate in (False, True):
            case = tmp_path / str(gate)
            case.mkdir()
            repo, env, g = make_repo(case)
            assert close(repo, env, "review").returncode == 0
            path = repo / (".xp/system.md" if gate else "src/thing.py")
            path.write_text(path.read_text() + "\nEXTRA = True\n")
            assert g("commit", "-qam", "lead change after round").returncode == 0
            result = close(repo, env, "land")
            if gate:
                assert result.returncode == 2 and "gate file" in result.stderr
            else:
                assert result.returncode == 0, result.stderr
                assert "merging unreviewed" in result.stdout


class TestRoundAcceptance:
    @pytest.mark.parametrize("fault", ["reason", "legacy"])
    def test_loss_refuses_before_a_new_round_is_recorded(self, tmp_path, fault):
        from close_helpers import marker_file

        repo, env, _ = make_repo(tmp_path)
        data = report(dropped=[{"finding": "loud cross-concern", "reason": "announces itself"}])
        if fault == "reason":
            del data["dropped"][0]["reason"]
        elif fault == "disposition":
            del data["dropped"]
        else:
            data = {"fixed": [], "blocking": [], "noted": ["unjudged"]}
        stub_reviewer(tmp_path, report=data)
        result = close(repo, env, "review")
        assert result.returncode == 2 and not marker_file(tmp_path).exists()
        assert "No round was recorded" in result.stderr

    def test_sprint_salvage_and_resume_preserve_structured_dispositions(self, tmp_path):

        repo, env, _ = sprint_repo(tmp_path)
        ref = debt(tmp_path / "data")
        item = {
            "finding": "loss",
            "ref": ref,
            "too_big": "design ruling",
            "too_important": "silent corruption",
        }
        dropped = {"finding": "loud expansion", "reason": "announces itself"}
        artifacts = tmp_path / "data/reports/sprint"
        artifacts.mkdir(parents=True)
        for stage in ["find-security", "find-state-lifecycle", "find-test-vacuity"]:
            (artifacts / f"2.{stage}.round-1.json").write_text(
                json.dumps(report(debt=[item], dropped=[dropped]))
            )
        salvaged = sprint(repo, env, "salvage")
        assert salvaged.returncode == 0, salvaged.stderr
        saved = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert saved["debt"] == [item] and saved["dropped"] == [dropped]
        staged_stub(tmp_path, find=report(debt=[item], dropped=[dropped]))
        resumed = sprint(repo, env, "review")
        assert resumed.returncode == 0, resumed.stderr
        saved = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert saved["debt"] == [item] and saved["dropped"] == [dropped]
        assert not saved.get("incomplete")

    def test_legacy_incomplete_round_is_preserved_when_stages_rerun(self, tmp_path):
        repo, env, g = sprint_repo(tmp_path)
        shown = g("rev-parse", "HEAD").stdout.strip()
        base = g("merge-base", "main", "HEAD").stdout.strip()
        old = {
            "fixed": [],
            "blocking": [],
            "noted": ["legacy unjudged finding"],
            "stages": ["find-security"],
            "incomplete": "host killed",
            "shown_sha": shown,
            "reviewed_head": shown,
            "review_base": base,
        }
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {"rounds": [old], "shown_sha": shown, "reviewed_head": shown, "review_base": base}
            )
        )
        artifacts = tmp_path / "data/reports/sprint"
        artifacts.mkdir(parents=True)
        (artifacts / "2.find-security.round-1.json").write_text(
            json.dumps({"fixed": [], "blocking": [], "noted": ["legacy unjudged finding"]})
        )
        staged_stub(tmp_path)
        result = sprint(repo, env, "review")
        assert result.returncode == 0, result.stderr
        rounds = json.loads(path.read_text())["rounds"]
        assert len(rounds) == 2 and rounds[0] == old
        assert rounds[1]["schema"] == 2
