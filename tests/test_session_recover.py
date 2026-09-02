"""What session recovery says when state is empty or names the next loop action.

Its own file because test_session_start.py sits AT constraint 8's 500-line cap:
extract, not scroll. Verify: pytest -q tests/test_session_recover.py"""

import json
import subprocess
import sys

import pytest
from session_start_helpers import HOOK, run_hook_as, run_recovery, xp_repo


def next_lines(output):
    return [line for line in output.splitlines() if line.startswith("NEXT:")]


class TestTheNextLoopAction:
    @pytest.mark.parametrize(
        ("status", "handoff", "expected"),
        [
            ("done", "ABSENT", "NEXT: no open card in Sprint 1 — run `/sprint-close`"),
            (
                "planned",
                "ABSENT",
                "NEXT: story-042 is [planned] — run `spawn.py ready story-042`",
            ),
            ("ready", "ABSENT", "NEXT: story-042 is [ready] — run `spawn.py story-042`"),
            (
                "in-progress",
                "ABSENT",
                "NEXT: story-042 is [in-progress] without a worktree — recover it before resuming",
            ),
            (
                "in-progress",
                "STOPPED",
                "NEXT: story-042 has a STOPPED worktree — run `spawn.py resume story-042`",
            ),
            (
                "in-progress",
                "FINISHED",
                "NEXT: story-042 has a FINISHED worktree — run `/story-close`",
            ),
        ],
    )
    def test_each_reachable_pair_names_exactly_one_action(
        self, tmp_path, status, handoff, expected
    ):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        if handoff != "ABSENT":
            (root / "worktrees" / "story-042").mkdir(parents=True)
            plans = root / "plans"
            plans.mkdir()
            (plans / "story-042.handoff.json").write_text(json.dumps({"state": handoff}))

        out = run_hook_as(repo, tmp_path, role="lead").stdout

        assert next_lines(out) == [expected]

    def test_a_failed_card_review_precedes_the_planned_card_boundary(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [planned]\nVerify: true\n"
        )
        marker = root / "markers" / "1.card-review-incomplete"
        marker.parent.mkdir()
        marker.write_text("{}")

        incomplete = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)
        marker.unlink()
        unreviewed = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert incomplete == [
            "NEXT: Sprint 1 card review did not complete — run `card_review.py 1`"
        ]
        assert unreviewed == ["NEXT: story-042 is [planned] — run `spawn.py ready story-042`"]

    def test_a_plan_story_id_cannot_append_a_shell_command(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        sentinel = tmp_path / "command-ran"
        story = f"story-042;touch${{IFS}}{sentinel}"
        (root / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### {story} — demo   [planned]\nVerify: true\n"
        )
        binary = tmp_path / "bin" / "spawn.py"
        binary.parent.mkdir()
        binary.write_text("#!/bin/sh\nexit 7\n")
        binary.chmod(0o755)

        output = run_hook_as(repo, tmp_path, role="lead").stdout
        line = next_lines(output)[0]
        command = line.split("`", 2)[1]
        ran = subprocess.run(
            ["/bin/sh", "-c", command], env={"PATH": f"{binary.parent}:/usr/bin:/bin"}
        )
        fenced = output.split("BEGIN project content", 1)[1].split("END project content", 1)[0]

        assert ran.returncode == 7 and not sentinel.exists()
        assert line in fenced

    @pytest.mark.parametrize("status", ["planned", "ready"])
    def test_a_worktree_on_the_wrong_side_of_spawn_names_recovery(self, tmp_path, status):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        (root / "worktrees" / "story-042").mkdir(parents=True)

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == [
            f"NEXT: recovery required — story-042 is [{status}] with worktree state ABSENT"
        ]

    def test_running_is_not_inferred_to_be_resumable(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [in-progress]\n"
        )
        (root / "worktrees" / "story-042").mkdir(parents=True)
        plans = root / "plans"
        plans.mkdir()
        (plans / "story-042.handoff.json").write_text('{"state": "RUNNING"}')

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == [
            "NEXT: recovery required — story-042 is [in-progress] with worktree state RUNNING"
        ]

    def test_carried_pool_cards_are_not_the_current_sprints_next_action(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — done   [done]\n"
            "### The pool — carried, not scheduled\n"
            "#### story-099 — later   [planned]\n"
        )

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: no open card in Sprint 1 — run `/sprint-close`"]

    def test_parallel_in_progress_cards_name_the_uncovered_state(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n"
            "#### story-041 — first   [in-progress]\n"
            "#### story-042 — second   [in-progress]\n"
        )

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: recovery required — multiple [in-progress] cards in Sprint 1"]

    @pytest.mark.parametrize(
        ("cards", "expected"),
        [
            (
                "#### story-042 — demo   [ready] trailing\n",
                "NEXT: recovery required — malformed card headings in Sprint 1",
            ),
            (
                "#### story-042 — first   [ready]\n#### story-042 — second   [planned]\n",
                "NEXT: recovery required — malformed card headings in Sprint 1",
            ),
            (
                "#### story-042 — demo   [queued]\n",
                "NEXT: recovery required — story-042 has unknown status [queued]",
            ),
        ],
    )
    def test_malformed_card_state_names_recovery(self, tmp_path, cards, expected):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(f"# plan\n### Sprint 1\n{cards}")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == [expected]

    @pytest.mark.parametrize(
        ("tree_kind", "marker", "expected_state"),
        [
            ("file", None, "INVALID"),
            ("directory", "{", "UNREADABLE"),
            ("directory", "[]", "UNREADABLE"),  # valid JSON, wrong SHAPE — `.get` would raise
            ("directory", '{"state": "PAUSED"}', "INVALID"),
            ("directory", None, "ABSENT"),
            ("absent", '{"state": "STOPPED"}', "ORPHANED-STOPPED"),
            ("absent", "{", "ORPHANED-UNREADABLE"),
            ("absent", '{"state": "PAUSED"}', "ORPHANED-INVALID"),
        ],
    )
    def test_uncovered_worktree_state_names_recovery(
        self, tmp_path, tree_kind, marker, expected_state
    ):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [in-progress]\n"
        )
        tree = root / "worktrees" / "story-042"
        tree.parent.mkdir(parents=True, exist_ok=True)
        if tree_kind == "file":
            tree.write_text("")
        elif tree_kind == "directory":
            tree.mkdir()
        if marker is not None:
            plans = root / "plans"
            plans.mkdir(exist_ok=True)
            (plans / "story-042.handoff.json").write_text(marker)

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == [
            "NEXT: recovery required — story-042 is [in-progress]"
            f" with worktree state {expected_state}"
        ]

    def test_no_open_card_with_a_leftover_tree_is_not_called_sprint_done(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — done   [done]\n")
        (root / "worktrees" / "story-042").mkdir(parents=True)
        plans = root / "plans"
        plans.mkdir()
        (plans / "story-042.handoff.json").write_text('{"state": "FINISHED"}')

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: recovery required — story-042 remains after close: FINISHED"]

    def test_a_closed_cards_surviving_marker_does_not_veto_sprint_close(self, tmp_path):
        """The marker is DURABLE: close removes the tree and the branch, never
        `plans/<story>.handoff.json`, because a later resume inherits from it. Reading it
        as leftover work made the sprint-close row above unreachable on any repo that has
        ever closed a story — measured against this repo's own root, 24 markers deep."""
        repo, _g = xp_repo(tmp_path)
        root = tmp_path / "xp"
        (root / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — done   [done]\n")
        plans = root / "plans"
        plans.mkdir(parents=True)
        (plans / "story-042.handoff.json").write_text('{"state": "FINISHED", "records": []}')

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: no open card in Sprint 1 — run `/sprint-close`"]

    @pytest.mark.parametrize("plan_state", ["missing", "directory"])
    def test_a_broken_plan_names_plan_recovery(self, tmp_path, plan_state):
        repo, _g = xp_repo(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.unlink()
        if plan_state == "directory":
            plan.mkdir()

        result = run_hook_as(repo, tmp_path, role="lead")
        lines = next_lines(result.stdout)

        assert result.returncode == 0 and len(lines) == 1
        assert lines[0].startswith(f"NEXT: recover plan at {plan} — ")
        assert "Traceback" not in result.stderr

    def test_a_plan_without_a_numbered_sprint_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text("# plan\n#### story-042 — demo   [ready]\n")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == [f"NEXT: recovery required — no numbered sprint in {plan}"]

    def test_an_unforeseen_failure_degrades_rather_than_tracebacking(self, monkeypatch):
        """The catch-all BENEATH the OSError handlers the tests above drive. No plan or
        marker on disk reaches it — `Path.exists()` swallows OSError — so raising from the
        one call outside the inner `try` is the only thing that can prove it not vacuous."""
        sys.path.insert(0, str(HOOK.parent))
        import session_start

        def explode():
            raise ValueError("boom")

        monkeypatch.setattr(session_start, "plan_path", explode)

        assert session_start.next_action() == (
            "NEXT: recovery required — next-action state is unreadable: boom"
        )


class TestARegionThatProducedNothing:
    """`recover` builds every region as `("<name>", "## <name>\n" + body)`, so the
    HEADING is always truthy: render's `if text` filter can never drop a region and
    the notice — which lists only regions the cut reached — never names one either.
    A region that produced nothing must therefore say so itself."""

    def test_a_dead_builder_names_its_cause_instead_of_a_bare_heading(self, tmp_path):
        """Fault-injected exactly as measured: plan.md replaced by a DIRECTORY.
        Before, `recover` printed bare `## recovery block` and `## sprint slice`
        headings with no notice and exit 0 — the lead reads that as "nothing open"."""
        repo, _g = xp_repo(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.unlink()
        plan.mkdir()
        r = run_recovery(repo, tmp_path)
        assert r.returncode == 0, r.stderr
        for region in ("recovery block", "sprint slice"):
            assert f"## {region}\n({region} UNAVAILABLE" in r.stdout, r.stdout
        assert str(plan) in r.stdout, "the cause is what the lead repairs"

    def test_an_empty_region_says_which_nothing_it_has(self, tmp_path):
        """Distinct states stay distinct: a plan carrying no `### Sprint` section is
        not a plan whose read blew up, and neither is a bare heading."""
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text("# plan with no sprint sections\n")
        r = run_recovery(repo, tmp_path)
        assert "## sprint slice\n(sprint slice: nothing recorded)" in r.stdout, r.stdout
        assert "UNAVAILABLE" not in r.stdout, "an empty region read as a failed one"
