import os
import stat
import sys
from pathlib import Path

import pytest
from test_secret_hooks import (
    ROOT,
    SETUP,
    add_remote,
    commit,
    generated_secret,
    git,
    init_repo,
    isolated_env,
    publish_base,
    remote_sha,
    run,
    scaffold,
    wall_repo,
)
from test_secret_hooks import real_tools as real_tools


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_existing_ref_scans_remote_to_local(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    publish_base(repo, env, tmp_path)
    commit(repo, env, "scanned.txt", "clean\n", "clean")
    green = git(repo, "push", "-q", "origin", "main", env=env)
    assert green.returncode == 0, green.stderr
    base = remote_sha(repo, env)
    commit(repo, env, "scanned.txt", generated_secret(), bypass=True)
    red = git(repo, "push", "origin", "main", env=env)
    assert red.returncode != 0 and remote_sha(repo, env) == base


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_new_ref_excludes_other_remote_history(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant, install=False)
    commit(repo, env, "base.txt", "base\n", "base")
    add_remote(repo, env, tmp_path)
    commit(repo, env, "legacy.txt", generated_secret(), "legacy")
    assert git(repo, "push", "-q", "origin", "main:legacy", env=env).returncode == 0
    (repo / "legacy.txt").write_text("rotated\n")
    git(repo, "add", "legacy.txt", env=env)
    git(repo, "commit", "-q", "-m", "rotate", env=env)
    scaffold(repo, env, variant)
    clean = git(repo, "push", "-q", "origin", "main:clean-new", env=env)
    assert clean.returncode == 0, clean.stderr
    git(repo, "checkout", "-q", "-b", "leaking-new", env=env)
    commit(repo, env, "new-secret.txt", generated_secret(), bypass=True)
    red = git(repo, "push", "origin", "HEAD:leaking-new", env=env)
    assert red.returncode != 0 and not remote_sha(repo, env, "refs/heads/leaking-new")
    assert "leaks found" in (red.stdout + red.stderr).lower()


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_every_pushed_ref_line_is_scanned(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    publish_base(repo, env, tmp_path)
    git(repo, "checkout", "-q", "-b", "clean", env=env)
    commit(repo, env, "clean.txt", "clean\n", "clean")
    git(repo, "checkout", "-q", "main", env=env)
    git(repo, "checkout", "-q", "-b", "leaking", env=env)
    commit(repo, env, "secret.txt", generated_secret(), bypass=True)
    result = git(repo, "push", "origin", "clean:two-clean", "leaking:two-leaking", env=env)
    assert result.returncode != 0
    assert not remote_sha(repo, env, "refs/heads/two-clean")
    assert not remote_sha(repo, env, "refs/heads/two-leaking")


def test_lefthook_blocks_post_sync_empty_diff_secret_history(tmp_path, real_tools):
    repo, env = wall_repo(tmp_path, real_tools, "lefthook")
    base = publish_base(repo, env, tmp_path)
    _, secret_sha = commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
    (repo / "secret.txt").unlink()
    git(repo, "add", "-u", env=env)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "remove", env=env)
    config = repo / "lefthook.yml"
    config.write_text(config.read_text() + "\n# force hook resync\n")

    pushed = git(repo, "push", "origin", "main", env=env)

    output = (pushed.stdout + pushed.stderr).lower()
    assert pushed.returncode != 0 and remote_sha(repo, env) == base
    assert secret_sha in output
    assert "secrets (skip)" not in output and "no matching push files" not in output


def test_lefthook_delivers_remote_and_ref_stream_to_scanner(tmp_path, real_tools):
    repo, env = wall_repo(tmp_path, real_tools, "lefthook")
    calls = tmp_path / "gitleaks.calls"
    scanner = Path(env["PATH"].split(":", 1)[0]) / "gitleaks"
    scanner.unlink()
    scanner.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    scanner.chmod(scanner.stat().st_mode | stat.S_IEXEC)
    env = env | {"CALLS": str(calls)}
    _, local_sha = commit(repo, env, "clean.txt", "clean\n", "clean")
    calls.unlink()
    add_remote(repo, env, tmp_path)

    pushed = git(repo, "push", "origin", "main:new-ref", env=env)

    assert pushed.returncode == 0, pushed.stderr
    assert calls.read_text().splitlines() == [
        f"git --log-opts={local_sha} --not --remotes=origin --no-banner --redact --verbose"
    ]
    assert "no ref updates" not in (pushed.stdout + pushed.stderr).lower()


def existing_lefthook_repo(tmp_path, real_tools, pre_push):
    repo = tmp_path / "existing"
    env = isolated_env(tmp_path, real_tools, "lefthook")
    init_repo(repo, env)
    (repo / ".xp").mkdir()
    (repo / ".githooks").mkdir()
    hook_lib = repo / ".githooks" / "hook-lib.sh"
    hook_lib.write_bytes((ROOT / "plugins/xp-plugin/templates/hook-lib.sh").read_bytes())
    config = repo / "lefthook.yml"
    config.write_text(pre_push)
    return repo, env, config, hook_lib


OLD_COMMAND_CONFIG = (
    "pre-push:\n"
    "  commands:\n"
    "    secrets:\n"
    "      run: sh -c '. .githooks/hook-lib.sh; secrets_scan_push \"$1\"' _ {1}\n"
    "      use_stdin: true\n"
)


def test_setup_names_the_existing_lefthook_security_migration(tmp_path, real_tools):
    repo, env, config, hook_lib = existing_lefthook_repo(tmp_path, real_tools, OLD_COMMAND_CONFIG)
    before = (config.read_bytes(), hook_lib.read_bytes())

    result = run(repo, sys.executable, str(SETUP), env=env)

    output = (result.stdout + result.stderr).lower()
    assert result.returncode == 2
    assert (config.read_bytes(), hook_lib.read_bytes()) == before
    assert "lefthook.yml lets an outgoing secret reach the remote" in output
    for term in ("pre-push", "scripts", "stdin", "lefthook install"):
        assert term in output
    # the destination, the template it comes from and source_dir are the three things
    # the walk cannot recover from lefthook.yml alone: without any one of them the
    # migrated push refuses with `script does not exist` and names no way out
    assert ".githooks/pre-push/secrets" in output
    assert str(ROOT / "plugins/xp-plugin/templates/lefthook-pre-push-secrets").lower() in output
    assert "source_dir: .githooks" in output


def test_setup_does_not_cry_migration_at_an_already_migrated_config(tmp_path, real_tools):
    migrated = (ROOT / "plugins/xp-plugin/templates/lefthook.yml").read_text()
    repo, env, _, _ = existing_lefthook_repo(tmp_path, real_tools, migrated)

    result = run(repo, sys.executable, str(SETUP), env=env)

    output = (result.stdout + result.stderr).lower()
    assert result.returncode == 2 and "setup never overwrites" in output
    assert "security migration" not in output


def construct_operation(repo, env, operation):
    if operation == "revert":
        commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
        secret = (repo / "secret.txt").read_text()
        (repo / "secret.txt").unlink()
        git(repo, "add", "-u", env=env)
        git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "rotate", env=env)
        return secret
    git(repo, "checkout", "-q", "-b", "source", env=env)
    _, secret_sha = commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
    git(repo, "checkout", "-q", "main", env=env)
    if operation == "no-ff":
        commit(repo, env, "diverge.txt", "clean\n", "diverge")
        git(
            repo,
            "-c",
            "core.hooksPath=/dev/null",
            "merge",
            "--no-ff",
            "source",
            "-m",
            "merge",
            env=env,
        )
    elif operation == "fast-forward":
        git(repo, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "source", env=env)
    else:
        git(repo, "-c", "core.hooksPath=/dev/null", "cherry-pick", secret_sha, env=env)


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
@pytest.mark.parametrize("operation", ["no-ff", "fast-forward", "cherry-pick", "revert"])
def test_git_operation_secret_is_blocked_at_pre_push(tmp_path, real_tools, variant, operation):
    if operation == "revert":
        repo, env = wall_repo(tmp_path, real_tools, variant, install=False)
        commit(repo, env, "base.txt", "clean\n", "base")
        secret = construct_operation(repo, env, operation)
        add_remote(repo, env, tmp_path)
        assert git(repo, "push", "-q", "origin", "main", env=env).returncode == 0
        scaffold(repo, env, variant)
        base = remote_sha(repo, env)
        assert git(repo, "revert", "--no-edit", "HEAD", env=env).returncode == 0
        assert (repo / "secret.txt").read_text() == secret
    else:
        repo, env = wall_repo(tmp_path, real_tools, variant)
        base = publish_base(repo, env, tmp_path)
        construct_operation(repo, env, operation)
    result = git(repo, "push", "origin", "main", env=env)
    assert result.returncode != 0 and remote_sha(repo, env) == base


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_remote_secret_is_excluded_but_outgoing_copy_reds(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant, install=False)
    secret = generated_secret()
    commit(repo, env, "secret.txt", secret, "secret")
    (repo / "secret.txt").write_text("rotated\n")
    git(repo, "add", "secret.txt", env=env)
    git(repo, "commit", "-q", "-m", "rotate", env=env)
    add_remote(repo, env, tmp_path)
    git(repo, "push", "-q", "-u", "origin", "main", env=env)
    scaffold(repo, env, variant)
    commit(repo, env, "clean.txt", "clean\n", "clean")
    assert git(repo, "push", "-q", "origin", "main", env=env).returncode == 0
    before = remote_sha(repo, env)
    commit(repo, env, "copy.txt", secret, "copy", bypass=True)
    red = git(repo, "push", "origin", "main", env=env)
    assert red.returncode != 0 and remote_sha(repo, env) == before


def test_push_remediation_requires_history_rewrite(tmp_path, real_tools):
    repo, env = wall_repo(tmp_path, real_tools, "githooks")
    base = publish_base(repo, env, tmp_path)
    commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
    first = git(repo, "push", "origin", "main", env=env)
    assert first.returncode != 0
    refusal = (first.stdout + first.stderr).lower()
    assert "rewrite" in refusal and "outgoing history" in refusal and "re-stage" not in refusal
    (repo / "secret.txt").unlink()
    git(repo, "add", "-u", env=env)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "remove", env=env)
    assert git(repo, "push", "origin", "main", env=env).returncode != 0
    git(repo, "reset", "--soft", base, env=env)
    (repo / "clean-final.txt").write_text("clean\n")
    git(repo, "add", "clean-final.txt", env=env)
    assert git(repo, "commit", "-q", "-m", "clean final tree", env=env).returncode == 0
    assert git(repo, "push", "-q", "origin", "main", env=env).returncode == 0
    (repo / "index-secret.txt").write_text(generated_secret())
    git(repo, "add", "index-secret.txt", env=env)
    index_red = git(repo, "commit", "-m", "index red", env=env)
    assert "re-stage" in (index_red.stdout + index_red.stderr).lower()
    (repo / "index-secret.txt").write_text("rotated\n")
    git(repo, "add", "index-secret.txt", env=env)
    assert git(repo, "commit", "-q", "-m", "index green", env=env).returncode == 0


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_deleted_ref_takes_explicit_no_outgoing_commits_branch(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    publish_base(repo, env, tmp_path)
    git(repo, "checkout", "-q", "-b", "doomed", env=env)
    commit(repo, env, "branch.txt", "clean\n", "branch")
    assert git(repo, "push", "-q", "origin", "doomed", env=env).returncode == 0
    deleted = git(repo, "push", "origin", "--delete", "doomed", env=env)
    assert deleted.returncode == 0, deleted.stderr
    assert "deletion" in (deleted.stdout + deleted.stderr).lower()
    assert not remote_sha(repo, env, "refs/heads/doomed")


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_unfetched_remote_sha_refuses_rather_than_scanning_nothing(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    publish_base(repo, env, tmp_path)
    peer = tmp_path / f"peer-{variant}"
    cloned = git(tmp_path, "clone", "-q", str(tmp_path / f"{repo.name}.git"), str(peer), env=env)
    assert cloned.returncode == 0, cloned.stderr
    git(peer, "config", "user.name", "XP Test", env=env)
    git(peer, "config", "user.email", "xp@example.test", env=env)
    commit(peer, env, "peer.txt", "moved\n", "peer moves the remote")
    assert git(peer, "push", "-q", "origin", "main", env=env).returncode == 0
    moved = remote_sha(repo, env)

    commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
    refused = git(repo, "push", "--force", "origin", "main", env=env)
    assert refused.returncode != 0 and remote_sha(repo, env) == moved
    text = (refused.stdout + refused.stderr).lower()
    assert "does not have" in text and "git fetch" in text
    assert git(repo, "fetch", "-q", "origin", env=env).returncode == 0
    scanned = git(repo, "push", "--force", "origin", "main", env=env)
    assert scanned.returncode != 0 and remote_sha(repo, env) == moved
    assert "rewrite the outgoing history" in (scanned.stdout + scanned.stderr).lower()


def test_push_scanner_names_the_state_where_no_ref_lines_arrive(tmp_path):
    scanner = tmp_path / "gitleaks"
    scanner.write_text("#!/bin/sh\nexit 1\n")
    scanner.chmod(scanner.stat().st_mode | stat.S_IEXEC)
    env = os.environ | {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "HOOK_LIB": str(Path(__file__).parent.parent / "plugins/xp-plugin/templates/hook-lib.sh"),
    }
    result = run(tmp_path, "sh", "-c", '. "$HOOK_LIB"; secrets_scan_push', env=env, input="")
    assert result.returncode == 0, "an empty ref stream cannot be made to red by any scanner"
    assert "no ref updates" in result.stderr
