import shutil
import subprocess

import pytest
from xpcore import config, setup

REAL_WHICH = shutil.which


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    root = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def lefthook(tmp_path, monkeypatch):
    """A stand-in lefthook on PATH that records how it was called."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "lefthook"
    fake.write_text(f'#!/bin/sh\necho "$@" > {tmp_path / "lefthook.called"}\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    return tmp_path / "lefthook.called"


def test_refuses_when_xp_exists(repo, capsys):
    (repo / ".xp").mkdir()
    with pytest.raises(SystemExit) as exc:
        setup.cmd_setup(None)
    assert exc.value.code == 2 and "edit the files there" in capsys.readouterr().err
    assert not (repo / ".githooks").exists()


def test_scaffolds_lefthook_when_no_routing(repo, lefthook, capsys):
    assert setup.cmd_setup(None) == 0
    for name in ("config.yml", "system.md", "constraints.md"):
        assert (repo / ".xp" / name).is_file()
    assert (repo / "lefthook.yml").is_file() and (repo / ".githooks" / "hook-lib.sh").is_file()
    assert (repo / ".githooks" / "pre-push" / "secrets").stat().st_mode & 0o111
    assert lefthook.read_text().strip() == "install"
    assert (config.data_root() / "plan.md").is_file()
    out = capsys.readouterr().out
    assert "recover: python3 " in out and out.rstrip().endswith("then /create-sprint")


def test_without_lefthook_writes_githooks_and_sets_hooks_path(repo, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n: None if n == "lefthook" else REAL_WHICH(n))
    assert setup.cmd_setup(None) == 0
    for hook in setup.GITHOOKS:
        assert (repo / ".githooks" / hook).stat().st_mode & 0o111
    hooks_path = subprocess.run(["git", "config", "core.hooksPath"], capture_output=True, text=True)
    assert hooks_path.stdout.strip() == ".githooks" and not (repo / "lefthook.yml").exists()


def test_skips_the_wall_when_lefthook_yml_exists(repo, lefthook, capsys):
    (repo / "lefthook.yml").write_text("pre-commit: {}\n")
    assert setup.cmd_setup(None) == 0
    assert (repo / "lefthook.yml").read_text() == "pre-commit: {}\n"
    assert not (repo / ".githooks").exists() and not lefthook.exists()
    out = capsys.readouterr().out
    assert "wall skipped: lefthook.yml" in out and "`sprint`" in out
    assert (repo / ".xp" / "config.yml").is_file()


def test_skips_the_wall_for_live_git_hooks(repo, capsys):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\n")
    assert setup.cmd_setup(None) == 0
    assert "wall skipped: live hooks in .git/hooks (pre-commit)" in capsys.readouterr().out
