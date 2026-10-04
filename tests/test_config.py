import hashlib
import os
import subprocess

import pytest
from xpcore import config

CONFIG = """\
release: story   # trailing comment
# trunk: develop
version_files: package.json, pyproject.toml
sprint_cap: 6
debt_budget: 0.2
roles:
  lead: claude/opus
  executor: codex/gpt-6/high
  reviewer: claude/opus
"""


def repo(path, config_text=CONFIG):
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True)
    if config_text is not None:
        (path / ".xp").mkdir()
        (path / ".xp" / "config.yml").write_text(config_text)
    (path / "README").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    root = repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    return root


def refused(capsys, call, *args):
    with pytest.raises(SystemExit) as exit_info:
        call(*args)
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("refused: ")
    return err


def test_missing_config_refuses_with_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.chdir(repo(tmp_path / "bare", config_text=None))
    assert "xp.py setup" in refused(capsys, config.load_config)


def test_parse_config_maps_comments_and_numbers(project):
    cfg = config.load_config()
    assert cfg["release"] == "story"
    assert "trunk" not in cfg
    assert cfg["version_files"] == "package.json, pyproject.toml"
    assert cfg["sprint_cap"] == 6 and cfg["debt_budget"] == 0.2
    assert cfg["roles"]["executor"] == "codex/gpt-6/high"


def test_malformed_line_refuses_naming_it(capsys):
    err = refused(capsys, config.parse_config, "release: sprint\n- listed\n")
    assert "line 2" in err


def test_role_resolution(project):
    assert config.role("executor") == ("codex", "gpt-6", "high")
    assert config.role("lead") == ("claude", "opus", "")
    assert config.role("plan-reviewer") == ("claude", "opus", "")
    assert config.role("executor", "claude/sonnet/low") == ("claude", "sonnet", "low")


def test_bad_or_missing_role_refuses(project, capsys):
    assert "planner" in refused(capsys, config.role, "planner")
    assert "harness/model" in refused(capsys, config.role, "executor", "gpt/x")


def test_trunk_prefers_config_then_origin_head_then_main(project, tmp_path):
    assert config.trunk() == "main"
    origin = repo(tmp_path / "origin", config_text=None)
    subprocess.run(["git", "branch", "-qm", "develop"], cwd=origin, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], check=True)
    subprocess.run(["git", "remote", "set-head", "origin", "-a"], check=True, capture_output=True)
    assert config.trunk() == "develop"
    (project / ".xp" / "config.yml").write_text(CONFIG + "trunk: release\n")
    assert config.trunk() == "release"


def test_data_root_hashes_common_dir_shared_by_worktrees(tmp_path, monkeypatch):
    monkeypatch.delenv("XP_DATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = repo(tmp_path / "repo")
    tree = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "s", str(tree)], cwd=root, check=True)
    digest = hashlib.sha256(os.path.realpath(root / ".git").encode()).hexdigest()[:12]
    monkeypatch.chdir(root)
    main_root = config.data_root()
    monkeypatch.chdir(tree)
    assert config.data_root() == main_root == tmp_path / "home" / ".xp" / "data" / digest


def test_outside_git_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("XP_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert "git repository" in refused(capsys, config.data_root)


def test_sprint_branch_record_and_clear(project, capsys):
    assert config.sprint_branch_name("12") == config.sprint_branch_name("012") == "sprint-012"
    assert config.sprint_branch() == ""
    config.record_sprint_branch("sprint-012")
    config.record_sprint_branch("sprint-012")
    assert config.sprint_branch() == "sprint-012"
    assert "sprint-012" in refused(capsys, config.record_sprint_branch, "sprint-013")
    config.clear_sprint_branch()
    assert config.sprint_branch() == ""


def test_plugin_root_holds_the_scripts():
    assert (config.plugin_root() / "scripts" / "xp.py").is_file()
