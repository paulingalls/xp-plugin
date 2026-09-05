import json

import pytest
from review_report import ITEM_CAP, cap_items, read_report
from sprint_helpers import make_repo, marker_path, sprint, staged_stub


class TestCloserOnlySchema:
    def write(self, tmp_path, **extra):
        path = tmp_path / "report.json"
        path.write_text(json.dumps({"fixed": [], "blocking": ["A", "B"], "noted": []} | extra))
        return path

    def test_closer_binding_is_validated_before_projection(self, tmp_path):
        path = self.write(tmp_path, clearable_by_full=["B"])
        report, error = read_report(path, stage="closer")
        assert not error
        assert report == {
            "fixed": [],
            "blocking": ["A", "B"],
            "noted": [],
            "clearable_by_full": ["B"],
        }

    @pytest.mark.parametrize("stage", ["finder", "verifier", "fixer"])
    def test_reserved_key_is_rejected_from_every_non_closer_stage(self, tmp_path, stage):
        path = self.write(tmp_path, clearable_by_full=["A"], unrelated="ignored")
        report, error = read_report(path, stage=stage)
        assert report == {}
        assert stage in error and "clearable_by_full" in error

    @pytest.mark.parametrize(
        "blocking,binding",
        [
            (["A"], "A"),
            (["A"], [1]),
            (["A"], ["B"]),
            (["A"], ["A", "A"]),
            ([], ["noted-only"]),
        ],
    )
    def test_malformed_or_unknown_closer_binding(self, tmp_path, blocking, binding):
        path = tmp_path / "report.json"
        path.write_text(
            json.dumps(
                {
                    "fixed": [],
                    "blocking": blocking,
                    "noted": ["noted-only"],
                    "clearable_by_full": binding,
                }
            )
        )
        report, error = read_report(path, stage="closer")
        assert report == {}
        assert "clearable_by_full" in error

    def test_binding_is_checked_before_items_are_capped(self, tmp_path):
        prefix = "x" * ITEM_CAP
        first, second = prefix + "a", prefix + "b"
        # CONSTRUCTED: two distinct findings the cap collapses onto one string, so a
        # membership test run after capping would accept a binding to neither.
        assert cap_items([first]) == cap_items([second])
        path = self.write(tmp_path, blocking=[first], clearable_by_full=[second])
        report, error = read_report(path, stage="closer")
        assert report == {}
        assert "clearable_by_full" in error

    def test_omitted_stage_keeps_the_three_list_projection(self, tmp_path):
        path = self.write(tmp_path, clearable_by_full=["A"], unrelated="ignored")
        report, error = read_report(path)
        assert not error
        assert report == {"fixed": [], "blocking": ["A", "B"], "noted": []}


FINDING = {"fixed": [], "blocking": ["F"], "noted": []}


class TestRoundProvenance:
    def test_complete_round_records_only_the_closers_validated_occurrences(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=FINDING,
            verify=FINDING,
            fix={"fixed": ["F"], "blocking": ["SAME"], "noted": []},
            close={
                "fixed": [],
                "blocking": ["SAME"],
                "noted": [],
                "clearable_by_full": ["SAME"],
            },
        )
        result = sprint(repo, env, "review")
        assert result.returncode == 0, result.stderr
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["blocking"] == ["SAME", "SAME"]
        assert round_["clearable_by_full"] == ["SAME"]

    def test_a_binding_to_only_the_fixers_text_refuses_the_closer_report(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=FINDING,
            verify=FINDING,
            fix={"fixed": ["F"], "blocking": ["SAME"], "noted": []},
            close={
                "fixed": [],
                "blocking": [],
                "noted": [],
                "clearable_by_full": ["SAME"],
            },
        )
        result = sprint(repo, env, "review")
        assert result.returncode == 2
        assert "clearable_by_full" in result.stderr and "matching blocker" in result.stderr

    def test_a_reserved_key_from_a_non_closer_stage_records_an_incomplete_round(self, tmp_path):
        sentinel = tmp_path / "tier-ran"
        config = (
            f"release: sprint\nroles:\n  reviewer: claude/opus\ntests:\n  full: touch {sentinel}\n"
        )
        repo, env, _g = make_repo(tmp_path, config=config)
        staged_stub(
            tmp_path,
            find=FINDING,
            verify=FINDING,
            fix={
                "fixed": ["F"],
                "blocking": [],
                "noted": [],
                "clearable_by_full": [],
            },
        )
        result = sprint(repo, env, "review")
        assert result.returncode == 2
        assert "fixer" in result.stderr and "clearable_by_full" in result.stderr
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]
        land = sprint(repo, env, "land")
        assert land.returncode == 2 and not sentinel.exists()
