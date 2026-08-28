"""Sprint-open owns one canonical branch record per clone."""

import shlex
import sys

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


def test_the_branch_guard_refuses_before_the_project_command(tmp_path):
    """Constraint 2 on the guard's POSITION, not only its verdict: placed below
    lc.run it would create the project's sprint for an open that then refuses,
    and the retry after the rename would create it a second time."""
    repo, env, g = make_repo(tmp_path)
    ran = tmp_path / "opened"
    script = tmp_path / "open.py"
    script.write_text(f"import pathlib; pathlib.Path({str(ran)!r}).write_text('ran')\n")
    config = repo / ".xp" / "config.yml"
    command = shlex.join([sys.executable, str(script)])
    config.write_text(f"lifecycle_command: {command}\n" + config.read_text())
    g("add", "-A")
    g("commit", "-qm", "configure lifecycle")
    g("branch", "-m", "sprint-2")
    (tmp_path / "data" / "sprint_branch").unlink()

    r = sprint(repo, env, "start")

    assert r.returncode == 2 and "sprint-002" in r.stderr
    assert not ran.exists(), "project code ran before the branch guard"


def test_a_sprint_the_pipeline_opened_is_one_post_merge_will_release(tmp_path):
    """sprint_close.cmd_start and close.release.cmd_post_merge spell the canonical
    branch from the id INDEPENDENTLY, which is the divergence that shipped: open
    recorded a name release refused to attribute. Every other test fixes one end's
    spelling by hand, so only walking open -> release pins the two together."""
    repo, env, g = make_repo(tmp_path)
    (tmp_path / "data" / "sprint_branch").unlink()

    assert sprint(repo, env, "start").returncode == 0
    g("tag", "v0.2.1")
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
    released = sprint(repo, env, "post-merge")

    assert released.returncode == 0, released.stderr
    assert "v0.3.0" in g("tag").stdout.split()
