import json

import pytest
from bookkeep import render_prior_rounds
from close_helpers import close, make_repo
from now_or_never_helpers import write_report
from review_report import read_report


class TestLegacyState:
    @pytest.mark.parametrize("shape", [None, 7, {"fixed": [], "blocking": [], "noted": "bad"}])
    def test_missing_malformed_and_legacy_are_distinct(self, tmp_path, shape):
        path = tmp_path / "report.json"
        if shape is not None:
            path.write_text(json.dumps(shape))
        assert read_report(path, fresh=False)[1]
        old = {"fixed": [], "blocking": [], "noted": ["unjudged finding"]}
        parsed, error = read_report(write_report(tmp_path, old), fresh=False)
        assert not error and parsed["legacy_untriaged"] == ["unjudged finding"]
        shown = render_prior_rounds([old])
        assert "legacy_untriaged" in shown and "unjudged finding" in shown
        assert "dropped:" not in shown

    def test_completed_legacy_story_state_still_lands(self, tmp_path):
        from close_helpers import marker_file

        repo, env, g = make_repo(tmp_path)
        head = g("rev-parse", "HEAD").stdout.strip()
        old = {"fixed": [], "blocking": [], "noted": ["old finding"]}
        marker_file(tmp_path).write_text(
            json.dumps(
                {
                    "rounds": [old],
                    "shown_sha": head,
                    "reviewed_head": head,
                    "review_base": g("merge-base", "main", "HEAD").stdout.strip(),
                }
            )
        )
        result = close(repo, env, "land")
        assert result.returncode == 0, result.stderr
        assert "legacy/untriaged" in result.stdout and "old finding" in result.stdout
        assert json.loads((tmp_path / "data" / "closes.jsonl").read_text())["rounds"] == [old]

    @pytest.mark.parametrize("kind", ["free", "sprint"])
    @pytest.mark.parametrize("blocking", [False, True])
    def test_completed_legacy_story_free_and_sprint_state_still_lands(
        self, tmp_path, kind, blocking
    ):
        from close_free_card_cases import carded_review
        from close_helpers import free, marker_file
        from sprint_helpers import make_repo as sprint_repo
        from sprint_helpers import marker_path, sprint
        from sprint_release_body_cases import release_tools

        old = {
            "fixed": [],
            "blocking": ["old blocker"] if blocking else [],
            "noted": ["old unjudged finding"],
        }
        if kind == "free":
            repo, env, g, _, key = carded_review(tmp_path)
            shown = g("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
            base = g("-C", str(repo), "merge-base", "main", "HEAD").stdout.strip()
            path = marker_file(tmp_path, key)
            state = {
                "rounds": [old],
                "shown_sha": shown,
                "reviewed_head": shown,
                "review_base": base,
            }
            path.write_text(json.dumps(state))
            result = free(repo, env, "fix-typo", "land")
            output = result.stdout
        else:
            repo, env, g = sprint_repo(tmp_path)
            shown = g("rev-parse", "HEAD").stdout.strip()
            base = g("merge-base", "main", "HEAD").stdout.strip()
            path = marker_path(tmp_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            old_round = old | {"shown_sha": shown, "reviewed_head": shown, "review_base": base}
            state = {
                "rounds": [old_round],
                "shown_sha": shown,
                "reviewed_head": shown,
                "review_base": base,
            }
            path.write_text(json.dumps(state))
            (tmp_path / "data/closes.jsonl").write_text(
                json.dumps(
                    {
                        "story": "story-042",
                        "title": "legacy story",
                        "merge_sha": shown,
                        "rounds": [old],
                    }
                )
                + "\n"
            )
            receipt = release_tools(tmp_path, env, g)
            result = sprint(repo, env, "land")
            output = json.loads(receipt.read_text())["body"] if receipt.exists() else result.stdout
        if blocking:
            assert result.returncode == 2 and "old blocker" in result.stderr
        else:
            assert result.returncode == 0, result.stderr
            assert "legacy_untriaged" in output or "legacy/untriaged" in output
            assert "old unjudged finding" in output and "dropped: old unjudged" not in output
