import os
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


def test_acceptance_is_a_shell_line_and_its_exit_code_is_the_verdict(root):
    assert hooks.run_acceptance("no-such-binary-xp", root, "acc") == 127
    assert hooks.run_acceptance("false && true", root, "x") != 0
    assert hooks.run_acceptance("echo ok | grep -q ok", root, "y") == 0


def test_sprint_hook_ignores_lefthook_switches_in_the_leads_env(root, tmp_path, monkeypatch):
    (root / "lefthook.yml").write_text("sprint: {}\n")
    (bin_ := tmp_path / "bin").mkdir()
    (bin_ / "lefthook").write_text("#!/bin/sh\nenv | grep '^LEFTHOOK' && exit 1\nexit 0\n")
    (bin_ / "lefthook").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    monkeypatch.setenv("LEFTHOOK", "0")
    monkeypatch.setenv("LEFTHOOK_EXCLUDE", "tests")
    assert hooks.run_sprint_hook(root, "s-hook") == 0
