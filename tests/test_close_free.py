"""Free mode: the card-less branch, its review, and the release it opens.

Every land test here has a twin on the story leg, because free mode's whole
risk is a guard the story leg has and this one lacks (story-011's close note).
"""

import datetime
import json
import re
import subprocess
import sys

import pytest
from close_helpers import CLOSE, close, free, free_repo, gh_calls, make_repo, marker_file

TODAY = datetime.date.today().isoformat()
BRANCH = f"t/free-{TODAY}-fix-typo"
KEY = f"free/{TODAY}-fix-typo"


def normalize(refusal: str) -> str:
    masked = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", refusal)
    return re.sub(r"close\.py \S+ \S+ review", "close.py <leg> review", masked).strip()


def commit_on_free(repo, g, text="B = 1\n", path="src/free.py", msg="free work"):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    g("add", "-A")
    g("commit", "-qm", msg)


def reviewed(tmp_path, slug="fix-typo"):
    """A free branch with one commit and one clean recorded round."""
    repo, env, g = free_repo(tmp_path, slug)
    assert free(repo, env, slug, "start").returncode == 0
    commit_on_free(repo, g)
    r = free(repo, env, slug, "review")
    assert r.returncode == 0, r.stderr + r.stdout
    return repo, env, g


class TestFreeStart:
    def test_start_cuts_the_dated_branch_off_the_default_branch(self, tmp_path):
        """AC 1: the branch is dated so two closes of the same slug never share
        a name — and so never share the marker keyed off it."""
        repo, env, g = free_repo(tmp_path)
        main = g("rev-parse", "main").stdout.strip()
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 0, r.stderr
        assert g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == BRANCH
        assert g("rev-parse", BRANCH).stdout.strip() == main

    def test_start_anywhere_but_the_default_branch_refuses_naming_it(self, tmp_path):
        """AC 2: a free branch cut off a story branch carries that story's
        unreleased work into a patch release."""
        repo, env, g = free_repo(tmp_path)
        g("checkout", "-q", "story-042-branch")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2
        assert "main" in r.stderr and "story-042-branch" in r.stderr

    def test_start_refuses_a_dirty_tree(self, tmp_path):
        repo, env, _g = free_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 99\n")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2 and "dirty" in r.stderr

    def test_start_refuses_an_existing_branch(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "start")
        assert r.returncode == 2 and BRANCH in r.stderr


class TestFreeReview:
    def test_the_bundle_carries_no_story_card(self, tmp_path):
        """AC 1: card-less is the point — the bundle must SAY there is no card,
        not omit the section and let the reviewer invent a scope."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        r = free(repo, env, "fix-typo", "review")
        assert r.returncode == 0, r.stderr
        from close_helpers import launches

        bundle = launches(tmp_path)[-1]["stdin"]
        assert "#### story-042" not in bundle, "a free bundle carried a story card"
        assert "free branch" in bundle
        assert "B = 1" in bundle, "the bundle carried no diff"

    def test_a_reviewer_that_edits_a_gate_file_is_refused(self, tmp_path):
        """No card means no `Files:` line, so the shared `.xp/` scope in
        check_reviewer_motion admits nothing at all. Fault-injected: the stub
        commits a config edit as the reviewer."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        gh = tmp_path / "bin" / "claude"
        gh.write_text(
            gh.read_text().replace(
                "sys.stdout.write",
                "open('.xp/config.yml', 'a').write('# edited\\n')\n"
                "import subprocess\n"
                "subprocess.run(['git', 'add', '-A'])\n"
                "subprocess.run(['git', '-c', 'user.name=xp story-reviewer',"
                " '-c', 'user.email=story-reviewer@xp.local', 'commit', '-qm', 'r'])\n"
                "sys.stdout.write",
            )
        )
        r = free(repo, env, "fix-typo", "review")
        assert r.returncode == 2, r.stdout
        assert ".xp/config.yml" in r.stderr and "may fix code" in r.stderr


class TestFreeLand:
    def test_land_opens_the_pr_to_main_with_the_patch_bump(self, tmp_path):
        """AC 3: v0.2.0 -> v0.2.1. A free close targeting main IS a release, and
        a minor bump here would claim a sprint's worth of change."""
        repo, env, _g = reviewed(tmp_path)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr + r.stdout
        create = [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]
        assert len(create) == 1, gh_calls(tmp_path)
        assert "v0.2.1" in " ".join(create[0])
        assert "--base" in create[0] and create[0][create[0].index("--base") + 1] == "main"

    def test_land_with_no_report_refuses(self, tmp_path):
        """AC 4: the report is pipeline-received, so its absence is the whole
        gate — there is no flag that supplies one."""
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        commit_on_free(repo, g)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2
        assert "review" in r.stderr and not gh_calls(tmp_path)

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = reviewed(tmp_path)
        path = marker_file(tmp_path, KEY)
        state = json.loads(path.read_text())
        state["rounds"][-1]["blocking"] = ["a real defect"]
        path.write_text(json.dumps(state))
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and "a real defect" in r.stderr

    def test_land_refuses_from_anywhere_but_its_own_free_branch(self, tmp_path):
        """The recorded round names a branch; land pushes HEAD. Without this,
        a merged free close replays from main — every other guard passes there,
        because shown_sha is an ancestor of main once the PR lands."""
        repo, env, g = reviewed(tmp_path)
        g("checkout", "-q", "main")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and BRANCH in r.stderr
        assert not gh_calls(tmp_path)

    def test_land_refuses_a_dirty_tree(self, tmp_path):
        repo, env, _g = reviewed(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 99\n")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2 and "dirty" in r.stderr

    def test_land_reports_a_lead_commit_the_round_never_covered(self, tmp_path):
        repo, env, g = reviewed(tmp_path)
        commit_on_free(repo, g, "C = 1\n", "src/late.py", "after the review")
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 0, r.stderr
        assert "unreviewed" in r.stdout, r.stdout


class TestSharedLandGuards:
    """AC 5. Each guard is fault-injected on BOTH legs and the refusal texts are
    asserted IDENTICAL — the property is one implementation, not two that agree
    today. A grep for the string in free.py would pass a rebuilt copy."""

    def rewrite_history(self, g):
        """The 012b/N2 injection: the recorded round's sha stops being an
        ancestor of HEAD, so it describes a tree that no longer exists."""
        g("commit", "-q", "--amend", "-m", "rewritten")

    def edit_gate_file(self, repo, g):
        (repo / ".xp" / "config.yml").write_text("roles:\n  reviewer: claude/opus\n")
        g("add", "-A")
        g("commit", "-qm", "swap the tier land runs")

    def story_refusal(self, tmp_path, inject):
        repo, env, g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        inject(repo, g)
        r = close(repo, env, "land")
        assert r.returncode == 2, r.stdout
        return r.stderr

    def free_refusal(self, tmp_path, inject):
        repo, env, g = reviewed(tmp_path)
        inject(repo, g)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2, r.stdout
        assert not gh_calls(tmp_path), "refused, but the PR was already open"
        return r.stderr

    @pytest.mark.parametrize(
        "inject,marks",
        [
            (lambda repo, g: TestSharedLandGuards().rewrite_history(g), ("does not contain",)),
            (
                lambda repo, g: TestSharedLandGuards().edit_gate_file(repo, g),
                (".xp/config.yml", "gate"),
            ),
        ],
        ids=["ancestor", "gate-file"],
    )
    def test_both_legs_refuse_with_the_same_words(self, tmp_path, inject, marks):
        story = self.story_refusal(tmp_path / "s", inject)
        freed = self.free_refusal(tmp_path / "f", inject)
        for mark in marks:
            assert mark in story, story
            assert mark in freed, freed
        assert "close.py free fix-typo review" in freed, freed
        assert "close.py story story-042 review" in story, story
        # EQUAL, not merely overlapping, modulo the two things that legitimately
        # differ: the sha each fixture produced and the leg's own review command.
        assert normalize(story) == normalize(freed)

    def test_the_tier_that_gates_is_the_one_the_merged_tree_declares(self, tmp_path):
        """The other half of the gate-file threat: a tier arriving on TRUNK is
        invisible to a shown..HEAD guard, and land read its command string
        before the trial merge — so the merge ran the tier it replaced."""
        repo, env, g = reviewed(tmp_path)
        g("checkout", "-q", "main")
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:\n  story: true\n  full: false\n"
        )
        g("add", "-A")
        g("commit", "-qm", "trunk tightens the release tier")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", BRANCH)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2, "ran the tier trunk replaced, and opened the PR"
        assert "tier red" in r.stderr, r.stderr
        assert not gh_calls(tmp_path)

    def test_land_refuses_on_overlap_with_trunk(self, tmp_path):
        """The third shared guard: trunk touched a file this branch touched and
        no review covered the two together."""
        repo, env, g = reviewed(tmp_path)
        g("checkout", "-q", "main")
        commit_on_free(repo, g, "B = 2\n", "src/free.py", "trunk touched it too")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", BRANCH)
        r = free(repo, env, "fix-typo", "land")
        assert r.returncode == 2
        assert "src/free.py" in r.stderr and "no review covered" in r.stderr
        assert not gh_calls(tmp_path)


class TestFreeIsUndocumentedNowhere:
    def test_free_help_names_the_three_actions(self, tmp_path):
        """Constraint 12: a surface a consuming project drives must answer
        --help without doing anything."""
        r = subprocess.run(
            [sys.executable, str(CLOSE), "free", "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert r.returncode == 0
        for action in ("start", "review", "land"):
            assert action in r.stdout
