"""The land wall between a story's commit range and its Files declaration."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from close_free_card_cases import (
    add_free_card,
    checkout_free,
    commit_on_free,
    spawn_free,
)
from close_helpers import CONFIG, SPAWN, close, free, free_repo, gh_calls, make_repo


def commit(g, repo, path, text, message):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    g("add", "-A")
    assert g("commit", "-qm", message).returncode == 0


def add_base_files(repo, g, files):
    g("checkout", "-q", "main")
    for path in files:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"base {path}\n")
    g("add", "-A")
    g("commit", "-qm", "add story base files")
    g("checkout", "-q", "story-042-branch")
    assert g("rebase", "main").returncode == 0


def amend(repo, env, story_id, reason="declare the complete landed change"):
    return subprocess.run(
        [sys.executable, str(SPAWN), "amend", story_id, "--reason", reason],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def record_git(tmp_path, env):
    real_git = shutil.which("git", path=env["PATH"])
    calls = tmp_path / "scope-git.jsonl"
    bin_dir = tmp_path / "scope-git"
    bin_dir.mkdir()
    shim = bin_dir / "git"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys\n"
        f"with open({str(calls)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.exit(subprocess.run([{real_git!r}, *sys.argv[1:]]).returncode)\n"
    )
    shim.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return calls


def git_calls(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestDeclaredLandScope:
    def modified_helper_story(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        add_base_files(repo, g, ["helper.py"])
        commit(g, repo, "helper.py", "changed\n", "change declared and undeclared paths")
        assert close(repo, env, "review").returncode == 0
        return repo, env, g

    def test_land_refuses_the_falsifiers_undeclared_modified_path(self, tmp_path):
        repo, env, g = self.modified_helper_story(tmp_path)
        g("checkout", "-q", "main")
        commit(g, repo, "trunk.py", "trunk moved\n", "move trunk outside story scope")
        g("checkout", "-q", "story-042-branch")
        before = g("rev-parse", "main").stdout.strip()
        calls = record_git(tmp_path, env)

        preview = close(repo, env, "land", "--dry-run")
        real = close(repo, env, "land")

        assert not any(call and call[0] in {"merge", "push"} for call in git_calls(calls))
        assert gh_calls(tmp_path) == []
        assert preview.returncode == real.returncode == 2
        assert preview.stderr == real.stderr
        assert "helper.py" in real.stderr
        assert "Add them to Files, then run `spawn.py amend story-042 --reason" in real.stderr
        assert g("rev-parse", "main").stdout.strip() == before

    def test_every_added_modified_and_deleted_undeclared_path_is_named(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        add_base_files(repo, g, ["modified.py", "deleted.py"])
        (repo / "modified.py").write_text("changed\n")
        (repo / "deleted.py").unlink()
        (repo / "added.py").write_text("added\n")
        g("add", "-A")
        g("commit", "-qm", "all undeclared statuses")
        assert close(repo, env, "review").returncode == 0

        refused = close(repo, env, "land", "--dry-run")

        assert refused.returncode == 2
        paths = ("added.py", "deleted.py", "modified.py")
        assert all(refused.stderr.count(path) == 1 for path in paths)
        names = [refused.stderr.index(path) for path in paths]
        assert names == sorted(names)

    def test_no_renames_keeps_a_renamed_away_undeclared_path_visible(self, tmp_path):
        repo, env, g = make_repo(tmp_path, files="src/thing.py, src/renamed.py")
        add_base_files(repo, g, ["old.py"])
        g("mv", "old.py", "src/renamed.py")
        g("commit", "-qm", "rename undeclared source to declared destination")
        assert close(repo, env, "review").returncode == 0

        refused = close(repo, env, "land", "--dry-run")

        assert refused.returncode == 2 and "old.py" in refused.stderr
        assert "  src/renamed.py" not in refused.stderr

    def test_the_named_files_and_amend_route_then_land(self, tmp_path):
        repo, env, g = self.modified_helper_story(tmp_path)
        assert close(repo, env, "land", "--dry-run").returncode == 2
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/thing.py", "Files: src/thing.py, helper.py")
        )
        drifted = close(repo, env, "land", "--dry-run")

        amended = amend(repo, env, "story-042")
        before = g("rev-parse", "main").stdout.strip()
        landed = close(repo, env, "land")

        assert drifted.returncode == 2 and "edited after its plan review" in drifted.stderr
        assert amended.returncode == 0, amended.stderr
        assert "card amended" in landed.stdout
        assert landed.returncode == 0, landed.stderr
        assert g("rev-parse", "main").stdout.strip() != before
        assert g("show", "main:helper.py").stdout == "changed\n"

    def test_a_story_changing_only_declared_paths_lands_as_before(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        before = g("rev-parse", "main").stdout.strip()

        landed = close(repo, env, "land")

        assert landed.returncode == 0, landed.stderr
        assert "Files declaration" not in landed.stderr
        assert g("rev-parse", "main").stdout.strip() != before

    def test_a_declared_non_ascii_path_is_compared_unquoted(self, tmp_path):
        repo, env, g = make_repo(tmp_path, files="src/thing.py, café.py")
        commit(g, repo, "café.py", "accented\n", "add declared non-ASCII path")
        assert close(repo, env, "review").returncode == 0

        landed = close(repo, env, "land")

        assert landed.returncode == 0, landed.stderr
        assert g("show", "main:café.py").stdout == "accented\n"

    def test_a_sprint_story_uses_the_integration_branch_as_its_scope_base(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "sprint release config")
        g("checkout", "-qb", "sprint-001")
        commit(g, repo, "sibling.py", "sibling\n", "land sibling story")
        (Path(env["XP_DATA"]) / "sprint_branch").write_text("sprint-001\n")
        g("branch", "-D", "story-042-branch")
        g("checkout", "-qb", "story-042-branch")
        commit(g, repo, "src/thing.py", "A = 2\n", "story work")
        assert close(repo, env, "review").returncode == 0

        landed = close(repo, env, "land")

        assert landed.returncode == 0, landed.stderr
        assert "sibling.py" not in landed.stderr
        assert g("show", "sprint-001:sibling.py").stdout == "sibling\n"
        assert g("show", "sprint-001:src/thing.py").stdout == "A = 2\n"

    def test_an_unparseable_files_entry_is_never_an_empty_declaration(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/thing.py", "Files: src/thing.py, bad path.py")
        )
        assert amend(repo, env, "story-042").returncode == 0
        calls = record_git(tmp_path, env)

        preview = close(repo, env, "land", "--dry-run")
        real = close(repo, env, "land")

        assert preview.returncode == real.returncode == 2
        assert preview.stderr == real.stderr
        assert "the Files entry 'bad path.py' is not a plausible path" in real.stderr
        assert "Traceback" not in real.stderr and "changes paths" not in real.stderr
        assert not any(call and call[0] in {"merge", "push"} for call in git_calls(calls))
        assert gh_calls(tmp_path) == []


class TestFreeDeclaredLandScope:
    def reviewed_free(self, tmp_path, config, changed_path):
        repo, env, g = free_repo(tmp_path)
        cfg = repo / ".xp" / "config.yml"
        cfg.write_text(CONFIG + "  full: true\n" + config)
        g("add", "-A")
        g("commit", "-qm", "configure release")
        g("push", "-q", "origin", "main")
        assert free(repo, env, "scope", "start").returncode == 0
        branch, key = checkout_free(g)
        commit_on_free(repo, g)
        commit_on_free(repo, g, "changed\n", changed_path, "change undeclared release path")
        add_free_card(env, key)
        tree = spawn_free(repo, env, g, tmp_path, key)
        g("worktree", "remove", "--force", str(tree))
        g("checkout", "-q", branch)
        assert free(repo, env, "scope", "review").returncode == 0
        return repo, env, g, key

    def test_only_version_manifests_bypass_the_free_release_scope(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        (repo / "plugin.json").write_text('{"version": "0.2.0"}\n')
        g("commit", "-qam", "align release manifest")
        g("push", "-q", "origin", "main")
        assert free(repo, env, "scope", "start").returncode == 0
        branch, key = checkout_free(g)
        commit_on_free(repo, g)
        commit_on_free(repo, g, '{"version": "0.2.1"}\n', "plugin.json", "bump manifest")
        commit_on_free(repo, g, "release notes\n", "CHANGELOG.md", "write changelog")
        add_free_card(env, key)
        tree = spawn_free(repo, env, g, tmp_path, key)
        g("worktree", "remove", "--force", str(tree))
        g("checkout", "-q", branch)
        assert free(repo, env, "scope", "review").returncode == 0

        refused = free(repo, env, "scope", "land", "--dry-run")

        assert refused.returncode == 2 and "CHANGELOG.md" in refused.stderr
        assert "  plugin.json" not in refused.stderr
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/free.py", "Files: src/free.py, CHANGELOG.md")
        )
        assert amend(repo, env, key).returncode == 0
        landed = free(repo, env, "scope", "land")
        assert landed.returncode == 0, landed.stderr
        assert any(call[:2] == ["pr", "create"] for call in gh_calls(tmp_path))

    @pytest.mark.parametrize(
        ("config", "path"),
        [
            ("versioning: off\nversion_files: ignored.json\n", "ignored.json"),
            ("version_files: none\n", "none"),
        ],
    )
    def test_inactive_or_waived_manifest_names_are_not_exempt(self, tmp_path, config, path):
        repo, env, _g, _key = self.reviewed_free(tmp_path, config, path)

        refused = free(repo, env, "scope", "land", "--dry-run")

        assert refused.returncode == 2 and f"  {path}\n" in refused.stderr
