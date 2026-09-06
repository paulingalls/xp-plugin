import subprocess

import pytest
from test_secret_hooks import commit, generated_secret, git, remote_sha, scaffold, wall_repo
from test_secret_hooks import real_tools as real_tools


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_new_ref_scans_a_commit_published_only_to_another_remote(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant, install=False)
    commit(repo, env, "base.txt", "base\n", "base")
    origin = tmp_path / f"origin-{variant}.git"
    mirror = tmp_path / f"mirror-{variant}.git"
    for remote in (origin, mirror):
        created = subprocess.run(
            ["git", "init", "-q", "--bare", str(remote)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr
    assert git(repo, "remote", "add", "origin", str(origin), env=env).returncode == 0
    assert git(repo, "remote", "add", "mirror", str(mirror), env=env).returncode == 0
    commit(repo, env, "secret.txt", generated_secret(), "secret")
    assert git(repo, "push", "-q", "mirror", "main:published", env=env).returncode == 0
    scaffold(repo, env, variant)

    pushed = git(repo, "push", "origin", "main:new-on-origin", env=env)

    assert pushed.returncode != 0
    assert not remote_sha(repo, env, "refs/heads/new-on-origin")
    assert "leaks found" in (pushed.stdout + pushed.stderr).lower()
