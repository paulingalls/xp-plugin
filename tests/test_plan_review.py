"""Plan review as a headless ROLE, not a harness subagent (story-026).
Verify: pytest -q tests/test_plan_review.py"""

import json
import re
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest
from spawn_helpers import make_repo, spawn, stub_claude, stub_codex
from test_spawn_escalation import ESCALATION, stub_escalating

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"
PLAN_REVIEW = PLUGIN / "scripts" / "plan_review.py"
# A charter-body phrase, so a bundle with an empty charter cannot pass for a real one.
CHARTER_MARK = "Checks, in order of payoff"
CLEAN = '{"status":"clean","reasons":[]}'

CONFIG = """release: sprint
roles:
  executor: claude/opus
  reviewer: codex/gpt-5.6-terra/high
  plan-reviewer: {spec}

tests:
  story: true
"""


def test_the_charter_disposition_examples_are_accepted_by_the_parser():
    from plan_review import evaluate_disposition

    charter = (PLUGIN / "agents" / "plan-reviewer.md").read_text()
    output = charter.split("## Output", 1)[1]
    examples = re.findall(r"(```json\n(.*?)```)", output, flags=re.S)
    assert len(examples) == 3
    assert [json.loads(body)["status"] for _fence, body in examples] == [
        "clean",
        "edited",
        "blocked",
    ]
    changed = b"# plan\n\nReason: exact reason text present in the plan\n"
    evaluations = [
        evaluate_disposition(examples[0][0], b"# plan\n", b"# plan\n"),
        evaluate_disposition(examples[1][0], b"# plan\n", changed),
        evaluate_disposition(examples[2][0], b"# plan\n", b"# plan\n"),
    ]
    assert [outcome for outcome, _problem in evaluations] == ["ran", "ran", "blocked"]
    outside_fences = re.sub(r"```json\n.*?```", "", output, flags=re.S)
    assert not re.search(r'\{[^{}]*"status"', outside_fences)
    assert ".round-1.md" in charter
    assert "legacy logical round one" in charter


def stub_planner(tmp_path, findings=CLEAN, write_findings=True, motion=""):
    """A fake `claude` that REFUSES a prompt carrying no charter.

    A leg that lost the rubric could still exit 0 with plausible prose and findings.
    Nothing downstream can tell that apart, so its detector belongs at the binary.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']: print("
        '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "stdin = sys.stdin.read()\n"
        "json.dump({'argv': sys.argv[1:], 'env': dict(os.environ), 'stdin': stdin},"
        f" open({str(rec)!r}, 'w'))\n"
        f"if {CHARTER_MARK!r} not in stdin:\n"
        "    print('error: the prompt carries no charter', file=sys.stderr)\n"
        "    sys.exit(2)\n"
        "m = re.search(r'^FINDINGS_PATH: (.+)$', stdin, re.M)\n"
        "assert m, 'the bundle named no FINDINGS_PATH'\n"
        "plan = re.search(r'^PLAN_PATH: (.+)$', stdin, re.M)\n"
        f"write_findings = {write_findings!r}\n"
        f"motion = {motion!r}\n"
        f"open(m.group(1).strip(), 'w').write({findings!r}) if write_findings else None\n"
        "if motion in ('dirty', 'commit'):\n"
        "    open('drift.txt', 'a').write('reviewer motion\\n')\n"
        "if motion == 'draft':\n"
        f"    open({str(tmp_path / 'draft.md')!r}, 'a').write('reviewer motion\\n')\n"
        "if motion in ('edit', 'edit-no-reason'):\n"
        "    assert plan, 'the bundle named no PLAN_PATH'\n"
        "    why = '\\nReason: the guard needs an executable acceptance check.\\n'"
        " if motion == 'edit' else '\\nchanged without explanation\\n'\n"
        "    open(plan.group(1).strip(), 'a').write(why)\n"
        "if motion == 'unreadable':\n"
        "    import pathlib\n"
        "    target = pathlib.Path(plan.group(1).strip())\n"
        "    target.unlink(); target.mkdir()\n"
        "if motion == 'card':\n"
        f"    open({str(tmp_path / 'data' / 'plan.md')!r}, 'a').write('reviewer motion\\n')\n"
        "if motion == 'own':\n"
        f"    _p = open({str(tmp_path / 'data' / 'plan.md')!r})\n"
        "    _t = _p.read(); _p.close()\n"
        f"    open({str(tmp_path / 'data' / 'plan.md')!r}, 'w').write(\n"
        "        _t.replace('OWN-CONTEXT', 'the review rewrote the card it is judged against'))\n"
        "if motion == 'sibling':\n"
        f"    _p = open({str(tmp_path / 'data' / 'plan.md')!r})\n"
        "    _t = _p.read(); _p.close()\n"
        f"    open({str(tmp_path / 'data' / 'plan.md')!r}, 'w').write(\n"
        "        _t.replace('SIBLING-CONTEXT', 'a sibling lane flipped its own card'))\n"
        "if motion == 'commit':\n"
        "    import subprocess\n"
        "    subprocess.run(['git', 'add', '-A'], check=True)\n"
        "    subprocess.run(['git', 'commit', '-qm', 'plan reviewer motion'], check=True)\n"
        f"print(json.dumps({{'type': 'result', 'result': {findings!r}}}))\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return rec


def plan_review(repo, env, *args, script=PLAN_REVIEW):
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def test_plan_reviewer_role_is_bounded_too(tmp_path, monkeypatch):
    from spawn import run_agent

    monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.01")
    with pytest.raises(subprocess.TimeoutExpired):
        run_agent(
            ["/bin/sh", "-c", "sleep 1"],
            tmp_path,
            "",
            role="plan-reviewer",
            harness="claude",
            log_id="story-042-review",
        )


def test_a_respawn_inherits_the_stopped_teammates_artifacts_only(tmp_path):
    repo, env, g = make_repo(tmp_path)
    stub_escalating(tmp_path, artifacts=True)
    assert spawn(repo, env, "story-042").returncode == 3
    tree = Path(env["XP_DATA"]) / "worktrees/story-042"
    g("worktree", "remove", "--force", str(tree))
    g("branch", "-D", "ada/story-042-demo-story")
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
    rec = stub_claude(tmp_path)
    assert spawn(repo, env, "story-042").returncode == 0
    inherited = json.loads(rec.read_text())["stdin"]
    plans = Path(env["XP_DATA"]) / "plans"
    for mark in ("DRAFT-SENTINEL", "FINDING-ONE", "FINDING-TWO", ESCALATION):
        assert mark not in inherited
    assert f"plan draft\n\n{plans / 'story-042.plan.md'}" in inherited
    assert f"round 1 (legacy)\n\nRead {plans / 'story-042.md'}" in inherited
    assert f"round 2\n\nRead {plans / 'story-042.round-2.md'}" in inherited
    rid = json.loads((plans / "story-042.handoff.json").read_text())["records"][0]
    assert f"records\n\n{rid}. Read each with `work.py show <id>`" in inherited


TWO_CARDS = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [ready]
Context: OWN-CONTEXT
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: true

#### story-099 — the other lane   [in-progress]
Context: SIBLING-CONTEXT
Files: src/other.py
AC:
- Given A, When B, Then C
Verify: true
"""


class TestTheSharedPlanIsNotThisStorysGate:
    """Bug 5a1abadb, measured: it cost story-032 a whole run. plan.md is
    PROJECT-GLOBAL and the lead edits it constantly — status flips, re-mints,
    card edits — while parallel lanes review. close.review.check_reviewer_motion
    already scopes its card check to the story's OWN card for exactly this
    reason; plan_review never got that fix.
    """

    def repo(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        (Path(env["XP_DATA"]) / "plan.md").write_text(TWO_CARDS)
        draft = tmp_path / "draft.md"
        draft.write_text("PLAN-SENTINEL: two files, one red test, then the code.\n")
        return repo, env, draft

    def test_another_card_changing_mid_review_does_not_refuse_this_one(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path, motion="sibling")
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, (
            f"a sibling lane's card edit refused this story's review:\n{r.stderr}"
        )
        assert "changed the repository" not in r.stderr, r.stderr

    def test_this_storys_own_card_changing_still_refuses(self, tmp_path):
        """The guard is not weakened — only scoped. A review that rewrites the
        card it is being judged against is still the thing worth refusing."""
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path, motion="own")
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode != 0, "a review that edited its own card was accepted"
        assert "changed the repository" in r.stderr, r.stderr


class TestTheLaunch:
    def repo(self, tmp_path, spec="claude/haiku/low"):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec=spec))
        draft = tmp_path / "draft.md"
        draft.write_text("PLAN-SENTINEL: two files, one red test, then the code.\n")
        return repo, env, draft

    def test_the_charter_the_plan_and_the_card_reach_the_reviewer(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        launch = json.loads(rec.read_text())
        stdin, argv = launch["stdin"], launch["argv"]
        assert CHARTER_MARK in stdin  # the charter, inlined — codex has no --plugin-dir
        assert "PLAN-SENTINEL" in stdin
        assert "demo story" in stdin  # the card slice
        assert "CONSTRAINT-SENTINEL" in stdin
        assert argv[argv.index("--model") + 1] == "haiku"  # the plan-reviewer ROLE
        assert argv[argv.index("--effort") + 1] == "low"
        assert launch["env"]["XP_ROLE"] == "plan-reviewer"  # cannot close
        assert CLEAN in r.stdout  # returned, not only written

    def test_round_two_bundle_carries_round_one_findings(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        prior = "unique first-round plan finding\nwith its second line"
        rec = stub_planner(tmp_path, findings=prior + "\n```json\n" + CLEAN + "\n```")
        assert plan_review(repo, env, "story-042", str(draft)).returncode == 0
        rec.unlink()

        assert plan_review(repo, env, "story-042", str(draft)).returncode == 0
        prompt = json.loads(rec.read_text())["stdin"]
        assert prior in prompt
        assert "story-042.round-2.md" in prompt

    @pytest.mark.parametrize("verdict", ["RED", "GREEN"])
    def test_a_third_plan_round_is_refused_without_launching(self, tmp_path, verdict):
        repo, env, draft = self.repo(tmp_path)
        root = Path(env["XP_DATA"]) / "plans"
        root.mkdir(parents=True, exist_ok=True)
        (root / "story-042.round-1.md").write_text("first")
        (root / "story-042.round-2.md").write_text(f"second says {verdict}")
        rec = stub_planner(tmp_path)

        result = plan_review(repo, env, "story-042", str(draft))

        assert result.returncode == 2
        assert not rec.exists()
        assert not (root / "story-042.round-3.md").exists()

    def test_a_live_round_is_joined_rather_than_counted_against_the_cap(self, tmp_path):
        from test_slate_review_prose import orphan_pid

        repo, env, draft = self.repo(tmp_path)
        root = Path(env["XP_DATA"]) / "plans"
        root.mkdir(parents=True, exist_ok=True)
        (root / "story-042.round-1.md").write_text("first")
        live = root / "story-042.round-2.md"
        live.write_text("second, still being written")
        pid = orphan_pid()
        marker = Path(env["XP_DATA"]) / "markers" / "story-042.plan-review-incomplete"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"findings": str(live), "pid": pid}))
        rec = stub_planner(tmp_path)

        joined = plan_review(repo, env, "story-042", str(draft))

        assert f"joining the plan review already running (pid {pid})" in joined.stderr
        assert "already exist" not in joined.stderr
        assert not rec.exists() and not (root / "story-042.round-3.md").exists()

    def test_the_foreground_cap_is_not_a_failed_reviewer(self, tmp_path, monkeypatch):
        from plan_review import run_foreground

        repo, env, draft = self.repo(tmp_path)
        root = Path(env["XP_DATA"]) / "plans"
        root.mkdir(parents=True, exist_ok=True)
        (root / "story-042.round-1.md").write_text(CLEAN)
        (root / "story-042.round-2.md").write_text(CLEAN)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        monkeypatch.chdir(repo)

        assert run_foreground("story-042", draft) == (2, "capped")

    def test_dead_reviewers_do_not_satisfy_the_two_round_cap(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        malformed = '```json\n{"status":\n```'
        rec = stub_planner(tmp_path, findings=malformed)
        for _attempt in range(2):
            assert plan_review(repo, env, "story-042", str(draft)).returncode == 2
        root = Path(env["XP_DATA"]) / "plans"
        assert not (root / "story-042.round-1.md").exists()
        assert len(list(root.glob("story-042.round-1.failed-*.md"))) == 2

        stub_planner(tmp_path)
        assert plan_review(repo, env, "story-042", str(draft)).returncode == 0
        assert rec.exists() and (root / "story-042.round-1.md").is_file()

    def test_an_empty_charter_ships_NOTHING(self, tmp_path):
        """The AC's fault injection, CONSTRUCTED rather than mocked: truncate the
        charter in a COPY of the plugin tree and run that copy's script. A missing
        file already refuses through _read_shipped; an empty one is what would
        otherwise ship a bundle with a hollow rubric and no sign of it."""
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        tree = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, tree)
        (tree / "agents" / "plan-reviewer.md").write_text("---\nname: plan-reviewer\n---\n")
        r = plan_review(
            repo, env, "story-042", str(draft), script=tree / "scripts" / "plan_review.py"
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert "Traceback" not in r.stderr, r.stderr
        assert "charter" in r.stderr.lower(), r.stderr
        assert not rec.exists(), "spent a review on an empty rubric"

    @pytest.mark.slow
    def test_plan_editing_role_refuses_every_other_guarded_motion(self, tmp_path):
        for motion in ("dirty", "commit", "card"):
            repo, env, draft = self.repo(tmp_path / motion)
            stub_planner(tmp_path / motion, motion=motion)
            before = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout.strip()
            r = plan_review(repo, env, "story-042", str(draft))
            assert r.returncode == 2 and "changed" in r.stderr.lower(), r.stderr
            if motion == "commit":
                after = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    env=env,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                assert after != before, "the committed-motion injection never happened"

    def test_a_missing_plan_file_refuses_without_launching(self, tmp_path):
        repo, env, _draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(tmp_path / "nope.md"))
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
        assert not rec.exists()

    def test_an_empty_plan_refuses_without_launching(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        draft.write_text("")
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 2 and "empty" in r.stderr.lower(), r.stderr
        assert not rec.exists()

    def test_a_missing_story_card_refuses_without_launching(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-nope", str(draft))
        assert r.returncode == 2 and "card" in r.stderr.lower(), r.stderr
        assert not rec.exists()

    def test_dry_run_launches_nothing_and_prints_the_argv(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft), "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "--model haiku" in r.stdout and CHARTER_MARK in r.stdout
        assert not rec.exists()
        assert not (tmp_path / "data" / "plans").exists()

    def test_a_codex_plan_reviewer_launches_under_the_shipped_posture(self, tmp_path):
        """The third codex leg, and the one no other test launches. It nests
        nothing, which is exactly why it used to be the leg the network flag was
        withheld from — a distinction the shipped posture dissolves."""
        repo, env, draft = self.repo(tmp_path, spec="codex/gpt-5.6-terra/high")
        rec = stub_codex(tmp_path, commit=False, sandbox="danger-full-access", findings=CLEAN)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        assert ("--sandbox", "danger-full-access") in list(pairwise(argv)), argv
        assert ("--disable", "unified_exec") not in list(pairwise(argv)), argv
        assert argv[argv.index("-m") + 1] == "gpt-5.6-terra"
        assert CHARTER_MARK in json.loads(rec.read_text())["stdin"]
        assert CLEAN in r.stdout


class TestTheProfileCarriesTheInvocation:
    """story-102 INVERTED this class's AC2. The profile used to carry the review's
    invocation, and a teammate that ran it had to wait on a detached child across a
    turn boundary — which it cannot, so two of three field-reported multi-file runs
    lost their work inventing `sleep 90`. Spawn now runs that review as its own
    stage, so what the profile must carry is the reviewed plan's path and NO
    command. Kept for both harnesses because a codex teammate has no --plugin-dir:
    whatever is not in the profile does not reach it at all."""

    def rendered(self, tmp_path, executor):
        root = tmp_path / executor.split("/")[0]
        repo, env, _g = make_repo(root, executor=executor)
        (stub_claude if executor.startswith("claude") else stub_codex)(root)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        return r.stdout

    def test_neither_harness_is_handed_a_review_to_launch(self, tmp_path):
        for executor in ("claude/opus", "codex/gpt-5.6-terra/high"):
            profile = self.rendered(tmp_path, executor)
            draft = tmp_path / executor.split("/")[0] / "data/plans/story-042.plan.md"
            assert str(PLAN_REVIEW) not in profile, profile
            assert str(draft) in profile, profile

    def test_the_launched_plan_path_survives_worktree_removal(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        prompt = json.loads(rec.read_text())["stdin"]
        draft = Path(env["XP_DATA"]) / "plans/story-042.plan.md"
        assert str(draft) in prompt
        tree = Path(env["XP_DATA"]) / "worktrees" / "story-042"
        assert not draft.is_relative_to(tree)
        # spawn must MAKE it: the planner writes before plan_review.py, and a shell
        # redirect into a missing directory sends it back to the worktree.
        assert draft.parent.is_dir(), draft
        draft.write_text("SURVIVES-UNWIND\n")
        assert g("worktree", "remove", "--force", str(tree)).returncode == 0
        assert draft.read_text() == "SURVIVES-UNWIND\n"


from plan_review_disposition import TestPlanEditsInPlace  # noqa: E402,F401
from plan_review_liveness import TestTheReviewOutlivesItsCaller  # noqa: E402,F401


def test_blocked_plan_reviews_converge_on_the_cap_instead_of_restarting(tmp_path):
    """A block replans, but a replanned block is round 2 — not round 1 again."""
    from test_spawn_stages import stub_stages

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    stub_stages(tmp_path, blocking_plan=True)
    plans = Path(env["XP_DATA"]) / "plans"
    assert spawn(repo, env, "story-042").returncode == 2
    (plans / "story-042.round-1.md").write_text("BLOCKED-ON-THE-FIRST-PLAN")

    second = spawn(repo, env, "resume", "story-042")

    assert second.returncode == 2
    assert (plans / "story-042.round-2.md").is_file()
    launched = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert "BLOCKED-ON-THE-FIRST-PLAN" in launched[-1]["prompt"]
    third = spawn(repo, env, "resume", "story-042")
    assert third.returncode == 2 and "cap" in third.stderr
    assert not (plans / "story-042.round-3.md").exists()


def test_a_replanned_executor_is_handed_the_replacement_rounds_not_the_archived_ones(tmp_path):
    """The prompt built before the planner names round files the archive has since renamed
    away, and rebuilding it off the live marker would label this very run the predecessor.
    (Here rather than beside its sibling: test_spawn.py sits at constraint 8's hard cap.)"""
    from test_spawn_stages import event_roles, stub_stages

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = stub_stages(tmp_path, blocking_diff=True)
    assert spawn(repo, env, "story-042").returncode != 0
    plans = Path(env["XP_DATA"]) / "plans"
    (plans / "story-042.round-2.md").write_text("OLD-FINDING")
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text().replace("Then Z", "Then amended Z"))
    assert spawn(repo, env, "amend", "story-042", "--reason", "acceptance changed").returncode == 0
    seen = len(event_roles(events))
    stub_stages(tmp_path, blocking_diff=True)
    assert spawn(repo, env, "resume", "story-042").returncode != 0

    teammate = [json.loads(line) for line in events.read_text().splitlines()[seen:]][2]["prompt"]

    assert "story-042.round-1.md" in teammate
    assert "story-042.round-2.md" not in teammate
    assert "handback — RUNNING" not in teammate
