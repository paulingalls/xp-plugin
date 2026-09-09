import json
import shlex
import sys

from sprint_helpers import PLAN, make_repo, sprint


class SprintMembershipCases:
    def test_lifecycle_runs_only_for_the_opening_and_before_the_branch_record(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record = tmp_path / "opened.jsonl"
        script = tmp_path / "open.py"
        script.write_text(
            "import json, os, pathlib, sys\n"
            "branch = pathlib.Path(os.environ['XP_DATA'], 'sprint_branch')\n"
            f"p = pathlib.Path({str(record)!r})\n"
            "with p.open('a') as f: f.write(json.dumps([sys.argv[1:], branch.exists()])+'\\n')\n"
            "raise SystemExit(int(p.with_suffix('.exit').read_text()) "
            "if p.with_suffix('.exit').exists() else 0)\n"
        )
        command = shlex.join([sys.executable, str(script), "fixed value"])
        config = repo / ".xp" / "config.yml"
        config.write_text(f"lifecycle_command: {command}\n" + config.read_text())
        g("add", "-A")
        g("commit", "-qm", "configure lifecycle")
        branch = tmp_path / "data" / "sprint_branch"
        branch.unlink()

        opened = sprint(repo, env, "start")
        assert opened.returncode == 0, opened.stderr
        assert [json.loads(line) for line in record.read_text().splitlines()] == [
            [["fixed value", "sprint-open", "2"], False]
        ]
        assert branch.exists()
        assert sprint(repo, env, "start").returncode == 0
        assert len(record.read_text().splitlines()) == 1, "the close-time re-run reopened it"

        branch.unlink()
        record.with_suffix(".exit").write_text("1")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]", 1))
        refused = sprint(repo, env, "start")
        assert refused.returncode == 2 and "sprint-open" in refused.stderr
        assert command.split()[0] in refused.stderr and not branch.exists()
        assert "[planned]" in plan.read_text()

    def test_other_sprints_do_not_block_this_one(self, tmp_path):
        """The naive reading — no story in plan.md is non-done — refuses forever,
        because Sprint 3 is [ready] right now and always will be."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "story-099" not in r.stdout
        assert "milestone" not in r.stdout.lower()

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

    def test_a_rerun_over_an_unfinished_sprint_refuses_instead_of_skipping_the_checks(
        self, tmp_path
    ):
        """The close leg exits 0 at OPEN, when every story is unfinished by
        definition. Without the re-run split that exit 0 is also what a premature
        close gets — falsifier batch, full tier and triage all silently skipped."""
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "plan.md"
        for status in ("planned", "ready", "in-progress"):
            path.write_text(
                PLAN.replace(
                    "#### story-043 — also done   [done]",
                    f"#### story-043 — also done   [{status}]",
                )
            )
            r = sprint(repo, env, "start")
            assert r.returncode == 2 and "story-043" in r.stderr
            assert "milestone" not in (r.stdout + r.stderr).lower()

    def test_start_refuses_to_overwrite_another_active_sprint(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.write_text("sprint-other\n")
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "clear" in r.stderr
        assert path.read_text().strip() == "sprint-other"

    def test_start_refuses_trunk_and_never_records_it(self, tmp_path):
        """Both halves, because they are stopped by different code: with a sprint
        already recorded the mismatch refusal fires anyway, so only the SECOND —
        nothing recorded, the sprint's first start — reaches this guard. Recording
        trunk would point integration_target at trunk, merging every story there."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        path = tmp_path / "data" / "sprint_branch"
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "freshly cut branch" in r.stderr
        assert path.read_text().strip() == "sprint-002"
        path.unlink()
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "freshly cut branch" in r.stderr
        assert not path.exists()

    def test_an_empty_branch_record_refuses_rather_than_reading_as_unset(self, tmp_path):
        """The one branch-state boundary story-061 drew that nothing constructed.
        EMPTY IS NOT ABSENT: absent falls back to the default branch on purpose, so
        a truncated record read as absent silently retargets every story merge of
        the sprint to trunk — the single failure this whole card refuses to risk.
        The OTHER reader, close.integration_target, is walked by
        falsifier_sprint_branch_insulation.py — `review` resolves trunk, not the
        integration target, so this leg cannot stand in for it."""
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.write_text("\n")
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "is empty" in r.stderr and "Traceback" not in r.stderr
        assert path.read_text() == "\n", "the refusal rewrote the state it refused on"

    def test_unreadable_branch_state_is_not_treated_as_missing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        path = tmp_path / "data" / "sprint_branch"
        path.unlink()
        path.mkdir()
        r = sprint(repo, env, "start")
        assert r.returncode == 2 and "not readable" in r.stderr and "Traceback" not in r.stderr

    def test_a_retired_story_in_this_sprint_does_not_refuse(self, tmp_path):
        plan = (
            PLAN.replace(
                "#### story-043 — also done   [done]",
                "#### story-043 — folded elsewhere   [retired]",
            )
            .replace(
                "### Sprint 3",
                "### Pool — not scheduled\n#### story-098 — later   [planned]\n\n### Sprint 3",
            )
            .replace(
                "#### story-099 — not this sprint   [ready]",
                "#### story-099 — later terminal card   [done]",
            )
        )
        repo, env, _g = make_repo(
            tmp_path,
            plan=plan,
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert r.stdout.count("## Milestone 1") == 1
        assert "close.py sprint 2 milestone-done" in r.stdout
        assert (tmp_path / "data" / "plan.md").read_text() == plan
