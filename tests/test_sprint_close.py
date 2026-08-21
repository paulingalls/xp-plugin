"""story-009: sprint-close pipeline. Verify: pytest -q tests/test_sprint_close.py"""

import json
import subprocess
import sys
from pathlib import Path

from test_close import launches, stub_reviewer

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

CONFIG = (
    "release: sprint\nsprint_branch: sprint-002\n"
    "roles:\n  reviewer: claude/opus\ntests:\n  full: true\n"
)


def make_repo(tmp_path, plan=PLAN, config=CONFIG):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(plan)
    (repo / ".xp" / "config.yml").write_text(config)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "src.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "sprint-002")
    # the sprint's own work, absent from the default branch: under `release:
    # sprint` an integration_target() diff would not carry it
    (repo / "src.py").write_text("A = 1\nB = 'SPRINT-ONLY-SENTINEL'\n")
    g("add", "-A")
    g("commit", "-qm", "story work on the sprint branch")
    return repo, env, g


def sprint(repo, env, *args, sprint_id="2"):
    return subprocess.run(
        [sys.executable, str(CLOSE), "sprint", sprint_id, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def head(repo, env):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
    ).stdout.strip()


def marker_path(tmp_path, lens, sprint_id="2"):
    return tmp_path / "data" / "markers" / "sprint" / f"{sprint_id}.{lens}.json"


def record_reviews(tmp_path, repo, env, blocking=(), lenses=("broad", "security")):
    """CONSTRUCT the state a real review leaves, so land's guard is exercised
    against markers rather than against the absence of them."""
    for lens in lenses:
        path = marker_path(tmp_path, lens)
        path.parent.mkdir(parents=True, exist_ok=True)
        round_ = {"fixed": [], "blocking": list(blocking), "noted": []}
        path.write_text(json.dumps({"rounds": [round_], "shown_sha": head(repo, env)}))


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

    def test_a_red_batch_refuses_before_the_full_tier_runs(self, tmp_path):
        """afbd01a3: the batch ran the full tier (256 tests, ~25s) before refusing
        on a falsifier it could have checked first. The tier writes a sentinel;
        BOTH halves are asserted, because absence alone also passes an
        implementation that simply deleted the tier."""
        sentinel = tmp_path / "tier-ran"
        repo, env, _g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", f"full: touch {sentinel}")
        )
        flag = tmp_path / "flag"
        flag.write_text("ok")
        work(
            repo, env, "debt", "--claim", "latent", "--falsifier", f"test -f {flag}", "--files", "a"
        )
        flag.unlink()
        assert sprint(repo, env, "start").returncode == 2
        assert not sentinel.exists(), "the expensive tier ran before the cheap batch refused"
        flag.write_text("ok")
        assert sprint(repo, env, "start").returncode == 0
        assert sentinel.exists(), "a green batch never reached the tier"

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


class TestReviewLeg:
    """story-014: the sprint close marshals its reviews, one leg, two lenses."""

    def test_the_bundle_diffs_against_the_DEFAULT_branch_not_the_integration_target(self, tmp_path):
        """Under `release: sprint`, integration_target() returns the SPRINT branch
        and the fixture is ON it — so that diff is EMPTY and the reviewer would
        certify nothing. A header-grep assertion passes over an empty diff, which
        is bug c9b48a66's own failure mode; a hardcoded "main" passes vacuously
        here and breaks a `master` consumer. So: a string only a sprint-branch
        commit carries."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 0, r.stderr
        assert "SPRINT-ONLY-SENTINEL" in launches(tmp_path)[0]["stdin"]

    def test_the_bundle_carries_the_cards_constraints_and_system(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "CONSTRAINT-SENTINEL" in bundle and "SYSTEM-SENTINEL" in bundle
        assert "story-042 — done thing" in bundle, "the sprint's story cards"
        assert "story-099" not in bundle, "another sprint's card rode along"
        assert "Polarity" in bundle, "PROCESS.md, which the charter points at"

    def test_a_story_cannot_shadow_the_sprints_report_or_marker_key(self, tmp_path):
        """Constraint 10, fault-injected against the id that would collide: a
        story literally named `sprint-2.broad`. BOTH keys — scoping the report and
        not the marker hands the land gate the collision the report just refused.
        Driven through both real legs, because comparing two Path expressions
        holds even against an implementation nobody can reach."""
        plan = PLAN.replace(
            "#### story-043 — also done   [done]",
            "#### story-043 — also done   [done]\n"
            "#### sprint-2.broad — the colliding id   [in-progress]\nVerify: true",
        )
        repo, env, g = make_repo(tmp_path, plan=plan)
        g("checkout", "-qb", "story-branch")
        story = subprocess.run(
            [sys.executable, str(CLOSE), "story", "sprint-2.broad", "review"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert story.returncode == 0, story.stderr
        g("checkout", "-q", "sprint-002")
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        data = tmp_path / "data"
        written = sorted(p.name for p in (data / "reports").rglob("*.json"))
        markers = sorted(p.name for p in (data / "markers").rglob("*.json"))
        assert len(written) == 2, f"the sprint and the story shared a report key: {written}"
        assert len(markers) == 2, f"the sprint and the story shared a marker key: {markers}"
        assert marker_path(tmp_path, "broad").exists()

    def test_the_review_leg_run_from_the_default_branch_is_refused(self, tmp_path):
        """close.py:186 has this guard for the story leg. Without it the diff is
        empty and land pushes whatever branch HEAD happens to be on."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2 and "main" in r.stderr
        assert launches(tmp_path) == [], "spawned a reviewer over an empty diff"

    def test_an_unknown_lens_is_refused_naming_the_ones_that_exist(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", "--lens", "vibes")
        assert r.returncode == 2 and "broad" in r.stderr and "security" in r.stderr
        assert launches(tmp_path) == []

    def test_shown_sha_is_the_head_captured_BEFORE_the_launch(self, tmp_path):
        """close.cmd_review records POST-run deliberately, because its motion
        checks bound what could have moved. This leg has no such checks, so
        copying that ordering makes anything the reviewer commits count as
        reviewed and ride the release PR."""
        repo, env, _g = make_repo(tmp_path)
        before = head(repo, env)
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        assert json.loads(marker_path(tmp_path, "broad").read_text())["shown_sha"] == before

    def test_dry_run_launches_nothing_and_records_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", "--lens", "broad", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert launches(tmp_path) == []
        assert not marker_path(tmp_path, "broad").exists()

    def test_the_two_lenses_keep_separate_markers_reports_and_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [], "noted": ["BROAD-FINDING"]})
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        assert sprint(repo, env, "review", "--lens", "security").returncode == 0
        assert marker_path(tmp_path, "broad").exists()
        assert marker_path(tmp_path, "security").exists()
        assert "BROAD-FINDING" not in launches(tmp_path)[1]["stdin"], "prior findings leaked lens"


class TestModeSwitch:
    """Note bae0b87b: findings handed in -> validate each; none handed in -> run
    the full pass. The mode switch is what BOUNDS the work — sprint-002's close
    re-reviewed four fix-commits with no prior findings to bound the pass."""

    def test_round_1_tells_the_reviewer_to_run_the_full_pass(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        # the SECTION's own words: the charter also says "run the full pass",
        # so a bare "full pass" grep passes on every bundle ever built
        assert "none — run the full pass yourself" in launches(tmp_path)[0]["stdin"]

    def test_a_second_round_of_the_same_lens_carries_the_prior_findings(self, tmp_path):
        """Read from the MARKER state, which is where close.py keeps rounds.
        Reading `reports/` off disk would be a second source of truth — so the
        fixture CONSTRUCTS the marker, never the report file."""
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path, "broad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "rounds": [
                        {"fixed": [], "blocking": ["ROUND-1-BLOCKER"], "noted": ["ROUND-1-NOTE"]}
                    ],
                    "shown_sha": head(repo, env),
                }
            )
        )
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "ROUND-1-BLOCKER" in bundle and "ROUND-1-NOTE" in bundle
        assert "validate that each was addressed; do not re-derive the diff" in bundle
        assert "run the full pass yourself" not in bundle, "handed findings AND told to re-derive"


def committing_stub(tmp_path, body):
    """A stub that writes a valid report and then moves the tree. A stub that
    never moves it certifies nothing (constraint 2)."""
    bin_dir = stub_reviewer(tmp_path)
    claude = bin_dir / "claude"
    claude.write_text(claude.read_text().replace("sys.stdout.write(", body + "\nsys.stdout.write("))
    claude.chmod(0o755)
    return bin_dir


class TestReportOnlyIsAMechanism:
    """AC 2. The card calls report-only a MECHANISM, not a charter claim, because
    the plan review found the claim unenforced. The agent file's `tools:` line
    bounds nothing here: review.run launches a TOP-LEVEL claude session that never
    loads the agent file — which is why charter() inlines it."""

    def test_a_reviewer_that_COMMITS_is_refused_and_records_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(
            tmp_path,
            "open('snuck.py','w').write('X = 1\\n')\n"
            "os.system('git add -A && git commit -qm snuck')\n",
        )
        before = head(repo, env)
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2, r.stdout
        assert before[:8] in r.stderr, "the undo names no sha to reset to"
        assert not marker_path(tmp_path, "broad").exists(), "recorded a round it refused"

    def test_a_reviewer_that_leaves_the_tree_DIRTY_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')\n")
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2 and "dirty" in r.stderr
        assert not marker_path(tmp_path, "broad").exists()

    def test_a_reviewer_that_rewrites_the_MARKER_is_refused(self, tmp_path):
        """The marker is outside the repo, no diff shows it, and it is the file
        land reads for rounds and blocking[] — a review may not move its own gate."""
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path, "broad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [], "shown_sha": "x"}))
        committing_stub(
            tmp_path,
            f"open({str(path)!r},'w').write('{json.dumps({'rounds': [], 'shown_sha': 'y'})}')\n",
        )
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2 and "marker" in r.stderr


class TestSprintCharter:
    def test_the_sprint_charter_is_a_delta_not_a_second_charter(self):
        """An opus executor with no bound models this on story-reviewer.md (712
        words), whose FIRST duty is "YOU FIX WHAT YOU FIND, in the tree you were
        given" — a fixing charter for a leg whose mechanism refuses any motion."""
        text = (PLUGIN / "agents" / "sprint-reviewer.md").read_text()
        body = text.split("---", 2)[2]
        assert len(body.split()) <= 150, f"{len(body.split())} words: a charter, not a delta"
        assert "in the tree you were given" not in body, "the fixing duty contradicts this leg"
        assert "report-only" in body.lower()
        assert "PROCESS.md" in body, "the bar and the rubric are POINTED at, never restated"
        # the report SHAPE as the reviewer must write it, not the bucket names in
        # prose: `noted` reads fine in a sentence that never states the JSON
        for token in ('"fixed"', '"blocking"', '"noted"', "broad", "security"):
            assert token in body, f"the charter never names {token}"

    def test_the_new_agent_files_frontmatter_is_funded_not_added(self):
        """Both shipped-prose caps sit at 240/300 and 1197/1200 — one token of
        headroom before this story. Constraint 1 is mechanical here: the sprint
        charter's frontmatter is paid for out of story-reviewer.md's."""
        sys.path.insert(0, str(CLOSE.parent))
        from spawn import (
            COMPONENT_METADATA_CAP,
            PLUGIN_SHIPPED_CAP,
            component_metadata_chars,
            plugin_shipped_chars,
        )

        assert component_metadata_chars() // 4 <= COMPONENT_METADATA_CAP
        assert plugin_shipped_chars() // 4 <= PLUGIN_SHIPPED_CAP


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
