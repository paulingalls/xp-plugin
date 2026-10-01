from close_helpers import close, make_repo, marker, stub_reviewer


class TestFullReviewFindings:
    """story-008 close review, round 5 — the first review over the whole story."""

    def test_a_full_re_review_appends_rather_than_erasing_prior_rounds(self, tmp_path):
        """R5F1: the non-delta path reset verdicts while the delta path appended
        — the same rule fixed in one of its two implementations. The merge body
        then labelled the survivor 'round 1', asserting round 1 found what round
        2 found. This is the exact workflow the full_sha bug prescribes."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={
                "fixed": [],
                "blocking": ["round one blocker"],
                "schema": 2,
                "dropped": [],
                "debt": [],
            },
        )
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 7\n")
        g("add", "-A")
        g("commit", "-qm", "lead fixes the findings")
        stub_reviewer(
            tmp_path,
            report={
                "fixed": [],
                "blocking": [],
                "schema": 2,
                "dropped": [
                    {"finding": item, "reason": "fixture reason"} for item in ["round two note"]
                ],
                "debt": [],
            },
        )
        close(repo, env, "review")
        rounds = marker(tmp_path)["rounds"]
        assert [r["blocking"] for r in rounds] == [["round one blocker"], []]
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B", "main").stdout
        assert "Review round 1: 0 fixed · 1 blocking · 0 dropped · 0 debt" in body
        assert "blocking: round one blocker" in body
        assert "Review round 2: 0 fixed · 0 blocking · 1 dropped · 0 debt" in body
