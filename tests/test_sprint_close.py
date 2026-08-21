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

    def test_sprint_2_does_not_swallow_sprint_20(self, tmp_path):
        """Membership was a PREFIX match, so sprint 2 claimed sprint 20's cards:
        closing 2 would refuse forever on a story that is not its own, and a
        double-digit sprint would silently close two sprints as one."""
        repo, env, _g = make_repo(
            tmp_path,
            plan=PLAN.replace(
                "### Sprint 3",
                "### Sprint 20\n#### story-900 — not this sprint   [in-progress]\n\n### Sprint 3",
            ),
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-900" not in r.stdout + r.stderr

    def test_an_unfinished_story_in_THIS_sprint_refuses(self, tmp_path):
        repo, env, _g = make_repo(
            tmp_path,
            plan=PLAN.replace(
                "#### story-043 — also done   [done]", "#### story-043 — also done   [in-progress]"
            ),
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "story-043" in r.stderr


class TestFullTier:
    def test_a_red_full_tier_refuses(self, tmp_path):
        """The fixture tier was `true` — green by construction — so deleting the
        returncode check left every test passing. It is the primary gate of the
        leg: unguarded, sprint close certifies a red suite as a release."""
        repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full: true", "full: false"))
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a red full tier did not stop the close"
        assert "full tier" in r.stderr

    def test_a_stray_top_level_key_cannot_override_the_declared_tier(self, tmp_path):
        """`full:` is only ever nested under `tests:` — the flat lookup was dead
        code, and worse than dead: a stray top-level key silently replaced the
        real tier with a green one and the close certified an unrun suite."""
        repo, env, _g = make_repo(
            tmp_path, config="full: true\n" + CONFIG.replace("full: true", "full: false")
        )
        assert sprint(repo, env, "start").returncode == 2, "a stray key shadowed the real tier"


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
        root = tmp_path / "data"
        before = snapshot(root)
        r = sprint(repo, env, "start")
        assert r.returncode == 2, r.stdout
        assert "latent" in r.stderr or "latent" in r.stdout
        after = snapshot(root)
        assert "## bug " in after[Path("work.md")].decode()
        # the append branch of the read-only property, which the green path
        # cannot reach: this is the only leg that writes anything at all
        assert after[Path("work.md")].startswith(before[Path("work.md")]), "work.md was rewritten"
        assert {k: v for k, v in after.items() if k != Path("work.md")} == {
            k: v for k, v in before.items() if k != Path("work.md")
        }

    def test_re_running_against_an_unfixed_red_files_one_bug_not_one_per_run(self, tmp_path):
        """The red path is the one that actually gets re-run — you fix, then run
        again. Each run appended a fresh duplicate, and every duplicate is itself
        a live record needing its own resolution, so the debris self-perpetuates."""
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
        for _ in range(3):
            assert sprint(repo, env, "start").returncode == 2
        filed = (tmp_path / "data" / "work.md").read_text().count("## bug ")
        assert filed == 1, f"three runs filed {filed} bugs for one unfixed red"

    def test_a_red_archived_falsifier_aborts_too(self, tmp_path):
        """The corpus is BOTH work.md and archive.md: a dropped debt that matters
        reds again, and that is the only mechanism that ever re-reads one."""
        repo, env, _g = make_repo(tmp_path)
        root = tmp_path / "data"
        root.mkdir(parents=True, exist_ok=True)
        (root / "archive.md").write_text(
            "## debt 2026-01-01T00:00:00Z (dropped)\nClaim: latent\n"
            "Falsifier: `false`\nFiles: a.py\n\n"
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "archive.md falsifiers were never run"
        assert "archive" in r.stderr

    def test_a_green_archived_falsifier_does_not_abort(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        root = tmp_path / "data"
        root.mkdir(parents=True, exist_ok=True)
        (root / "archive.md").write_text("Falsifier: `true`\n\n")
        assert sprint(repo, env, "start").returncode == 0

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

    def test_land_refuses_to_advertise_a_version_it_cannot_compute(self, tmp_path):
        """The PR title names the release; guessing there is the same lie."""
        repo, env, g = make_repo(tmp_path)
        g("tag", "release-2024")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "release-2024" in r.stderr

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

    def test_post_merge_on_the_unmerged_sprint_branch_refuses(self, tmp_path):
        """The leg exists to cut the tag on the sha that SHIPPED. Nothing made
        that true: it tagged whatever HEAD was, so running it without checking
        out trunk named an unreviewed sprint-branch commit as the release."""
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        (repo / "unreviewed.py").write_text("# never went through the PR\n")
        g("add", "-A")
        g("commit", "-qm", "unmerged work")
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2, "tagged a release on an unmerged branch"
        assert "v0.3.0" not in g("tag").stdout.split()
        assert "sprint_branch:" in (repo / ".xp" / "config.yml").read_text()

    def test_post_merge_on_trunk_without_the_merge_refuses(self, tmp_path):
        """On trunk, but the sprint branch never landed: the tag would name a
        commit that contains none of the sprint."""
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        (repo / "unreviewed.py").write_text("# never went through the PR\n")
        g("add", "-A")
        g("commit", "-qm", "unmerged work")
        g("checkout", "-q", "main")
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2, "tagged a release that contains none of the sprint"
        assert "v0.3.0" not in g("tag").stdout.split()

    def test_a_non_semver_latest_tag_refuses(self, tmp_path):
        """AC 12 makes the latest git tag the version source so the leg works in
        a CONSUMING project — whose tag scheme is exactly the input we do not
        control. `v1.x` tracebacked; `release-2024` minted `vrelease-2024.1.0`."""
        repo, env, g = make_repo(tmp_path)
        g("tag", "release-2024")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
        assert g("tag").stdout.split() == ["release-2024"], "minted a version off a non-semver tag"

    def test_post_merge_without_a_config_refuses_rather_than_tracebacks(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        (repo / ".xp" / "config.yml").unlink()
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr

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
