import base64
import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SETUP = ROOT / "plugins" / "xp-plugin" / "scripts" / "setup.py"


def run(repo, *args, env=None, input=None):
    return subprocess.run(args, cwd=repo, env=env, input=input, capture_output=True, text=True)


def git(repo, *args, env=None, input=None):
    return run(repo, "git", *args, env=env, input=input)


def generated_secret(kind="stripe"):
    token = secrets.token_hex(24)
    if kind == "stripe":
        return f"STRIPE_API_KEY=sk_live_{token}\n"
    if kind == "slack":
        return f"SLACK_TOKEN=xoxb-{secrets.randbelow(10**12):012d}-{token}\n"
    if kind == "aws":
        b32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"  # 16 distinct pin entropy 4.0; hex missed ~5%
        access = "AKIA" + "".join(secrets.SystemRandom().sample(b32, 16))
        private = base64.b64encode(secrets.token_bytes(30)).decode()
        return f"AWS_ACCESS_KEY_ID={access}\nAWS_SECRET_ACCESS_KEY={private}\n"
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.fail("PEM calibration requires openssl")
    key = subprocess.run(
        [openssl, "genpkey", "-algorithm", "ED25519"], capture_output=True, text=True
    )
    assert key.returncode == 0, "openssl could not generate the PEM calibration key"
    return key.stdout


def find_real_tools():
    found = {name: shutil.which(name) for name in ("gitleaks", "lefthook")}
    missing = [name for name, path in found.items() if not path]
    if missing:
        pytest.fail(f"acceptance requires real tools: {', '.join(missing)}")
    versions = {
        name: subprocess.run([path, "version"], capture_output=True, text=True).stdout.strip()
        for name, path in found.items()
    }
    assert versions["gitleaks"] == "8.30.1", versions["gitleaks"]
    assert versions["lefthook"] == "2.1.10", versions["lefthook"]
    return found


@pytest.fixture(scope="session")
def real_tools():
    return find_real_tools()


def test_absent_acceptance_tools_fail_instead_of_skip(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BaseException) as refusal:
        find_real_tools()
    assert isinstance(refusal.value, pytest.fail.Exception)


def test_gitleaks_version_pin_rejects_superstring(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: name)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout={"gitleaks": "8.30.10\n", "lefthook": "2.1.10\n"}[args[0]]
        ),
    )
    with pytest.raises(AssertionError):
        find_real_tools()


def test_push_scanner_keeps_ref_stream_from_child_process(tmp_path):
    calls = tmp_path / "calls"
    scanner = tmp_path / "gitleaks"
    scanner.write_text('#!/bin/sh\necho call >> "$CALLS"\ncat >/dev/null\n')
    scanner.chmod(scanner.stat().st_mode | stat.S_IEXEC)
    env = os.environ | {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "CALLS": str(calls),
        "HOOK_LIB": str(ROOT / "plugins/xp-plugin/templates/hook-lib.sh"),
    }
    # real shas: the scanner is only reached once the range resolves
    repo = tmp_path / "stream"
    init_repo(repo, env)
    older = commit(repo, env, "a.txt", "a\n", "a")[1]
    newer = commit(repo, env, "b.txt", "b\n", "b")[1]
    first = f"refs/heads/one {newer} refs/heads/one {older}"
    second = f"refs/heads/two {newer} refs/heads/two {older}"
    result = run(
        repo,
        "sh",
        "-c",
        '. "$HOOK_LIB"; secrets_scan_push',
        env=env,
        input=f"{first}\n{second}\n",
    )
    assert result.returncode == 0 and calls.read_text().splitlines() == ["call", "call"]


def init_repo(path, env):
    path.mkdir()
    assert git(path, "init", "-q", "-b", "main", env=env).returncode == 0
    git(path, "config", "user.name", "XP Test", env=env)
    git(path, "config", "user.email", "xp@example.test", env=env)


def isolated_env(tmp_path, real_tools, variant):
    bin_dir = tmp_path / f"bin-{variant}"
    bin_dir.mkdir()
    names = ["gitleaks"] + (["lefthook"] if variant == "lefthook" else [])
    for name in names:
        (bin_dir / name).symlink_to(real_tools[name])
    return os.environ | {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / f"home-{variant}"),
        "XP_DATA": str(tmp_path / f"state-{variant}"),
    }


def scaffold(repo, env, variant):
    result = run(repo, sys.executable, str(SETUP), env=env)
    assert result.returncode == 0, result.stderr
    config = repo / ".xp" / "config.yml"
    text = config.read_text()
    for tier in ("fast", "story", "full"):
        text = text.replace(f"{tier}: EDIT-ME", f"{tier}: true")
    config.write_text(text)
    hooks = git(repo, "rev-parse", "--git-path", "hooks", env=env).stdout.strip()
    hooks_path = git(repo, "config", "core.hooksPath", env=env).stdout.strip()
    if variant == "githooks":
        assert hooks_path == ".githooks"
        assert not (repo / "lefthook.yml").exists()
        assert os.access(repo / ".githooks" / "pre-merge-commit", os.X_OK)
    else:
        assert not hooks_path
        assert (repo / "lefthook.yml").exists()
        assert os.access(repo / hooks / "pre-merge-commit", os.X_OK)
        assert 'run "pre-push" "$@"' in (repo / hooks / "pre-push").read_text()


def wall_repo(tmp_path, real_tools, variant, install=True):
    repo = tmp_path / f"repo-{variant}"
    env = isolated_env(tmp_path, real_tools, variant)
    init_repo(repo, env)
    if install:
        scaffold(repo, env, variant)
    return repo, env


def commit(repo, env, name, content, message="change", bypass=False):
    (repo / name).write_text(content)
    assert git(repo, "add", name, env=env).returncode == 0
    args = ["commit", "-q", "-m", message]
    if bypass:
        args = ["-c", "core.hooksPath=/dev/null", *args]
    result = git(repo, *args, env=env)
    return result, git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


def add_remote(repo, env, tmp_path):
    remote = tmp_path / f"{repo.name}.git"
    assert git(tmp_path, "init", "-q", "--bare", str(remote), env=env).returncode == 0
    assert git(repo, "remote", "add", "origin", str(remote), env=env).returncode == 0
    return remote


def remote_sha(repo, env, ref="refs/heads/main"):
    return git(repo, "ls-remote", "origin", ref, env=env).stdout.split("\t", 1)[0]


def publish_base(repo, env, tmp_path):
    commit(repo, env, "base.txt", "clean\n", "base")
    add_remote(repo, env, tmp_path)
    pushed = git(repo, "push", "-q", "-u", "origin", "main", env=env)
    assert pushed.returncode == 0, pushed.stderr
    return remote_sha(repo, env)


@pytest.mark.parametrize("kind", ["stripe", "slack", "aws", "pem"])
def test_generated_secret_reds_at_gitleaks_8_30_1(tmp_path, real_tools, kind):
    repo = tmp_path / kind
    env = isolated_env(tmp_path, real_tools, "githooks")
    init_repo(repo, env)
    (repo / "secret.txt").write_text(generated_secret(kind))
    git(repo, "add", "secret.txt", env=env)
    result = run(
        repo,
        real_tools["gitleaks"],
        "protect",
        "--staged",
        "--no-banner",
        "--redact",
        env=env,
    )
    assert result.returncode == 1, f"{kind} fixture did not trigger gitleaks 8.30.1"


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_index_paths_red_then_pass_after_restaging(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    clean = commit(repo, env, "base.txt", "clean\n", "base")
    assert clean[0].returncode == 0
    before = clean[1]
    (repo / "secret.txt").write_text(generated_secret())
    git(repo, "add", "secret.txt", env=env)
    red = git(repo, "commit", "-m", "secret", env=env)
    assert red.returncode != 0 and git(repo, "rev-parse", "HEAD", env=env).stdout.strip() == before
    (repo / "secret.txt").write_text("rotated\n")
    git(repo, "add", "secret.txt", env=env)
    green = git(repo, "commit", "-q", "-m", "clean", env=env)
    assert green.returncode == 0, green.stderr


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_no_ff_merge_secret_stops_before_history_and_unhooked_control_merges(
    tmp_path, real_tools, variant
):
    repo, env = wall_repo(tmp_path, real_tools, variant, install=False)
    commit(repo, env, "base.txt", "base\n", "base")
    git(repo, "checkout", "-q", "-b", "feature", env=env)
    _, leaking = commit(repo, env, "secret.txt", generated_secret(), "secret")
    git(repo, "checkout", "-q", "main", env=env)
    _, target = commit(repo, env, "target.txt", "target\n", "target")
    scaffold(repo, env, variant)

    stopped = git(repo, "merge", "--no-ff", "feature", "-m", "merge", env=env)
    assert stopped.returncode != 0
    assert git(repo, "rev-parse", "HEAD", env=env).stdout.strip() == target
    assert leaking not in git(repo, "rev-list", "main", env=env).stdout.splitlines()
    assert leaking in git(repo, "rev-list", "feature", env=env).stdout.splitlines()
    git(repo, "merge", "--abort", env=env)

    git(repo, "checkout", "-q", "feature", env=env)
    (repo / "secret.txt").write_text("rotated\n")
    git(repo, "add", "secret.txt", env=env)
    assert git(repo, "commit", "-q", "--amend", "--no-edit", env=env).returncode == 0
    git(repo, "checkout", "-q", "main", env=env)
    assert git(repo, "merge", "--no-ff", "feature", "-m", "clean", env=env).returncode == 0

    git(repo, "reset", "--hard", target, env=env)
    git(repo, "branch", "-f", "feature", leaking, env=env)
    hook = (
        repo / ".githooks" / "pre-merge-commit"
        if variant == "githooks"
        else repo
        / git(repo, "rev-parse", "--git-path", "hooks", env=env).stdout.strip()
        / "pre-merge-commit"
    )
    hook.unlink()
    control = git(repo, "merge", "--no-ff", "feature", "-m", "unhooked", env=env)
    assert control.returncode == 0, control.stderr
    assert leaking in git(repo, "rev-list", "main", env=env).stdout.splitlines()


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_existing_ref_scans_remote_to_local(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    base = publish_base(repo, env, tmp_path)
    commit(repo, env, "secret.txt", generated_secret(), bypass=True)
    red = git(repo, "push", "origin", "main", env=env)
    assert red.returncode != 0 and remote_sha(repo, env) == base
    git(repo, "reset", "--soft", base, env=env)
    (repo / "secret.txt").write_text("rotated\n")
    git(repo, "add", "secret.txt", env=env)
    assert git(repo, "commit", "-q", "-m", "clean", env=env).returncode == 0
    green = git(repo, "push", "-q", "origin", "main", env=env)
    assert green.returncode == 0, green.stderr


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


def test_lefthook_names_post_sync_empty_diff_push_skip(tmp_path, real_tools):
    repo, env = wall_repo(tmp_path, real_tools, "lefthook")
    base = publish_base(repo, env, tmp_path)
    commit(repo, env, "secret.txt", generated_secret(), "secret", bypass=True)
    (repo / "secret.txt").unlink()
    git(repo, "add", "-u", env=env)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "remove", env=env)
    config = repo / "lefthook.yml"
    config.write_text(
        config.read_text().replace(
            "  commands:\n    secrets:",
            '  commands:\n    user-linter:\n      run: "true"\n    secrets:',
            1,
        )
    )

    pushed = git(repo, "push", "origin", "main", env=env)

    output = (pushed.stdout + pushed.stderr).lower()
    assert pushed.returncode == 0 and remote_sha(repo, env) != base
    assert "sync hooks" in output
    assert "secrets (skip)" in output and "no matching push files" in output


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
    # the refusal's next action has to reach a scan that can red, not just quiet it
    assert git(repo, "fetch", "-q", "origin", env=env).returncode == 0
    scanned = git(repo, "push", "--force", "origin", "main", env=env)
    assert scanned.returncode != 0 and remote_sha(repo, env) == moved
    assert "rewrite the outgoing history" in (scanned.stdout + scanned.stderr).lower()


def test_push_scanner_names_the_state_where_no_ref_lines_arrive(tmp_path):
    scanner = tmp_path / "gitleaks"
    scanner.write_text("#!/bin/sh\nexit 1\n")  # reds everything it is ever handed
    scanner.chmod(scanner.stat().st_mode | stat.S_IEXEC)
    env = os.environ | {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "HOOK_LIB": str(ROOT / "plugins/xp-plugin/templates/hook-lib.sh"),
    }
    result = run(tmp_path, "sh", "-c", '. "$HOOK_LIB"; secrets_scan_push', env=env, input="")
    assert result.returncode == 0, "an empty ref stream cannot be made to red by any scanner"
    assert "no ref updates" in result.stderr


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_missing_scanner_refuses_owned_paths(tmp_path, real_tools, variant):
    repo, env = wall_repo(tmp_path, real_tools, variant)
    publish_base(repo, env, tmp_path)
    Path(env["PATH"].split(":", 1)[0], "gitleaks").unlink()
    (repo / "next.txt").write_text("clean\n")
    git(repo, "add", "next.txt", env=env)
    result = git(repo, "commit", "-m", "must refuse", env=env)
    assert result.returncode != 0 and "gitleaks not installed" in result.stderr.lower()
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "outgoing", env=env)
    pushed = git(repo, "push", "origin", "main", env=env)
    assert pushed.returncode != 0 and "gitleaks not installed" in pushed.stderr.lower()
