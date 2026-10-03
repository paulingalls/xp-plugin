import json
from pathlib import Path

from close_helpers import LEAD_CREDS
from diff_reference_helpers import read_named_diff
from review_case_data import ANGLES, CANDIDATES, LEFTHOOK, SURVIVES, angle_names
from sprint_helpers import (
    PLUGIN,
    bundles,
    committing_stub,
    make_repo,
    marker_path,
    sprint,
    staged_stub,
)


class TestTheCommitGateRefusalIsActionable:
    def refusal(self, tmp_path, gate):
        """What the pipeline prints when the commit gate refuses the fixer's patch.
        `gate` is the lines the gate emits before exiting 1."""
        repo, env, _g = make_repo(tmp_path)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n" + "".join(f"printf '{ln}\\n'\n" for ln in gate) + "exit 1\n")
        hook.chmod(0o755)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            fix={
                "fixed": ["a fix the gate rejects"],
                "blocking": [],
                "schema": 2,
                "dropped": [],
                "debt": [],
            },
            patches=[("fix", "src.py", "FIX")],
        )
        r = sprint(repo, {**env, **LEAD_CREDS}, "review")
        assert r.returncode == 2, r.stdout + r.stderr
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["fixed"] == ["a fix the gate rejects"] and round_["stages"][-1] == "fix"
        assert round_["blocking"] and set(round_["blocking"]) == {"a silent one"}
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and "incomplete" in land.stderr
        return repo, env, _g, r.stdout + r.stderr

    def test_the_refusal_names_the_log_with_the_gate_cause(self, tmp_path):
        repo, env, _g, out = self.refusal(tmp_path, LEFTHOOK)
        log = Path(env["XP_DATA"]) / "logs/story-042-fixer.log"
        assert str(log) in out
        assert "would be reformatted" in log.read_text()
        assert "FIX" in (repo / "src.py").read_text()

    def test_refused_commit_preserves_the_staged_work_without_an_undo(self, tmp_path):
        repo, _env, g, out = self.refusal(tmp_path, LEFTHOOK)
        assert "git reset --hard" not in out
        assert "FIX" in (repo / "src.py").read_text()
        assert "FIX" in g("diff", "--cached").stdout

    def test_long_gate_output_preserves_its_cause_in_the_named_log(self, tmp_path):
        gate = ["CAUSE-ABOVE-THE-CUT"] + [f"noise {n}" for n in range(14)]
        _repo, env, _g, out = self.refusal(tmp_path, gate)
        log = Path(env["XP_DATA"]) / "logs/story-042-fixer.log"
        assert str(log) in out
        text = log.read_text()
        assert all(line in text for line in gate)

    def test_the_humans_commit_gets_explicit_integration_judgment(self, tmp_path):
        repo, env, g, _out = self.refusal(tmp_path, LEFTHOOK)
        (repo / ".git" / "hooks" / "pre-commit").unlink()
        assert g("commit", "-qm", "human accepts fixer work").returncode == 0
        before = g("rev-parse", "HEAD").stdout
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
        assert len(rounds) == 2 and rounds[0]["incomplete"]
        assert "incomplete" not in rounds[1]
        assert bundles(tmp_path, "close") == []
        assert g("rev-parse", "HEAD").stdout == before
        assert (tmp_path / "data/reports/sprint/2.fix.round-1.json").exists()


class TestTheGateIsNotHalfFixed:
    def test_a_reviewer_that_rewrites_the_MARKER_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [], "shown_sha": "x"}))
        erased = json.dumps(
            {
                "rounds": [{"fixed": [], "blocking": [], "schema": 2, "dropped": [], "debt": []}],
                "shown_sha": "y",
            }
        )
        committing_stub(tmp_path, f"open({str(path)!r}, 'w').write({erased!r})")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "marker" in r.stderr, r.stderr


class TestTheClosingPass:
    """AC 5. It runs after the fixer, over the tree the fixer left, and looks for
    blockers only. Both arms are injected: a pass that cannot fail certifies, and
    a pass that fails on a clean tree stops every release."""

    def test_a_blocker_from_the_closing_pass_stops_the_release(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            fix={"fixed": ["fixed it"], "blocking": [], "schema": 2, "dropped": [], "debt": []},
            close={
                "fixed": [],
                "blocking": ["THE-FIX-BROKE-IT"],
                "schema": 2,
                "dropped": [],
                "debt": [],
            },
        )
        assert sprint(repo, env, "review").returncode == 2
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and "THE-FIX-BROKE-IT" in land.stderr

    def test_a_clean_closing_pass_lets_the_release_proceed(self, tmp_path):
        """The green twin: without it, an always-blocking closer passes the test
        above and nothing ever releases."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path, find=CANDIDATES, verify=SURVIVES)
        assert sprint(repo, env, "review").returncode == 0
        assert len(bundles(tmp_path, "close")) == 1
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["blocking"] == []
        assert sprint(repo, env, "land", "--dry-run").returncode == 0

    def test_the_closing_pass_reads_the_tree_the_fixer_LEFT(self, tmp_path):
        """Built at launch, not up front: a closer diffing the pre-fix tree is a
        pass over work nobody checked, and its report would look identical."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", "src.py", "THE_FIXERS_LINE = 1")],
        )
        assert sprint(repo, env, "review").returncode == 0
        bundle = bundles(tmp_path, "close")[0]
        assert "THE_FIXERS_LINE" in read_named_diff(bundle, "Cumulative sprint diff", repo, env)

    def test_clean_integration_skips_the_closing_pass(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        assert bundles(tmp_path, "close") == []


class TestTheAnglesAreShippedProse:
    """AC 7 and constraint 1: the angles are the only place the questions live,
    they are project-neutral by construction, and the library grows additively —
    a fourth angle is a file, not a mechanism."""

    def test_every_angle_is_neutral_about_the_project_reviewing_with_it(self):
        """Whether a security finding exists is the CONSUMING project's answer.
        The mechanical half is asserted; that the prose reads neutrally is
        read-and-judge, like every other prose rule here."""
        for path in ANGLES.glob("*.md"):
            text = path.read_text()
            for token in (".xp/", "xp-plugin", "close.py", "sprint_close", "work.md", "story-0"):
                assert token not in text, f"{path.name} names {token} — not a neutral angle"

    def test_the_shipped_angles_are_the_three_this_story_starts_with(self):
        assert angle_names() == ["security", "state-lifecycle", "test-vacuity"]

    def test_the_charter_carries_one_section_per_stage_and_no_more(self):
        """stage_charter slices these by name: a missing section launches an
        uninstructed agent whose report the pipeline records anyway."""
        body = (PLUGIN / "agents" / "sprint-reviewer.md").read_text().split("---", 2)[2]
        assert [ln[3:].strip() for ln in body.splitlines() if ln.startswith("## ")] == [
            "finder",
            "verifier",
            "fixer",
            "closer",
        ]

    def test_each_stage_section_is_a_page_not_a_charter(self):
        body = (PLUGIN / "agents" / "sprint-reviewer.md").read_text().split("---", 2)[2]
        for section in body.split("\n## ")[1:]:
            words = len(section.split())
            assert words <= 200, f"{section.splitlines()[0]}: {words} words"
