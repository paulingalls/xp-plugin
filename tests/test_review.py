"""story-022: the sprint review finds, judges, fixes, then clears.

Sprint-003: one reviewer found 1 blocking + 8 noted; 28 agents found FOUR more, all
confirmed and silent, at 1.47M tokens. The shape buys N blind finders, BATCHED
verification, a fixer, and a blockers-only closing pass.
Verify: pytest -q tests/test_review.py
"""

import json
import re
import shutil
from pathlib import Path

from close_helpers import LEAD_CREDS, launches
from review_install_cases import HarnessInstallCases
from sprint_helpers import (
    CONFIG,
    PLAN,
    PLUGIN,
    bundles,
    committing_stub,
    head,
    make_repo,
    marker_path,
    sprint,
    stage_key,
    staged_stub,
)

ANGLES = PLUGIN / "scripts" / "angles"

CANDIDATES = {"fixed": [], "blocking": ["a silent one"], "noted": ["a loud one"]}

SURVIVES = {"fixed": [], "blocking": ["a silent one"], "noted": []}

# A refusing commit gate framed the way lefthook frames one: the cause is the LAST
# line, behind escape codes. Constructed, never observed.
LEFTHOOK = [
    "\\033[1m\\033[38;2;0;0;0m│ lefthook │\\033[0m",
    "summary: (done)",
    "\\033[31mformat: src.py would be reformatted\\033[0m",
]


class TestHarnessInstallPreflight(HarnessInstallCases):
    pass


def angle_names():
    return sorted(p.stem for p in ANGLES.glob("*.md"))


def test_bad_codex_sandbox_is_a_review_error_not_an_exception(tmp_path, monkeypatch):
    import review
    from close_helpers import make_repo as make_close_repo

    repo, env, _g = make_close_repo(tmp_path)
    (repo / ".xp" / "config.yml").write_text(
        "roles:\n  reviewer: codex/gpt-5.6-terra/high\ncodex_sandbox: broken\n"
    )
    monkeypatch.chdir(repo)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result, error = review.run("prompt", repo)
    assert result == ""
    assert "workspace-write" in error and "danger-full-access" in error


class TestTheFindersAreBlind:
    """AC 1. Each finder reads ONLY its own angle, over the WHOLE diff. The
    failure this guards is silent by construction: a finder whose angle never
    reached its bundle runs generalist, and a generalist pass looks exactly like
    a working one in every artifact the pipeline keeps."""

    def test_one_finder_per_angle_file_each_carrying_only_its_own(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        found = bundles(tmp_path, "find")
        assert len(found) == len(angle_names()) >= 3, "one blind finder per shipped angle"
        for name in angle_names():
            mine = [b for b in found if stage_key(b) == f"find-{name}"]
            assert len(mine) == 1, f"no finder carried {name}"
            body = (ANGLES / f"{name}.md").read_text().strip()
            assert body in mine[0], f"{name}'s angle never reached its finder"
            others = [n for n in angle_names() if n != name]
            for other in others:
                assert (ANGLES / f"{other}.md").read_text().strip() not in mine[0], (
                    f"{name}'s finder could see {other} — the finders are not blind"
                )

    def test_every_finder_gets_the_WHOLE_diff_not_a_slice(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        for bundle in bundles(tmp_path, "find"):
            assert "SPRINT-ONLY-SENTINEL" in bundle

    def test_an_unreadable_angle_refuses_before_anything_is_launched(self, tmp_path):
        """The fault injection AC 1 asks for: a mis-rendered angle path yields a
        generalist pass nothing downstream can distinguish. Injected against a
        COPY of the plugin, so the refusal is proven on the real reader rather
        than on a stub of it, and this repo's own angles are untouched."""
        repo, env, _g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        (plugin / "scripts" / "angles" / f"{angle_names()[0]}.md").write_text("\n")
        r = sprint(repo, env, "review", close=plugin / "scripts" / "close.py")
        assert r.returncode == 2, r.stdout
        assert angle_names()[0] in r.stderr, r.stderr
        assert bundles(tmp_path) == [], "spawned a finder over an angle it could not read"

    def test_a_missing_stage_SECTION_refuses_before_anything_is_launched(self, tmp_path):
        """The angle guard's twin, one file over, and hoisted for a worse reason:
        read at each stage's own launch, a missing `## closer` is discovered only
        after the finders, the verifiers and the fixer have spent — and after the
        fixer has committed, which `fail` alone names no undo for."""
        repo, env, _g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        agent = plugin / "agents" / "sprint-reviewer.md"
        agent.write_text(agent.read_text().split("\n## closer")[0] + "\n")
        r = sprint(repo, env, "review", close=plugin / "scripts" / "close.py")
        assert r.returncode == 2 and "closer" in r.stderr, r.stderr
        assert bundles(tmp_path) == [], "spent a finder before reading the closer's section"

    def test_an_empty_angles_directory_refuses(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        shutil.rmtree(plugin / "scripts" / "angles")
        r = sprint(repo, env, "review", close=plugin / "scripts" / "close.py")
        assert r.returncode == 2 and "angle" in r.stderr
        assert bundles(tmp_path) == []


class TestTheTwoBarsAreBothStated:
    """AC 2. Conflating CONFIDENCE with CONSEQUENCE is why the sprint-003 report
    was long: the angles never carried PROCESS.md's finding bar, and tightening
    confidence instead is the failure the verdict ladder names."""

    def test_the_finder_prompt_states_the_consequence_bar_and_a_generous_confidence(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        for bundle in bundles(tmp_path, "find"):
            charter = bundle[: bundle.index("## Your report")].lower()
            assert "silent" in charter and "corrupting" in charter, "no consequence bar"
            assert "loud and self-healing never" in charter, "the never half is missing"
            assert "plausible is the default" in charter, "confidence was tightened too"

    def test_process_still_carries_the_bar_the_finder_quotes(self):
        """One rule, and the charter is the second place it is written: if
        PROCESS.md ever loses it, the finder's copy is a bar nobody else holds."""
        process = (PLUGIN / "PROCESS.md").read_text()
        assert "silent or corrupting" in process


class TestVerificationIsBatched:
    """AC 3. Sprint-003 measured 22 refuter agents to kill 3 candidates — ~80% of
    1.47M tokens bought a 12% filter, because xp-agents runs one refuter per
    LOCATION and locations barely collide."""

    def _many_candidates(self, tmp_path, cap=None):
        """Nine DISTINCT candidates, three per angle: identical strings across
        angles would make a batcher that drops six look like one that partitions."""
        config = CONFIG if cap is None else CONFIG + f"review:\n  verify_batches: {cap}\n"
        repo, env, _g = make_repo(tmp_path, config=config)
        per_angle = {
            name.replace("-", "_"): {
                "fixed": [],
                "blocking": [f"{name} candidate {i}" for i in range(3)],
                "noted": [],
            }
            for name in angle_names()
        }
        staged_stub(
            tmp_path,
            verify={"fixed": [], "blocking": [], "noted": ["all refuted"]},
            **{f"find_{k}": v for k, v in per_angle.items()},
        )
        assert sprint(repo, env, "review").returncode == 0, "the pipeline did not complete"
        return bundles(tmp_path, "verify")

    def test_the_verifier_count_is_the_config_cap_not_the_candidate_count(self, tmp_path):
        """Three angles x three candidates = 9. One-per-candidate is the shape
        this AC exists to forbid, so the count is what is asserted."""
        verifiers = self._many_candidates(tmp_path, cap=2)
        assert len(verifiers) == 2, f"{len(verifiers)} verifiers for 9 candidates"

    def test_every_candidate_reaches_exactly_one_verifier(self, tmp_path):
        """A cap alone greens against a leg that launches two verifiers and hands
        them nothing: the batches must PARTITION the candidates."""
        verifiers = self._many_candidates(tmp_path, cap=2)
        wanted = [f"{name} candidate {i}" for name in angle_names() for i in range(3)]
        judged = [c for c in wanted for b in verifiers if c in b]
        assert sorted(judged) == sorted(wanted), f"9 candidates, {len(judged)} judged"

    def test_the_cap_is_read_from_config_not_hardcoded(self, tmp_path):
        assert len(self._many_candidates(tmp_path, cap=3)) == 3

    def test_a_cap_that_is_not_a_positive_integer_refuses(self, tmp_path):
        """It bounds spend inside the release gate; a typo silently falling back
        to the default is a number the lead believes they set."""
        repo, env, _g = make_repo(tmp_path, config=CONFIG + "review:\n  verify_batches: two\n")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "verify_batches" in r.stderr
        assert "Traceback" not in r.stderr, r.stderr

    def test_no_candidates_means_no_verifiers_at_all(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path)  # every stage clean
        assert sprint(repo, env, "review").returncode == 0
        assert bundles(tmp_path, "verify") == [], "spawned a verifier with nothing to judge"

    def test_only_the_bar_passing_bucket_reaches_a_verifier(self, tmp_path):
        """The bar is asserted in the PROMPT above; here it has to bite. Both
        buckets fed forward is the conflation this story exists to fix — a finder
        that dutifully sorts a loud finding into `noted` sees it verified, fixed
        and, unfixable, blocking the release the bar says it never earns."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path, find=CANDIDATES)
        assert sprint(repo, env, "review").returncode == 0
        judged = "\n".join(bundles(tmp_path, "verify"))
        assert "a silent one" in judged, "the bar-passing candidate never reached a verifier"
        assert "a loud one" not in judged, "a `noted` finding was carried forward anyway"


class TestTheFixerFixes:
    """AC 4. Measured at sprint-002: a REPORTING reviewer took 4 rounds and 11
    blocking findings and never converged; a FIXING one took 1 round, 7 fixed,
    0 blocking. This reverses story-014's report-only sprint leg deliberately."""

    def test_a_fixer_that_commits_is_recorded_not_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        before = head(repo, env)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            fix={"fixed": ["fixed the silent one"], "blocking": [], "noted": []},
            patches=[("fix", "src.py", "FIX")],
        )
        r = sprint(repo, {**env, **LEAD_CREDS}, "review")
        assert r.returncode == 0, r.stdout + r.stderr
        assert head(repo, env) != before, "the fixer's commit is not in the tree"
        state = json.loads(marker_path(tmp_path).read_text())
        assert state["rounds"][-1]["fixed"] == ["fixed the silent one"]
        assert state["shown_sha"] == head(repo, env), "the round names a tree nobody reviewed"
        for launch in launches(tmp_path):
            assert not [k for k in launch["env"] if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]

    def test_a_STAGE_THAT_COMMITS_AT_ALL_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(
            tmp_path,
            "os.system('echo X >> src.py && git commit -qam snuck"
            ' --author="someone else <e@x>"\')',
        )
        r = sprint(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert "read-only reviewer changed HEAD" in r.stderr, r.stderr
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_a_fixer_patch_touching_an_UNDECLARED_xp_file_is_refused(self, tmp_path):
        """The `.xp/` scope moved from the committed range to patch apply, and the
        sprint arm passes the whole sprint's cards where the story arm passes one.
        Only the story arm had a negative test, so this call site's refusal was
        carried by nothing (constraint 2)."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/constraints.md", "sneaky")],
        )
        r = sprint(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert ".xp/constraints.md" in r.stderr and "Files line" in r.stderr, r.stderr
        assert "sneaky" not in (repo / ".xp" / "constraints.md").read_text()
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_a_reviewer_that_leaves_the_tree_DIRTY_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')", report=CANDIDATES)
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["blocking"] == ["a silent one"] and round_["stages"] == ["find-security"]
        assert "IS recorded" in round_["incomplete"] and "No round was" not in round_["incomplete"]

    def test_no_survivors_means_no_fixer_is_launched(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path, find=CANDIDATES, verify={"fixed": [], "blocking": [], "noted": ["x"]})
        assert sprint(repo, env, "review").returncode == 0
        assert bundles(tmp_path, "fix") == [], "spawned a fixer with nothing to fix"

    def test_the_fixers_diff_is_written_where_the_lead_can_read_it(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", "src.py", "FIX")],
        )
        r = sprint(repo, env, "review")
        assert r.returncode == 0, r.stderr
        diff = tmp_path / "data" / "reports" / "sprint" / "2.fix.round-1.diff"
        assert str(diff) in r.stdout and "FIX" in diff.read_text()

    def test_LAND_shows_the_lead_the_commits_it_is_merging(self, tmp_path):
        """Assent is given by RUNNING land, and SKILL.md says so — but the review
        leg's stdout is long gone by then, and `reviewed_head` was written into the
        marker with no reader at all. The story leg re-prints the range here; this
        one printed nothing, so a reviewer's fixes merged unseen."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", "src.py", "FIXED_BY_THE_REVIEWER = 1")],
        )
        assert sprint(repo, env, "review").returncode == 0
        land = sprint(repo, env, "land")  # not --dry-run: a preview runs nothing
        assert "you are merging its work" in land.stdout, land.stdout
        assert "fix" in land.stdout and "full diff:" in land.stdout, land.stdout

    def test_LAND_names_a_GATE_file_the_fixer_rewrote(self, tmp_path):
        """The scope rule lets the fixer edit any `.xp/` path a sprint card's Files
        line declares, and a card DOES declare `.xp/system.md`, whose `Worktree
        bootstrap:` line spawn shell-executes. shown_sha is recorded AFTER the
        fixer, so land's own GATE_FILES check compares an empty range and never
        sees it. Loud is the least this can be."""
        plan = PLAN.replace(
            "#### story-042 — done thing   [done]",
            "#### story-042 — done thing   [done]\nFiles: src.py, .xp/system.md",
        )
        repo, env, _g = make_repo(tmp_path, plan=plan)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/system.md", "boot: x")],
        )
        assert sprint(repo, env, "review").returncode == 0
        land = sprint(repo, env, "land")
        assert "gate file" in land.stdout and ".xp/system.md" in land.stdout, land.stdout


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
            fix={"fixed": ["a fix the gate rejects"], "blocking": [], "noted": []},
            patches=[("fix", "src.py", "FIX")],
        )
        r = sprint(repo, {**env, **LEAD_CREDS}, "review")
        assert r.returncode == 2, r.stdout + r.stderr
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["fixed"] == ["a fix the gate rejects"] and round_["stages"][-1] == "fix"
        assert round_["blocking"] == ["a silent one"], "one finding, once per stage that saw it"
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and "incomplete" in land.stderr
        return repo, env, _g, r.stdout + r.stderr

    def test_the_refusal_names_the_gate_and_the_humans_next_action(self, tmp_path):
        *_context, out = self.refusal(tmp_path, LEFTHOOK)
        assert "commit gate refused" in out, out
        assert "commit the staged tree yourself" in out, "no next action for the human"
        assert "would be reformatted" in out, "the cause the gate named is not in the refusal"
        assert "\x1b[" not in out, "ANSI escapes survived into the refusal"

    def test_the_patch_survives_the_undo_offered_directly_below_the_refusal(self, tmp_path):
        """abort_text appends `git reset --hard`, which discards the staged patch
        the sentence above it says to commit. The two read as opposite orders
        unless the refusal names a copy of the patch that the reset cannot reach."""
        *_context, out = self.refusal(tmp_path, LEFTHOOK)
        m = re.search(r"the patch is also at (\S+?),", out)
        assert m, f"the refusal offers an undo but names no surviving patch:\n{out}"
        assert "FIX" in Path(m.group(1)).read_text(), "the named patch is not the fixer's"

    def test_a_truncated_transcript_says_it_was_truncated(self, tmp_path):
        """A bounded tail can cut the cause off the top — the same "reason twelve
        lines up" this refusal exists to end, re-created inside it. Say the count."""
        gate = ["CAUSE-ABOVE-THE-CUT"] + [f"noise {n}" for n in range(14)]
        *_context, out = self.refusal(tmp_path, gate)
        assert "CAUSE-ABOVE-THE-CUT" not in out, "the fixture no longer truncates"
        assert "last 12 of 15 lines" in out, f"the refusal hid its own truncation:\n{out}"

    def test_the_humans_commit_is_followed_by_round_two_without_erasing_round_one(self, tmp_path):
        repo, env, g, _out = self.refusal(tmp_path, LEFTHOOK)
        (repo / ".git" / "hooks" / "pre-commit").unlink()
        assert g("commit", "-qm", "human accepts fixer patch").returncode == 0
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
        assert len(rounds) == 2 and rounds[0]["incomplete"] and "incomplete" not in rounds[1]
        assert (tmp_path / "data/reports/sprint/2.fix.round-1.json").exists()


class TestTheGateIsNotHalfFixed:
    def test_a_reviewer_that_rewrites_the_MARKER_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [], "shown_sha": "x"}))
        erased = json.dumps(
            {"rounds": [{"fixed": [], "blocking": [], "noted": []}], "shown_sha": "y"}
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
            fix={"fixed": ["fixed it"], "blocking": [], "noted": []},
            close={"fixed": [], "blocking": ["THE-FIX-BROKE-IT"], "noted": []},
        )
        assert sprint(repo, env, "review").returncode == 0
        land = sprint(repo, env, "land", "--dry-run")
        assert land.returncode == 2 and "THE-FIX-BROKE-IT" in land.stderr

    def test_a_clean_closing_pass_lets_the_release_proceed(self, tmp_path):
        """The green twin: without it, an always-blocking closer passes the test
        above and nothing ever releases."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
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
        assert "THE_FIXERS_LINE" in bundles(tmp_path, "close")[0]

    def test_the_closing_pass_runs_even_when_nothing_was_fixed(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        assert len(bundles(tmp_path, "close")) == 1


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
