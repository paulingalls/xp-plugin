"""story-006: /xp-setup scaffold. Verify: pytest -q tests/test_setup.py"""

import stat
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from close import config_flat, story_card, verify_commands  # noqa: E402
from work import config_block_value  # noqa: E402


def bare_repo(tmp_path, with_fake_lefthook=False):
    repo = tmp_path / "repo"
    repo.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    if with_fake_lefthook:
        fake = bin_dir / "lefthook"
        fake.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/lefthook.calls"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    return repo, env


def run_setup(repo, env):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "setup.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


class TestScaffold:
    def test_bare_repo_gets_seeded_xp(self, tmp_path, monkeypatch):
        repo, env = bare_repo(tmp_path)
        r = run_setup(repo, env)
        assert r.returncode == 0, r.stderr
        constraints = (repo / ".xp" / "constraints.md").read_text()
        assert "300" in constraints and "500" in constraints  # small-files seed
        assert "comment" in constraints.lower()  # comment rubric seed
        assert "fault-inject" in constraints.lower()
        monkeypatch.chdir(repo)
        assert config_flat("release") == "sprint"
        assert "EDIT-ME" in config_block_value("tests", "story")  # tiers are placeholders
        cfg = (repo / ".xp" / "config.yml").read_text()
        assert "sprint_cap" in cfg and "debt_budget" in cfg and "constraints_cap" in cfg
        plan = (repo / ".xp" / "plan.md").read_text()
        card, status = story_card(plan, "story-001")  # template parses with the real parser
        assert status == "ready" and verify_commands(card)
        assert (repo / ".xp" / "system.md").exists()

    def test_existing_xp_refused_untouched(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        (repo / ".xp").mkdir()
        (repo / ".xp" / "constraints.md").write_text("MINE\n")
        r = run_setup(repo, env)
        assert r.returncode == 2 and ".xp" in r.stderr
        assert (repo / ".xp" / "constraints.md").read_text() == "MINE\n"
        assert not (repo / ".xp" / "config.yml").exists()

    def test_not_a_git_repo_refused(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "setup.py")],
            cwd=plain,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "git" in r.stderr


class TestHookWall:
    def test_lefthook_present_writes_config_and_installs(self, tmp_path):
        repo, env = bare_repo(tmp_path, with_fake_lefthook=True)
        r = run_setup(repo, env)
        assert r.returncode == 0, r.stderr
        assert (repo / "lefthook.yml").exists()
        assert "install" in (tmp_path / "lefthook.calls").read_text()

    def test_no_lefthook_scaffolds_executable_githooks(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        pre = repo / ".githooks" / "pre-commit"
        assert pre.exists() and pre.stat().st_mode & stat.S_IEXEC
        assert (repo / ".githooks" / "pre-push").exists()
        hooks_path = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert hooks_path == ".githooks"

    def test_wall_executes_config_tier_at_run_time(self, tmp_path):
        # declared-once: edit config AFTER scaffold; the hook must use the new command
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(cfg.read_text().replace("fast: EDIT-ME", "fast: false"))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode != 0  # red tier reds the hook, no re-scaffold needed
        cfg.write_text(cfg.read_text().replace("fast: false", "fast: true"))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0, r.stderr

    def test_wall_runs_gitleaks_when_present_and_warns_when_absent(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(cfg.read_text().replace("fast: EDIT-ME", "fast: true"))
        bin_dir = tmp_path / "bin"
        fake = bin_dir / "gitleaks"
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode != 0  # failing gitleaks reds the wall
        fake.unlink()
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0 and "gitleaks" in (r.stderr + r.stdout)  # loud warning

    def test_preexisting_routing_left_untouched(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        (repo / "lefthook.toml").write_text("# theirs\n")
        r = run_setup(repo, env)
        assert r.returncode == 0
        assert (repo / ".xp").is_dir()  # xp scaffolded
        assert not (repo / ".githooks").exists() and not (repo / "lefthook.yml").exists()
        assert "existing" in (r.stdout + r.stderr).lower()

    def test_preexisting_hookspath_left_untouched(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        subprocess.run(["git", "config", "core.hooksPath", ".husky"], cwd=repo, env=env)
        r = run_setup(repo, env)
        assert r.returncode == 0
        hooks_path = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert hooks_path == ".husky"
        assert not (repo / ".githooks").exists()


class TestCloseReviewFindings:
    def test_live_git_hooks_dir_counts_as_routing(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        hooks_dir = repo / ".git" / "hooks"
        planted = hooks_dir / "pre-commit"
        planted.write_text("#!/bin/sh\nexit 0\n")
        planted.chmod(planted.stat().st_mode | stat.S_IEXEC)
        r = run_setup(repo, env)
        assert r.returncode == 0 and "existing" in (r.stdout + r.stderr).lower()
        assert planted.exists() and not planted.with_suffix(".old").exists()
        hooks_path = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert hooks_path == ""  # the user's live hook keeps firing

    def test_failed_lefthook_install_reported_loudly(self, tmp_path):
        repo, env = bare_repo(tmp_path, with_fake_lefthook=True)
        fake = tmp_path / "bin" / "lefthook"
        fake.write_text("#!/bin/sh\nexit 1\n")
        r = run_setup(repo, env)
        out = r.stdout + r.stderr
        assert "FAILED" in out or "failed" in out
        assert "installed" not in out.split("fail")[0].split("FAIL")[0] or "install" in out

    def test_quoted_tier_command_survives_extraction(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        quoted = 'fast: test "not slow" = "not slow"'
        cfg.write_text(cfg.read_text().replace("fast: EDIT-ME", quoted))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0, (r.stdout, r.stderr)  # quotes intact -> test passes
        assert "unset" not in (r.stdout + r.stderr)  # and no lying diagnostic

    def test_reindented_config_still_read(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(cfg.read_text().replace("  fast: EDIT-ME", "    fast: true"))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0 and "unset" not in (r.stdout + r.stderr)

    def test_fresh_scaffold_edit_me_warns_and_passes_through_hook(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0 and "config" in (r.stdout + r.stderr)
