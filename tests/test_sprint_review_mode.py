"""Later explicit review judges changed integration without committing."""

import json

from sprint_helpers import bundles, head, launches, make_repo, marker_path, sprint, staged_stub


def test_lead_corrected_delta_requires_explicit_integration_judgment(tmp_path):
    repo, env, g = make_repo(tmp_path)
    first = head(repo, env)
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "blocking": ["current integration blocker"],
                        "fixed": ["settled fix"],
                        "dropped": [{"finding": "settled drop", "reason": "refuted"}],
                        "shown_sha": first,
                    }
                ],
                "shown_sha": first,
            }
        )
    )
    unchanged = sprint(repo, env, "review")
    assert unchanged.returncode == 2 and launches(tmp_path) == []
    (repo / "src.py").write_text("A = 2\n")
    assert g("commit", "-qam", "lead correction").returncode == 0
    corrected = head(repo, env)
    assert sprint(repo, env, "land", "--dry-run").returncode == 2
    assert launches(tmp_path) == []
    staged_stub(tmp_path)

    result = sprint(repo, env, "review")

    assert result.returncode == 0, result.stderr
    assert len(launches(tmp_path)) == 1
    assert len(bundles(tmp_path, "solution")) == 1
    assert head(repo, env) == corrected
    bundle = bundles(tmp_path, "solution")[0]
    assert "current integration blocker" in bundle
    assert "settled fix" not in bundle and "settled drop" not in bundle
    assert "The delta since the last recorded round" in bundle
