"""Failed land commands leave a bounded, actionable final line."""

import json
import shutil
import subprocess
import sys

import pytest
from close_helpers import CLOSE, close, make_repo, marker_file
from sprint_helpers import CLOSE as SPRINT_CLOSE
from sprint_helpers import head
from sprint_helpers import make_repo as sprint_repo
from test_close_free import reviewed
from test_sprint_land import record_release, release_state


def run_redirected(repo, env, argv, output):
    with output.open("w") as stream:
        result = subprocess.run(argv, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT)
    return result.returncode, output.read_text().splitlines()


def failing_command(tmp_path, env, executable, match):
    directory = tmp_path / "fail-bin"
    directory.mkdir(exist_ok=True)
    script = directory / executable
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        f"if {match!r} in sys.argv[1:] and ({executable!r} != 'git' or 'push' in sys.argv[1:]):\n"
        "    for n in range(1000):\n"
        "        print(f'HOOK-LINE-{n:04d}', file=sys.stderr)\n"
        "        if n == 998: print('Logs preserved at: /tmp/hook.log', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        + (
            f"os.execv({shutil.which('git')!r}, ['git', *sys.argv[1:]])\n"
            if executable == "git"
            else "sys.exit(0)\n"
        )
    )
    script.chmod(0o755)
    return {**env, "PATH": f"{directory}:{env['PATH']}"}


def setup_mode(tmp_path, mode):
    if mode == "free":
        repo, env, _ = reviewed(tmp_path)
        argv = [sys.executable, str(CLOSE), "free", "fix-typo", "land"]
    elif mode == "story":
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        assert g("remote", "add", "origin", str(origin)).returncode == 0
        assert close(repo, env, "review").returncode == 0
        argv = [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"]
    else:
        repo, env, g = sprint_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        assert g("remote", "add", "origin", str(origin)).returncode == 0
        record_release(tmp_path, release_state(repo, env))
        argv = [sys.executable, str(SPRINT_CLOSE), "sprint", "2", "land"]
    return repo, env, argv


def working_gh(tmp_path, env):
    path = tmp_path / "bin" / "gh"
    path.write_text("#!/usr/bin/env python3\n")
    path.chmod(0o755)
    return env


@pytest.mark.parametrize("mode", ["free", "story", "sprint"])
def test_failed_push_ends_with_bounded_refusal(tmp_path, mode):
    repo, env, argv = setup_mode(tmp_path, mode)
    working_gh(tmp_path, env)
    env = failing_command(tmp_path, env, "git", "push")
    rc, lines = run_redirected(repo, env, argv, tmp_path / "output.txt")
    assert rc == 2, lines[-10:]
    assert lines[-1].startswith("refused:"), lines[-5:]
    assert "git push -u origin" in lines[-1] and "exit 1" in lines[-1]
    assert lines[-2] == "HOOK-LINE-0999"
    assert "Logs preserved at: /tmp/hook.log" in lines[-4:]
    assert sum(line.startswith("HOOK-LINE-") for line in lines) < 50


@pytest.mark.parametrize("mode", ["free", "story", "sprint"])
def test_failed_pr_create_ends_with_one_line_refusal(tmp_path, mode):
    repo, env, argv = setup_mode(tmp_path, mode)
    working_gh(tmp_path, env)
    env = failing_command(tmp_path, env, "gh", "create")
    rc, lines = run_redirected(repo, env, argv, tmp_path / "output.txt")
    assert rc == 2, lines[-10:]
    assert lines[-1].startswith("refused:") and "gh pr create" in lines[-1]
    assert "exit 1" in lines[-1] and "Review round" not in lines[-1]
    assert lines[-2] == "HOOK-LINE-0999"
    assert sum(line.startswith("HOOK-LINE-") for line in lines) < 50


def test_failed_pr_merge_elides_multiround_verdict(tmp_path):
    repo, env, g = make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert close(repo, env, "review").returncode == 0
    marker = marker_file(tmp_path)
    state = json.loads(marker.read_text())
    state["rounds"] *= 2
    for round_ in state["rounds"]:
        round_["fixed"] = ["first finding", "second finding"]
        round_["noted"] = ["third finding"]
    marker.write_text(json.dumps(state))
    env = failing_command(tmp_path, env, "gh", "merge")
    argv = [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"]
    rc, lines = run_redirected(repo, env, argv, tmp_path / "output.txt")
    assert rc == 2, lines[-10:]
    assert lines[-1].startswith("refused:") and "gh pr merge" in lines[-1]
    assert "exit 1" in lines[-1] and "finding" not in lines[-1]
    assert lines[-2] == "HOOK-LINE-0999"


def test_disclosure_precedes_failed_push(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    reviewed = head(repo, env)
    (repo / "reviewer-change.py").write_text("REVIEWER_CHANGE = True\n")
    assert g("add", "-A").returncode == 0
    assert g("commit", "-qm", "REVIEWER-DISCLOSURE").returncode == 0
    state = release_state(repo, env)
    state["rounds"][0]["reviewed_head"] = reviewed
    record_release(tmp_path, state)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    working_gh(tmp_path, env)
    env = failing_command(tmp_path, env, "git", "push")
    argv = [sys.executable, str(SPRINT_CLOSE), "sprint", "2", "land"]
    rc, lines = run_redirected(repo, env, argv, tmp_path / "output.txt")
    assert rc == 2, lines[-10:]
    assert next(i for i, line in enumerate(lines) if "REVIEWER-DISCLOSURE" in line) < next(
        i for i, line in enumerate(lines) if line == "HOOK-LINE-0989"
    )
    assert lines[-1].startswith("refused:")


@pytest.mark.parametrize("dependencies", [True, False])
def test_local_push_identifies_dependency_refresh_only_when_needed(tmp_path, dependencies):
    paths = ["src/thing.py"]
    if dependencies:
        paths += ["package.json", "pnpm-lock.yaml", "patches/tool.patch"]
    else:
        paths += ["package.json.backup", "patches-old/tool.patch"]
    repo, env, g = make_repo(tmp_path, files=", ".join(paths))
    for name in paths[1:]:
        path = repo / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("changed\n")
    assert g("add", "-A").returncode == 0
    assert g("commit", "-qm", "additional changes").returncode == 0
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert g("checkout", "-q", "main").returncode == 0
    tree = tmp_path / "story-tree"
    assert g("worktree", "add", str(tree), branch).returncode == 0
    assert close(tree, env, "review").returncode == 0
    env = failing_command(tmp_path, env, "git", "main")
    argv = [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "local"]
    rc, lines = run_redirected(tree, env, argv, tmp_path / "output.txt")
    output = "\n".join(lines)
    assert rc == 3, lines[-10:]
    assert "incomplete — the merge landed. Re-run or resolve them:" in output
    assert "git push origin main" in output
    if dependencies:
        for name in paths[1:]:
            assert name in output
        assert str(repo) in output
        assert "Refresh dependencies there, then re-run `git push origin main`" in output
    else:
        assert "Refresh dependencies" not in output
        assert "dependency files changed" not in output
