"""Sprint land and post-merge. Split from test_sprint_close.py at sprint-004 open."""

import json
import subprocess

from close_helpers import launches, stub_reviewer  # noqa: F401
from sprint_helpers import (  # noqa: F401
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    WORK,
    WORK_SECTION,
    committing_stub,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    snapshot,
    sprint,
    work,
)


class TestLandAndPostMerge:
    def test_an_incomplete_round_refuses_before_its_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        round_ = {"fixed": [], "blocking": ["B1"], "noted": [], "incomplete": "DIRT"}
        path.write_text(json.dumps({"rounds": [round_], "shown_sha": head(repo, env)}))
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "incomplete" in r.stderr
        assert "blocking findings" not in r.stderr
        assert "close.py sprint 2 review" in r.stderr, "the refusal names no next action"

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


class TestLandRefusesOnADirtyTree:
    """Sprint-4 closing pass, the round's one blocker: sprint land was the one
    land leg of three with no dirty-tree refusal, so an UNCOMMITTED file decided
    the tier's verdict about a tree the PR does not contain (measured both arms
    on the real leg). The story and free legs refuse this at close.py:241 and
    free.py:80; the green arm is pinned by test_land_proceeds_on_a_green_tier."""

    def test_an_uncommitted_file_refuses_before_the_tier(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "uncommitted.py").write_text("x = 1\n")
        r = sprint(repo, env, "land")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "dirty" in r.stderr.lower(), r.stderr


class TestTheTierJudgesTheTreeThatSHIPS:
    """The release is this branch MERGED into the default branch, and cmd_land
    performs no merge — it ran the tier on the unmerged sprint branch under the
    text "full tier red on the tree you are releasing". So anything the default
    branch gained since the fork (a free release, a hotfix, another stream's
    merge) was never executed together with the sprint, and the PR opened green.
    The story leg has built the merged tree since story-018; this one had not.
    """

    def trunk_gains(self, repo, g, path="probe.py"):
        """A file DISJOINT from the sprint's own, so the merge is clean and only
        EXECUTING it can see the interaction — a conflict would refuse anyway."""
        g("checkout", "-q", "main")
        (repo / path).write_text("LANDED_ON_TRUNK = 1\n")
        g("add", "-A")
        g("commit", "-qm", "a free release landed on main")
        g("checkout", "-q", "sprint-002")

    def test_a_tier_green_here_and_red_on_the_merge_refuses(self, tmp_path):
        repo, env, g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", "full: ! ls probe.py")
        )
        record_reviews(tmp_path, repo, env)
        self.trunk_gains(repo, g)
        # NOT --dry-run: a preview runs nothing. The fixture PATH has no gh, so the
        # MESSAGE is the discriminator — under the defect the tier passes here and
        # land refuses on the missing binary instead.
        r = sprint(repo, env, "land")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "tier red" in r.stderr and "merged with" in r.stderr, r.stderr
        assert g("status", "--porcelain").stdout == "", "the trial merge was left staged"

    def test_the_same_tier_with_trunk_unmoved_still_reaches_the_release(self, tmp_path):
        """The control: without it an implementation that always reds passes above
        and no sprint ever ships."""
        repo, env, _g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", "full: ! ls probe.py")
        )
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land")
        assert r.returncode == 2 and "gh" in r.stderr, r.stderr
        assert "tier" not in r.stderr, r.stderr

    def test_the_preview_names_the_trial_merge_land_would_run(self, tmp_path):
        """A preview that omits the whole release suite on a tree it never
        mentions certifies a plan nobody runs (bookkeep.render_land_preview)."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        self.trunk_gains(repo, g)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "trial merge" in r.stdout, r.stdout


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
        not exist, forcing a whole re-review over a space."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro notes.md").write_text("narrative\n")
        g("add", "-A")
        g("commit", "-qm", "retro prose with a space in the name")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr
