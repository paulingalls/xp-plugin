"""Sprint land and post-merge. Split from test_sprint_close.py at sprint-004 open."""

import json
import subprocess
import sys

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

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))
from sprint_land import _release_body


def release_tools(tmp_path, env, g):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    record = tmp_path / "gh.json"
    gh = tmp_path / "bin" / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\nassert '--body' not in args\n"
        "path = args[args.index('--body-file') + 1]\n"
        "data = {'argv': args, 'body': open(path).read()}\n"
        f"open({str(record)!r}, 'w').write(json.dumps(data))\n"
    )
    gh.chmod(0o755)
    return record


def write_closes(tmp_path, records):
    path = tmp_path / "data" / "closes.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def record_release(tmp_path, state):
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(state))
    write_closes(tmp_path, [{"story": "story-042", "title": "done", "merge_sha": "2" * 40}])


def release_state(repo, env, **round_changes):
    covered = head(repo, env)
    coverage = {"reviewed_head": covered, "shown_sha": covered}
    round_ = {"fixed": [], "blocking": [], "noted": [], **coverage, **round_changes}
    receipt = {"tier": "full", "command": "true", "tree": "recorded-tree", "head": "recorded-head"}
    receipt.update(verdict="passed", ran_by="land", reused=False)
    return dict(rounds=[round_], reviewed_head=covered, shown_sha=covered, full_tier=receipt)


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

    def test_post_merge_clears_the_recorded_sprint_branch(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("tag", "v0.2.1")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        config = (repo / ".xp" / "config.yml").read_text()
        assert sprint(repo, env, "post-merge").returncode == 0
        assert not (tmp_path / "data" / "sprint_branch").exists()
        assert (repo / ".xp" / "config.yml").read_text() == config

    def test_post_merge_without_a_recorded_branch_refuses(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (tmp_path / "data" / "sprint_branch").unlink()
        g("tag", "v0.2.1")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        r = sprint(repo, env, "post-merge")
        assert r.returncode == 2 and "no sprint branch recorded" in r.stderr

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
        assert (tmp_path / "data" / "sprint_branch").read_text().strip() == "sprint-002"

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
        assert (tmp_path / "data" / "sprint_branch").read_text().strip() == "sprint-002"


class TestReleasePrBody:
    def test_the_release_pr_carries_only_this_sprints_record(self, tmp_path):
        events = tmp_path / "tier-events"
        command = f"printf x >> {events}"
        repo, env, g = make_repo(tmp_path, config=CONFIG.replace("full: true", f"full: {command}"))
        assert sprint(repo, env, "start").returncode == 0
        marker = marker_path(tmp_path)
        state = json.loads(marker.read_text())
        state["full_tier"]["head"] = "recorded-start-head"
        covered = head(repo, env)
        rounds = [
            release_state(repo, env, fixed=["first fix"], noted=["first note", "second note"])[
                "rounds"
            ][0],
            release_state(
                repo,
                env,
                fixed=["second fix", "third fix"],
                blocking=["RUN-FULL-BEFORE-RELEASE"],
                clearable_by_full=["RUN-FULL-BEFORE-RELEASE"],
            )["rounds"][0],
        ]
        state.update(rounds=rounds, reviewed_head=covered, shown_sha=covered)
        marker.write_text(json.dumps(state))
        write_closes(
            tmp_path,
            [
                {"story": "story-043", "title": "also done", "merge_sha": "4" * 40},
                {"story": "story-042", "title": "done thing", "merge_sha": "2" * 40},
                {"story": "story-099", "title": "not this sprint", "merge_sha": "9" * 40},
            ],
        )
        gh_record = release_tools(tmp_path, env, g)

        result = sprint(repo, env, "land")

        assert result.returncode == 0, result.stdout + result.stderr
        assert events.read_text() == "x" and not (tmp_path / "launches.jsonl").exists()
        call = json.loads(gh_record.read_text())
        assert "--body-file" in call["argv"] and "--body" not in call["argv"]
        body = call["body"]
        first, second = body.index("story-042"), body.index("story-043")
        assert first < second and "2" * 40 in body and "4" * 40 in body
        assert "story-099" not in body and "9" * 40 not in body and "not this sprint" not in body
        assert "Round 1: 1 fixed · 0 blocking · 2 noted" in body
        assert "Round 2: 2 fixed · 1 blocking · 0 noted" in body
        for value in (
            covered,
            "RUN-FULL-BEFORE-RELEASE",
            "Tier: full",
            "Verdict: passed",
            command,
            state["full_tier"]["tree"],
            "reused from start at recorded-start-head",
        ):
            assert value in body

    def test_a_land_run_is_not_described_as_reused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_release(tmp_path, release_state(repo, env))
        gh_record = release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        body = json.loads(gh_record.read_text())["body"]
        assert result.returncode == 0 and "ran by land" in body and "reused from" not in body

    def test_no_recorded_round_still_refuses_before_tier_or_gh(self, tmp_path):
        touched = tmp_path / "tier-ran"
        repo, env, _g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", f"full: touch {touched}")
        )
        marker = marker_path(tmp_path)
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"rounds": [], "full_tier": {}}))
        before = marker.read_bytes()
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "no recorded review for sprint 2" in result.stderr
        assert not touched.exists() and not (tmp_path / "gh.json").exists()
        assert marker.read_bytes() == before

    def test_huge_findings_are_counted_without_becoming_the_body(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        sentinel = "FINDING-PROSE-" * 1000
        record_release(tmp_path, release_state(repo, env, fixed=[sentinel], noted=[sentinel]))
        gh_record = release_tools(tmp_path, env, g)
        assert sprint(repo, env, "land").returncode == 0
        body = json.loads(gh_record.read_text())["body"]
        assert "1 fixed · 0 blocking · 1 noted" in body
        assert sentinel not in body and len(body) < 65_536

    def test_an_overlong_body_refuses_before_push_or_gh(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        huge = "BOUND-" * 11000
        state = release_state(repo, env, blocking=[huge], clearable_by_full=[huge])
        record_release(tmp_path, state)
        gh_record = release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "65536" in result.stderr
        assert "missing" not in result.stderr and "unreadable" not in result.stderr
        assert (
            not gh_record.exists()
            and g("ls-remote", "--heads", "origin", "sprint-002").stdout == ""
        )

    def test_release_inputs_name_the_unreadable_part(self, tmp_path, monkeypatch):
        repo, env, _g = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        state = release_state(repo, env)
        record_release(tmp_path, state)
        close_log = tmp_path / "data" / "closes.jsonl"
        close_log.unlink()
        assert "missing close log" in _release_body("2", state, marker_path(tmp_path))[1]
        close_log.write_text("{broken\n")
        assert "unreadable close log" in _release_body("2", state, marker_path(tmp_path))[1]
        record_release(tmp_path, state)
        state.pop("reviewed_head")
        state["rounds"][-1].pop("reviewed_head")
        assert "reviewed_head" in _release_body("2", state, marker_path(tmp_path))[1]
        state = release_state(repo, env)
        state["full_tier"] = None
        assert "full_tier" in _release_body("2", state, marker_path(tmp_path))[1]
        state = release_state(repo, env)
        write_closes(tmp_path, [{"story": "story-099", "title": "OTHER", "merge_sha": None}])
        body, error = _release_body("2", state, marker_path(tmp_path))
        assert not error and body.count("no close record") == 2 and "OTHER" not in body
        (tmp_path / "data" / "plan.md").write_text(PLAN.replace("### Sprint 2", "### Sprint 8"))
        assert "no `### Sprint 2` section" in _release_body("2", state, marker_path(tmp_path))[1]


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

    def test_land_discloses_reviewer_work_from_every_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        shas = [head(repo, env)]
        for n in (1, 2):
            (repo / f"round-{n}.py").write_text(f"ROUND_{n} = True\n")
            g("add", "-A")
            g("commit", "-qm", f"REVIEWER-ROUND-{n}")
            shas.append(head(repo, env))
        marker = marker_path(tmp_path)
        marker.parent.mkdir(parents=True, exist_ok=True)
        rounds = [
            {
                "fixed": [],
                "blocking": [],
                "noted": [],
                "reviewed_head": shas[n],
                "shown_sha": shas[n + 1],
            }
            for n in range(2)
        ]
        marker.write_text(json.dumps({"rounds": rounds, **rounds[-1]}))
        result = sprint(repo, env, "land")
        assert "REVIEWER-ROUND-1" in result.stdout and "REVIEWER-ROUND-2" in result.stdout

    def test_dry_run_does_not_run_the_tier(self, tmp_path):
        """af9023f put the tier ABOVE the `if dry_run` return, so a preview paid
        the whole sprint suite and a red tier turned a preview into a refusal.
        The story-side analogue is explicit: "pure preview: nothing runs, nothing
        changes". A red tier is the discriminator — under the bug it refuses."""
        repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full: true", "full: false"))
        record_reviews(tmp_path, repo, env)
        before = marker_path(tmp_path).read_bytes()
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "unless a passed receipt matches the shipping tree and command" in r.stdout
        assert marker_path(tmp_path).read_bytes() == before

    def test_dry_run_says_when_the_full_tier_cannot_run(self, tmp_path):
        config = CONFIG.replace("  full: true\n", "  full: EDIT-ME\n")
        repo, env, _g = make_repo(tmp_path, config=config)
        record_reviews(tmp_path, repo, env)
        preview = sprint(repo, env, "land", "--dry-run")
        assert preview.returncode == 2 and "Set tests.full" in preview.stderr
        assert "gh pr create" not in preview.stdout and "EDIT-ME" not in preview.stdout
        landed = sprint(repo, env, "land")
        assert landed.returncode == 2 and "Set tests.full" in landed.stderr

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
