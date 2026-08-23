"""story-006: /xp-setup scaffold. Verify: pytest -q tests/test_setup.py"""

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from close import config_flat, story_card, verify_commands  # noqa: E402
from work import config_block_value  # noqa: E402

SHIPPED_TEMPLATES = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "templates"


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


def plant(tmp_path, name, body):
    exe = tmp_path / "bin" / name
    exe.write_text(body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def run_setup(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "setup.py"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


class TestScaffold:
    def test_help_explains_rather_than_scaffolding(self, tmp_path):
        """setup.py parsed no args, so an agent orienting with --help SCAFFOLDED
        the repo instead of being told what the command does. Corrupting, not
        loud: it creates state nobody asked for and then reports success. The
        fixture is a BARE repo — in this one, .xp/ already exists and the refusal
        masks the bug entirely."""
        repo, env = bare_repo(tmp_path)
        r = run_setup(repo, env, "--help")
        assert r.returncode == 0, r.stderr
        assert not (repo / ".xp").exists(), "--help scaffolded the repo"
        assert "scaffold" in r.stdout.lower(), r.stdout

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
        # AC3: the plan scaffolds into the CLONE's state root, and .xp/ keeps only
        # what three parallel streams must share. XP_DATA is unset here and
        # HOME is tmp_path, so data_root() really hashes and nothing touches the
        # developer's own ~/.xp.
        assert {f.name for f in (repo / ".xp").iterdir()} == {
            "config.yml",
            "constraints.md",
            "system.md",
        }
        roots = list((tmp_path / ".xp" / "data").glob("*/plan.md"))
        assert len(roots) == 1, f"expected one state-root plan, found {roots}"
        plan = roots[0].read_text()
        assert plan == (SHIPPED_TEMPLATES / "plan.md").read_text(), "not the seeded template"
        card, status = story_card(plan, "story-000")  # template parses with the real parser
        # SEEDED [planned], not [ready]: a scaffolded project's first card must not
        # be spawnable before its plan review. Both sprint-003 misses were forgetting,
        # and a state nothing defaults to cannot catch forgetting.
        assert status == "planned" and verify_commands(card)

    def test_an_existing_state_root_plan_refuses_and_leaves_no_half_made_xp(self, tmp_path):
        """F10: the check must sit with the OTHER preflight, before .xp/.mkdir().
        Below it, a refusal would leave the directory behind — setup's own
        'never overwrites' promise inverted."""
        repo, env = bare_repo(tmp_path)
        first = run_setup(repo, env)
        assert first.returncode == 0, first.stderr
        shutil.rmtree(repo / ".xp")
        second = run_setup(repo, env)
        assert second.returncode != 0 and "never overwrites" in second.stderr
        assert not (repo / ".xp").exists(), "a refusal left a half-made .xp/ behind"

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
        plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 0\n")
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

    def test_wall_runs_gitleaks_when_present_and_refuses_when_absent(self, tmp_path):
        """A missing scanner must RED the wall, not warn past it. DESIGN §7 puts
        the secrets scan in the enforcement floor, and a floor with a skip in it
        is not one: the commit it passes looks scanned and was not."""
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(cfg.read_text().replace("fast: EDIT-ME", "fast: true"))
        fake = plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 1\n")
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode != 0  # failing gitleaks reds the wall
        fake.unlink()
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode != 0, "a missing scanner passed the wall"
        assert "gitleaks" in r.stderr  # and the refusal carries the install line

    def test_setup_never_points_at_a_hook_it_declined_to_write(self, tmp_path):
        """Step 3 said "add your linter to the pre-commit hook" unconditionally,
        so on a repo whose routing setup deliberately left alone it named a file
        that does not exist. The real task there is the one the field report had
        to work out by hand: point the tiers at the existing wall's own commands,
        so two walls cannot drift into different definitions of "fast"."""
        repo, env = bare_repo(tmp_path)
        (repo / "lefthook.toml").write_text("# theirs\n")
        r = run_setup(repo, env)
        assert r.returncode == 0, r.stderr
        assert "add your linter" not in r.stdout, r.stdout
        assert "tiers at that wall" in r.stdout, r.stdout  # names the real task instead

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
        plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 0\n")
        quoted = 'fast: test "not slow" = "not slow"'
        cfg.write_text(cfg.read_text().replace("fast: EDIT-ME", quoted))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0, (r.stdout, r.stderr)  # quotes intact -> test passes
        assert "unset" not in (r.stdout + r.stderr)  # and no lying diagnostic

    def test_a_hash_inside_a_word_is_not_a_yaml_comment(self, tmp_path):
        """YAML opens a comment only at a WHITESPACE-preceded `#`, so `p#ss` is one
        scalar to every other reader of config.yml and was a truncation point only
        to us. The field case: a tier carrying an inline env var whose password
        holds a `#` truncated to a bare `VAR=value` — a syntactically valid shell
        command that assigns, exits 0, and runs no test. The same false green as
        the two legs above, reached from the parser instead of the guard.

        Trailing-comment stripping stays covered by the tier tests around this one:
        the shipped template comments every tier line, and they only ever replace
        the value, so each of them runs a command with a real `  # ...` after it.
        """
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 0\n")
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(
            cfg.read_text().replace(
                "fast: EDIT-ME", "fast: DB=postgres://u:p#ss@h/db touch ran-a && touch ran-b"
            )
        )
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert (repo / "ran-a").exists(), "the tier truncated to a bare assignment and ran nothing"
        assert (repo / "ran-b").exists(), "the tier ran only part of the command"

    def test_reindented_config_still_read(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        cfg = repo / ".xp" / "config.yml"
        plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 0\n")
        cfg.write_text(cfg.read_text().replace("  fast: EDIT-ME", "    fast: true"))
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode == 0 and "unset" not in (r.stdout + r.stderr)

    def test_fresh_scaffold_edit_me_reds_rather_than_greening(self, tmp_path):
        """The worst arm of the same shape, because it fires on a JUST-scaffolded
        repo: setup writes EDIT-ME as the tier default, so the first commit after
        setup passed a wall that had run no test — invisible during exactly the
        window where the user assumes setup worked."""
        repo, env = bare_repo(tmp_path)
        run_setup(repo, env)
        plant(tmp_path, "gitleaks", "#!/bin/sh\nexit 0\n")
        r = subprocess.run(
            ["sh", ".githooks/pre-commit"], cwd=repo, env=env, capture_output=True, text=True
        )
        assert r.returncode != 0, "an unedited tier passed the wall having run nothing"
        assert "tests.fast" in r.stderr and ".xp/config.yml" in r.stderr


class TestDogfoodMatchesTheScaffold:
    """We hand-built .xp/ at Sprint 0 and never run xp-setup on ourselves, so
    what we dogfood can drift from what we ship and nothing would say so. The
    stale-marketplace-build bug is the same class: we tested a thing we were not
    running. These pin the SHAPE the code parses, never the content — a project's
    tiers, constraints and stories are legitimately its own.
    """

    REPO = Path(__file__).parent.parent
    OURS = REPO / ".xp"
    SHIPPED = REPO / "plugins" / "xp-plugin" / "templates"

    def keys(self, path):
        return {ln.split(":")[0] for ln in path.read_text().splitlines() if re.match(r"^\w+:", ln)}

    def test_our_config_carries_every_key_the_scaffold_ships(self):
        missing = self.keys(self.SHIPPED / "config.yml") - self.keys(self.OURS / "config.yml")
        assert not missing, f"we never exercise the shipped keys: {missing}"

    def test_the_scaffold_ships_no_key_we_invented_without_seeding(self):
        """The reverse drift: a key we rely on that a scaffolded repo never gets.
        sprint_branch is seeded COMMENTED, so it counts as shipped."""
        shipped = self.SHIPPED / "config.yml"
        text = shipped.read_text()
        extra = {k for k in self.keys(self.OURS / "config.yml") - self.keys(shipped)}
        for key in sorted(extra):
            assert f"# {key}:" in text, f"we use {key!r} and the scaffold never mentions it"

    def test_the_shipped_plan_parses_with_the_parser_sprint_close_uses(self):
        """Was a PAIR: it also read THIS repo's .xp/plan.md, so our live plan and
        the template could not drift apart unnoticed. story-019 moved our plan to
        the state root, which is machine-dependent and ambient — reading it here
        would be the observed state constraint 11 forbids — so the drift alarm is
        gone, not moved. AC7's migration walk re-asserts the parse where the live
        plan is present by construction."""
        sys.path.insert(0, str(self.REPO / "plugins" / "xp-plugin" / "scripts"))
        from sprint_close import sprint_stories

        assert sprint_stories((self.SHIPPED / "plan.md").read_text(), "1"), (
            "a scaffolded repo cannot run a sprint close: the seeded plan has no"
            " `### Sprint N` section for sprint_stories to find"
        )


class TestEnvFile:
    """story-027 AC1: the data root records the plugin root that scaffolded it, so
    a codex lead's scripts — spawned by nothing, holding no ${CLAUDE_PLUGIN_ROOT} —
    can find the install. In THIS repo the plugin is in-tree and the gap is invisible."""

    def test_setup_seeds_the_env_file_with_its_own_root_and_version(self, tmp_path):
        """XP_DATA unset, as in the AC3 arm above: data_root() really hashes and the
        developer's own ~/.xp is never written."""
        repo, env = bare_repo(tmp_path)
        r = run_setup(repo, env)
        assert r.returncode == 0, r.stderr
        found = list((tmp_path / ".xp" / "data").glob("*/env.json"))
        assert len(found) == 1, f"expected one state-root env file, found {found}"
        recorded = json.loads(found[0].read_text())
        manifest = json.loads((SCRIPTS.parent / ".claude-plugin" / "plugin.json").read_text())
        assert recorded["plugin_root"] == str(SCRIPTS.parent)
        assert recorded["plugin_version"] == manifest["version"]
        assert str(found[0]) in r.stdout, "the summary never says where it landed"

    def test_setup_preserves_existing_non_plugin_keys(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        data = tmp_path / "state"
        data.mkdir()
        env["XP_DATA"] = str(data)
        (data / "env.json").write_text(json.dumps({"consumer": {"keep": True}}))

        r = run_setup(repo, env)

        assert r.returncode == 0, r.stderr
        recorded = json.loads((data / "env.json").read_text())
        manifest = json.loads((SCRIPTS.parent / ".claude-plugin" / "plugin.json").read_text())
        assert recorded == {
            "consumer": {"keep": True},
            "plugin_root": str(SCRIPTS.parent),
            "plugin_version": manifest["version"],
        }

    def test_an_invalid_env_refuses_before_scaffolding(self, tmp_path):
        repo, env = bare_repo(tmp_path)
        data = tmp_path / "state"
        data.mkdir()
        env["XP_DATA"] = str(data)
        invalid = '{"consumer": '
        (data / "env.json").write_text(invalid)

        r = run_setup(repo, env)

        assert r.returncode != 0 and "env.json" in r.stderr, r.stderr
        assert not (repo / ".xp").exists(), "a failed env seed left a partial scaffold"
        assert not (data / "plan.md").exists(), "a failed env seed left a partial plan"
        assert (data / "env.json").read_text() == invalid

    def test_an_install_without_a_version_refuses_before_scaffolding(self, tmp_path):
        install = shutil.copytree(SCRIPTS.parent, tmp_path / "install")
        (install / ".claude-plugin" / "plugin.json").unlink()
        repo, env = bare_repo(tmp_path)
        data = tmp_path / "state"
        env["XP_DATA"] = str(data)

        r = subprocess.run(
            [sys.executable, str(install / "scripts" / "setup.py")],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

        assert r.returncode != 0 and "plugin.json" in r.stderr, r.stderr
        assert not (repo / ".xp").exists(), "an invalid install scaffolded the repo"
        assert not (data / "plan.md").exists(), "an invalid install seeded the plan"
        assert not (data / "env.json").exists(), "an invalid version was recorded"

    def test_the_concurrent_writer_that_replaces_last_wins(self, tmp_path):
        data = tmp_path / "state"
        data.mkdir()
        (data / "env.json").write_text(json.dumps({"consumer": "keep"}))
        writer = """
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from env import write_env
replace = Path.replace
def rendezvous(self, target):
    (Path(os.environ["XP_DATA"]) / f"ready.{os.getpid()}").touch()
    deadline = time.monotonic() + 10
    while len(list(Path(os.environ["XP_DATA"]).glob("ready.*"))) < 2:
        if time.monotonic() > deadline:
            raise TimeoutError("the other writer never reached replace")
        time.sleep(0.01)
    swapped = Path(os.environ["XP_DATA"]) / "first-swapped"
    if sys.argv[3] == "1.0.0":
        while not swapped.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("the first writer never replaced")
            time.sleep(0.01)
        return replace(self, target)
    result = replace(self, target)
    swapped.touch()
    return result
Path.replace = rendezvous
write_env(Path(sys.argv[2]), sys.argv[3])
"""
        env = {"PATH": "/usr/bin:/bin", "XP_DATA": str(data)}
        writers = [
            subprocess.Popen(
                [sys.executable, "-c", writer, str(SCRIPTS), str(tmp_path / root), version],
                env=env,
            )
            for root, version in (("install-a", "1.0.0"), ("install-b", "2.0.0"))
        ]

        assert [process.wait(15) for process in writers] == [0, 0]
        recorded = json.loads((data / "env.json").read_text())
        assert recorded["consumer"] == "keep"
        assert recorded["plugin_root"] == str(tmp_path / "install-a")
        assert recorded["plugin_version"] == "1.0.0"
