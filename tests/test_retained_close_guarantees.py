"""Consumer guarantees that outlive patch-based review and salvage."""

import pytest
from close_helpers import CLAUDE_SH, close, make_repo, marker_file, worktree_land_setup
from story_review_helpers import flow_repo, invoke


def test_land_from_worktree_merges_and_removes_only_its_worktree(tmp_path):
    _repo, env, git, tree, branch = worktree_land_setup(tmp_path)
    bystander = tmp_path / "bystander"
    assert git("worktree", "add", "-b", "unrelated", str(bystander), "main").returncode == 0
    result = close(tree, env, "land", "--merge-mode", "local")
    assert result.returncode == 0, result.stderr
    assert not tree.exists()
    assert bystander.exists()
    assert branch in git("log", "-1", "--format=%s").stdout
    assert "[done]" in (tmp_path / "data/plan.md").read_text()
    assert git("show-ref", "--verify", f"refs/heads/{branch}").returncode != 0


@pytest.mark.parametrize("dirty", [False, True])
def test_dirty_integration_tree_is_checked_before_validation(tmp_path, dirty):
    sentinel = tmp_path / "verify-ran"
    repo, env, _git, tree, _branch = worktree_land_setup(tmp_path, verify=f"touch {sentinel}")
    sentinel.unlink()
    for receipt in (tmp_path / "data/markers").glob("*.verify.json"):
        receipt.unlink()
    if dirty:
        (repo / "dirt.txt").write_text("uncommitted\n")
    result = close(tree, env, "land", "--merge-mode", "local")
    if dirty:
        assert result.returncode == 2 and "dirty" in result.stderr, result.stderr
        assert not sentinel.exists()
        assert tree.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert sentinel.exists()


@pytest.mark.parametrize("declared", [False, True])
def test_wrapped_files_authorizes_only_the_named_project_file(tmp_path, declared):
    files = "src/thing.py, .xp/config.yml"
    if declared:
        files += ",\n.xp/system.md"
    repo, env, git, key, _events, _hooks = flow_repo(tmp_path, scenario="fixed", files=files)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "    Path('src/thing.py').write_text",
            "    Path('.xp/system.md').write_text('Worktree bootstrap: none needed\\n')\n"
            "    subprocess.run(['git','add','.xp/system.md'],check=True)\n"
            "    Path('src/thing.py').write_text",
        )
    )
    result = invoke(repo, env, key)
    assert result.returncode == (0 if declared else 2), result.stderr
    if not declared:
        assert "undeclared .xp" in result.stderr
        assert not marker_file(tmp_path).exists()
    assert git("show", "HEAD:.xp/system.md").stdout == "Worktree bootstrap: none needed\n"


def test_silent_review_refuses_with_a_usable_timeout_override(tmp_path):
    repo, env, _git = make_repo(tmp_path)
    binary = tmp_path / "bin/claude"
    binary.write_text(CLAUDE_SH + "sleep 30\n")
    result = close(repo, env | {"XP_AGENT_TIMEOUT": "1"}, "review")
    assert result.returncode == 2 and "produced NO OUTPUT" in result.stderr, result.stderr
    assert "XP_AGENT_TIMEOUT" in result.stderr
    assert not marker_file(tmp_path).exists()
