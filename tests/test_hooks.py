import subprocess

import pytest
from xpcore import hooks


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    path = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    monkeypatch.chdir(path)
    return path


def script_hook(root, body):
    hook = root / ".githooks" / "sprint"
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\n{body}\n")
    hook.chmod(0o755)


def test_any_lefthook_spelling_names_the_lefthook_sprint_hook(root):
    (root / "lefthook.yaml").write_text("sprint: {}\n")
    assert hooks.sprint_hook(root) == ["lefthook", "run", "sprint"]


def test_red_sprint_hook_returns_its_exit_code(root):
    script_hook(root, "echo boom; exit 3")
    assert hooks.run_sprint_hook(root, "s-hook") == 3
    assert "boom" in hooks.log_path("s-hook").read_text()


def test_missing_sprint_hook_refuses_rather_than_passing(root, capsys):
    with pytest.raises(SystemExit) as exit_:
        hooks.run_sprint_hook(root, "s-hook")
    assert exit_.value.code == 2 and "no sprint hook" in capsys.readouterr().err


def test_missing_binary_is_red(root):
    assert hooks.run_acceptance([["no-such-binary-xp"]], root, "acc") == 127
