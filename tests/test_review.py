"""Sprint review finds, judges, fixes, then clears."""

import json
import shutil

from close_helpers import LEAD_CREDS, launches
from diff_reference_helpers import read_named_diff
from review_case_data import ANGLES, CANDIDATES, SURVIVES, angle_names
from review_install_cases import HarnessInstallCases
from review_tail_cases import (  # noqa: F401
    TestTheAnglesAreShippedProse,
    TestTheClosingPass,
    TestTheCommitGateRefusalIsActionable,
    TestTheGateIsNotHalfFixed,
)
from sprint_helpers import (
    CONFIG,
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


class TestHarnessInstallPreflight(HarnessInstallCases):
    pass


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


def test_runtime_names_use_only_their_owned_config_seats(tmp_path, monkeypatch, capsys):
    import review

    repo, env, _g = make_repo(
        tmp_path,
        config=(
            "roles:\n"
            "  reviewer: claude/reviewer-only\n"
            "  finder: claude/finder-only\n"
            "  slate-reviewer: claude/slate-only\n"
            "  card-refresher: claude/card-only\n"
        ),
    )
    monkeypatch.chdir(repo)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def selected(name, role="", card=""):
        review.run("prompt", repo, dry_run=True, name=name, role=role, card=card, checked=True)
        line = capsys.readouterr().out.splitlines()[0].split()
        return line[line.index("--model") + 1]

    assert [
        selected("story-reviewer"),
        selected("sprint fix"),
        selected("sprint find", role="finder"),
        selected("slate-reviewer", card="Slate-reviewer: claude/card-owned"),
        selected("card-refresher", card="Card-refresher: claude/card-owned"),
    ] == ["reviewer-only", "reviewer-only", "finder-only", "slate-only", "card-only"]


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
            assert "SPRINT-ONLY-SENTINEL" in read_named_diff(
                bundle, "Cumulative sprint diff", repo, env
            )

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

    def test_judgment_carries_the_bar_the_finder_quotes(self):
        """One rule, and the charter is the second place it is written: if
        JUDGMENT.md ever loses it, the finder's copy is a bar nobody else holds."""
        judgment = (PLUGIN / "JUDGMENT.md").read_text()
        assert "silent or corrupting" in judgment


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
                "schema": 2,
                "dropped": [],
                "debt": [],
            }
            for name in angle_names()
        }
        staged_stub(
            tmp_path,
            verify={
                "fixed": [],
                "blocking": [],
                "schema": 2,
                "dropped": [
                    {"finding": item, "reason": "fixture reason"} for item in ["all refuted"]
                ],
                "debt": [],
            },
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
            fix={
                "fixed": ["fixed the silent one"],
                "blocking": [],
                "schema": 2,
                "dropped": [],
                "debt": [],
            },
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

    def test_a_reviewer_that_leaves_the_tree_DIRTY_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')", report=CANDIDATES)
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["blocking"] == ["a silent one"]
        assert round_["stages"] == [f"find-{name}" for name in angle_names()]
        assert all(
            (tmp_path / "data/reports/sprint" / f"2.find-{name}.round-1.json").exists()
            for name in angle_names()
        )
        assert "reviewer changed HEAD" not in r.stderr
        assert "IS recorded" in round_["incomplete"] and "No round was" not in round_["incomplete"]

    def test_no_survivors_means_no_fixer_is_launched(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify={
                "fixed": [],
                "blocking": [],
                "schema": 2,
                "dropped": [{"finding": item, "reason": "fixture reason"} for item in ["x"]],
                "debt": [],
            },
        )
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
