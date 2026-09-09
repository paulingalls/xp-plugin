"""story-014: the sprint close marshals its reviews.
Split from test_sprint_close.py at sprint-004 open."""

import json

from close_helpers import launches
from sprint_helpers import (
    SPRINT_ID,
    head,
    make_repo,
    marker_path,
    section,
    sprint,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"


class TestModeSwitch:
    """Note bae0b87b: findings handed in -> validate each; none handed in -> run
    the full pass. The mode switch is what BOUNDS the work — sprint-002's close
    re-reviewed four fix-commits with no prior findings to bound the pass."""

    def test_round_1_tells_the_reviewer_to_run_the_full_pass(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        # the SECTION's own words: the charter also says "run the full pass",
        # so a bare "full pass" grep passes on every bundle ever built
        assert "none — run the full pass yourself" in launches(tmp_path)[0]["stdin"]

    def test_a_second_round_carries_the_prior_findings(self, tmp_path):
        """Read from the MARKER state, which is where close.py keeps rounds.
        Reading `reports/` off disk would be a second source of truth — so the
        fixture CONSTRUCTS the marker, never the report file."""
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "rounds": [
                        {"fixed": [], "blocking": ["ROUND-1-BLOCKER"], "noted": ["ROUND-1-NOTE"]}
                    ],
                    "shown_sha": head(repo, env),
                }
            )
        )
        assert sprint(repo, env, "review").returncode == 0
        ran = launches(tmp_path)
        assert len(ran) == 1, "a confirming delta paid for another fanout"
        bundle = ran[0]["stdin"]
        assert "ROUND-1-BLOCKER" in bundle and "ROUND-1-NOTE" in bundle
        assert DELTA in bundle
        assert "validate that each was addressed; do not re-derive the diff" in bundle
        assert "run the full pass yourself" not in bundle, "handed findings AND told to re-derive"

    def test_prior_items_are_once_only_in_the_confirming_round_not_sprint_land(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        prior = {
            "fixed": [f"prior-fixed-{i:02}" for i in range(25)],
            "blocking": ["prior-blocking-0", "prior-blocking-1"],
            "noted": ["prior-noted-0", "prior-noted-1"],
        }
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [prior], "shown_sha": head(repo, env)}))

        assert sprint(repo, env, "review").returncode == 0
        ran = launches(tmp_path)
        assert len(ran) == 1
        carried = section(
            ran[0]["stdin"],
            "Findings from earlier rounds",
            f"The stories in sprint {SPRINT_ID}",
        )
        items = [item for status_items in prior.values() for item in status_items]
        for item in items:
            assert carried.count(item) == 1, item
        assert "more, in full" not in carried

        landed = sprint(repo, env, "land", "--dry-run")
        assert landed.returncode == 0, landed.stderr
        assert "--body-file <release-pr-body>" in landed.stdout
        assert "Review round" not in landed.stdout
        assert all(item not in landed.stdout for item in items)
