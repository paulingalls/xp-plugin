"""Sprint-open owns one canonical branch record per clone."""

from sprint_helpers import PLAN, make_repo, sprint


def test_start_records_and_prints_each_clones_own_branch_before_stories(tmp_path):
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        repo, env, _g = make_repo(
            root,
            plan=PLAN.replace(
                "#### story-043 — also done   [done]",
                "#### story-043 — also done   [in-progress]",
            ),
        )
        branch = "sprint-002"
        (root / "data" / "sprint_branch").unlink()
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert (root / "data" / "sprint_branch").read_text().strip() == branch
        assert branch in r.stdout


def test_start_refuses_a_branch_post_merge_cannot_attribute_to_the_sprint(tmp_path):
    repo, env, g = make_repo(tmp_path)
    g("branch", "-m", "sprint-2")
    branch = tmp_path / "data" / "sprint_branch"
    branch.unlink()

    r = sprint(repo, env, "start")

    assert r.returncode == 2
    assert "sprint-002" in r.stderr and "sprint-2" in r.stderr
    assert not branch.exists()
