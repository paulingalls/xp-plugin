"""story-009: sprint-close pipeline. Verify: pytest -q tests/test_sprint_close.py"""

import subprocess
import sys
from pathlib import Path

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"
WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"
PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"

PLAN = """# plan
## Milestone 1
### Sprint 2 — the one under test
#### story-042 — done thing   [done]
Verify: true
#### story-043 — also done   [done]
Verify: true

### Sprint 3
#### story-099 — not this sprint   [ready]
Verify: true
"""

CONFIG = "release: sprint\nsprint_branch: sprint-002\ntests:\n  full: true\n"


def make_repo(tmp_path, plan=PLAN, config=CONFIG):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "data")}
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(plan)
    (repo / ".xp" / "config.yml").write_text(config)
    (repo / "src.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "sprint-002")
    return repo, env, g


def sprint(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(CLOSE), "sprint", "2", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def work(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(WORK), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def snapshot(root: Path):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class TestMembership:
    def test_other_sprints_do_not_block_this_one(self, tmp_path):
        """The naive reading — no story in plan.md is non-done — refuses forever,
        because Sprint 3 is [ready] right now and always will be."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-099" not in r.stdout

    def test_an_unfinished_story_in_THIS_sprint_refuses(self, tmp_path):
        repo, env, _g = make_repo(
            tmp_path,
            plan=PLAN.replace(
                "#### story-043 — also done   [done]", "#### story-043 — also done   [in-progress]"
            ),
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "story-043" in r.stderr


class TestFalsifierBatch:
    def test_a_red_falsifier_aborts_and_is_refiled_as_a_bug(self, tmp_path):
        """Constructed, never observed: the fixture files a debt whose falsifier is
        green now and makes it red before the batch runs."""
        repo, env, _g = make_repo(tmp_path)
        flag = tmp_path / "flag"
        flag.write_text("ok")
        work(
            repo,
            env,
            "debt",
            "--claim",
            "latent",
            "--falsifier",
            f"test -f {flag}",
            "--files",
            "a.py",
        )
        flag.unlink()
        r = sprint(repo, env, "start")
        assert r.returncode == 2, r.stdout
        assert "latent" in r.stderr or "latent" in r.stdout
        assert "## bug " in (tmp_path / "data" / "work.md").read_text()

    def test_a_resolved_record_runs_the_RESOLUTION_falsifier_not_nothing(self, tmp_path):
        """A resolution that was wrong must red later and reopen the record."""
        repo, env, _g = make_repo(tmp_path)
        flag = tmp_path / "fixed"
        flag.write_text("ok")
        work(repo, env, "bug", "--claim", "broken", "--falsifier", "false", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        assert (
            work(repo, env, "resolve", "--ref", ref, "--falsifier", f"test -f {flag}").returncode
            == 0
        )
        assert sprint(repo, env, "start").returncode == 0, "a green resolution should pass"
        flag.unlink()  # the fix regressed
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a resolved record was skipped instead of re-checked"

    def test_only_a_resolved_record_can_substitute_a_falsifier(self, tmp_path):
        """Keyed off the heading `resolve` writes, never off a `Resolves:` line
        anywhere in a block: a record that merely REFERENCES an id would
        substitute its own green falsifier, silencing a live bug with the
        green-check that resolve exists to enforce never having run."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "bug", "--claim", "live", "--falsifier", "false", "--files", "a.py")
        victim = work(repo, env, "list").stdout.split()[0]
        work(
            repo,
            env,
            "debt",
            "--claim",
            f"partial cleanup\nResolves: {victim}",
            "--falsifier",
            "true",
            "--files",
            "a.py",
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a record that only referenced an id silenced a live bug"


class TestStartIsReadOnly:
    def test_start_mutates_nothing_but_appends_to_work_md(self, tmp_path):
        """Structural, so the property survives every future addition to the leg."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "a note to consume")
        root = tmp_path / "data"
        before = snapshot(root)
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
        ).stdout
        assert sprint(repo, env, "start").returncode == 0
        after = snapshot(root)
        for name, blob in before.items():
            if name == Path("work.md"):
                assert after[name].startswith(blob), "work.md was rewritten, not appended to"
            else:
                assert after[name] == blob, f"{name} changed during a read-and-emit leg"
        assert (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout
            == before_head
        )

    def test_start_is_idempotent(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        first = sprint(repo, env, "start")
        second = sprint(repo, env, "start")
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout

    def test_start_emits_the_retro_skeleton_and_the_digest_PROMPT(self, tmp_path):
        """Constraint 7: deterministic Python may not summarize. It emits the
        prompt, exactly as close.py's story leg does."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "SENTINEL-NOTE-FOR-TRIAGE")
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "SENTINEL-NOTE-FOR-TRIAGE" in r.stdout, "notes were not emitted for triage"
        assert "Retro" in r.stdout
        assert "digest" in r.stdout.lower()


class TestLandAndPostMerge:
    def test_land_dry_run_previews_the_commands_it_would_run(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "gh pr create" in r.stdout
        assert (
            subprocess.run(
                ["git", "tag"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout.strip()
            == ""
        ), "a preview created a tag"

    def test_land_refuses_without_gh_before_anything_moves(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "land")
        assert r.returncode == 2 and "gh" in r.stderr

    def test_the_tag_is_cut_post_merge_on_the_merged_trunk_sha(self, tmp_path):
        """Cut at PR-open it names a commit that is not the release: the review
        commits the PR exists to produce land after it."""
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        merged = g("rev-parse", "HEAD").stdout.strip()
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 0, r.stderr
        tags = g("tag").stdout.split()
        assert "v0.3.0" in tags, tags
        assert g("rev-list", "-n1", "v0.3.0").stdout.strip() == merged

    def test_post_merge_retires_the_sprint_branch_key(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        assert sprint(repo, env, "post-merge").returncode == 0
        assert "sprint_branch:" not in (repo / ".xp" / "config.yml").read_text()

    def test_an_existing_tag_refuses_before_anything_moves(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        g("tag", "v0.3.0")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2 and "v0.3.0" in r.stderr
        assert "sprint_branch:" in (repo / ".xp" / "config.yml").read_text()


class TestShippedProse:
    def test_the_sprint_close_skill_names_the_human_only_steps(self):
        skill = (PLUGIN / "skills" / "sprint-close" / "SKILL.md").read_text().lower()
        assert "security review" in skill and "broad review" in skill

    def test_process_carries_the_record_lifecycle_and_the_polarity_contract(self):
        process = (PLUGIN / "PROCESS.md").read_text()
        assert "resolve" in process, (
            "a verb in work.py and not in PROCESS.md is one rule, two impls"
        )
        assert "still OK" in process, "the polarity contract belongs where the filer reads it"
