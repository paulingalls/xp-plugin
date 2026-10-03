import json
import re
import shlex
import subprocess

import pytest
from plan_review import evaluate_disposition
from test_plan_review import (
    CLEAN,
    CONFIG,
    PLUGIN,
    make_repo,
    plan_review,
    stub_planner,
)


def disposition_result(text, before, after):
    """The refusal alone, for the cases whose outcome is not what is under test."""
    return evaluate_disposition(text, before, after)[1]


class TestPlanEditsInPlace:
    EDITED = json.dumps(
        {
            "status": "edited",
            "human_question": None,
            "reasons": ["the guard needs an executable acceptance check"],
        }
    )

    def repo(self, tmp_path, tracked=False):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        draft = repo / "draft plan.md" if tracked else tmp_path / "draft.md"
        draft.write_text("# draft plan\nstep 1\n")
        if tracked:
            g("add", "draft plan.md")
            g("commit", "-qm", "track plan")
        return repo, env, draft

    @pytest.mark.parametrize("tracked", [False, True], ids=["untracked", "tracked"])
    def test_reasoned_edits_replace_findings_negotiation(self, tmp_path, tracked):
        repo, env, draft = self.repo(tmp_path, tracked)
        stub_planner(tmp_path, findings=self.EDITED, motion="edit")
        result = plan_review(repo, env, "story-042", str(draft))
        assert result.returncode == 0, result.stderr
        assert "Reason: the guard needs" in draft.read_text()
        assert not (tmp_path / "data" / "markers" / "story-042.plan-review-incomplete").exists()

    def test_a_plan_read_failure_names_the_plan_and_a_retry_that_recovers(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path, findings=self.EDITED, motion="unreadable")
        result = plan_review(repo, env, "story-042", str(draft))
        marker = tmp_path / "data" / "markers" / "story-042.plan-review-incomplete"
        assert result.returncode == 2 and marker.exists()
        assert str(draft.resolve()) in result.stderr
        assert "every plan edit" not in result.stderr
        commands = re.findall(r"`([^`]+)`", result.stderr)
        assert len(commands) == 1

        draft.rmdir()
        draft.write_text("# draft plan\nstep 1\n")
        stub_planner(tmp_path, findings=self.EDITED, motion="edit")
        recovered = subprocess.run(
            shlex.split(commands[0]), cwd=repo, env=env, capture_output=True, text=True
        )
        assert recovered.returncode == 0, recovered.stderr
        assert not marker.exists()

    def test_a_reason_with_no_content_words_refuses(self):
        report = json.dumps({"status": "edited", "human_question": None, "reasons": ["***"]})
        problem = disposition_result(report, b"before", b"---\n")
        assert "non-empty text" in problem

    def test_a_bracket_in_the_prose_is_not_a_rival_disposition(self):
        """A footnote marker, a checkbox and a fenced non-object all decode as JSON on
        their own, so an ambiguity check counting every decodable value refuses the fenced
        verdict this story exists to accept — the round lost twice under a new diagnostic."""
        report = f"Findings [1]\n\n- [ ] nothing loud\n\n```\n[2]\n```\n\n```json\n{CLEAN}\n```"
        assert disposition_result(report, b"x", b"x") == ""
        truncated = f'Verdict: {{"status":\nquoted charter example: `{CLEAN}`'
        assert "could not read" in disposition_result(truncated, b"x", b"x")

    def test_prose_braces_beside_a_fenced_verdict_do_not_lose_the_round(self):
        """A finding that quotes a brace is not a rival verdict the harness failed to
        read. Let the prose scan's failure outvote a clean fenced disposition and this
        reds — a complete review lost to how it was WRITTEN, this story's whole class."""
        for noise in ("The plan's literal `{'a': 1}` is fine.", "It writes {status} there."):
            report = f"{noise}\n\n```json\n{CLEAN}\n```"
            assert evaluate_disposition(report, b"x", b"x") == ("ran", ""), noise

    def test_one_bare_object_in_prose_is_accepted(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        findings = f"Review complete.\n\n{CLEAN}\n\nNo plan edits were needed."
        stub_planner(tmp_path, findings=findings)
        result = plan_review(repo, env, "story-042", str(draft))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == findings
        marker = tmp_path / "data" / "markers" / "story-042.plan-review-incomplete"
        assert not marker.exists()

    def test_missing_and_unreadable_dispositions_are_distinct(self, tmp_path):
        cases = [
            ("missing", "Review complete with no disposition.", "wrote no structured disposition"),
            (
                "unreadable",
                '```json\n{"status":\n```',
                "wrote a structured disposition the harness could not read",
            ),
        ]
        for name, findings, message in cases:
            root = tmp_path / name
            repo, env, draft = self.repo(root)
            stub_planner(root, findings=findings)
            result = plan_review(repo, env, "story-042", str(draft))
            assert result.returncode == 2
            assert message in result.stderr, result.stderr
            # Constraint 15: each state needs its OWN message. While one refusal
            # contained the other as a substring, collapsing them greened here.
            other = [m for _n, _f, m in cases if m != message]
            assert not any(m in result.stderr for m in other), result.stderr
            marker = root / "data" / "markers" / "story-042.plan-review-incomplete"
            assert marker.exists()

    @pytest.mark.parametrize(
        "wrapper",
        ["{}", "```json\n{}\n```", "```\n{}\n```"],
        ids=["bare", "fenced", "untagged"],
    )
    @pytest.mark.parametrize(
        "findings,motion,mark",
        [
            (CLEAN, "", ""),
            (EDITED, "edit", ""),
            (
                '{"status":"blocked","reasons":[],"human_question":"human?"}',
                "",
                "blocked for the human",
            ),
            (
                '{"status":"blocked","reasons":[],"human_question":"human?"}',
                "edit-no-reason",
                "blocked for the human",
            ),
            (CLEAN, "edit", ""),
            (EDITED, "", ""),
            (
                '{"status":"edited","human_question":null,"reasons":[]}',
                "edit-no-reason",
                "",
            ),
            ("[]", "", "json object"),
            ("human question in prose", "", "structured disposition"),
            (f"{CLEAN}\n{CLEAN}", "", "ambiguous"),
        ],
        ids=[
            "clean",
            "edited",
            "blocked",
            "blocked-changed",
            "clean-changed",
            "edited-unchanged",
            "reason-absent",
            "non-object",
            "prose-only",
            "ambiguous",
        ],
    )
    def test_bare_and_fenced_dispositions_keep_round_states_distinct(
        self, tmp_path, wrapper, findings, motion, mark
    ):
        repo, env, draft = self.repo(tmp_path)
        before = draft.read_bytes()
        report = wrapper.format(findings)
        stub_planner(tmp_path, findings=report, motion=motion)
        result = plan_review(repo, env, "story-042", str(draft))
        marker = tmp_path / "data" / "markers" / "story-042.plan-review-incomplete"
        assert result.returncode == (2 if mark else 0), result.stderr
        assert (mark in result.stderr.lower()) if mark else result.stdout.strip() == report
        expected = "blocked" if mark == "blocked for the human" else "failed" if mark else "ran"
        assert evaluate_disposition(report, before, draft.read_bytes())[0] == expected
        assert marker.exists() is bool(mark)
        if findings == CLEAN and not motion:
            assert draft.read_bytes() == before

    def test_the_teammate_is_told_to_reread_the_plan(self):
        import spawn

        teammate = dict(spawn.teammate_sections("card", "story-042", "", PLUGIN, multifile=True))[
            "How you work"
        ].lower()
        assert "re-read" in teammate and "reviewed plan" in teammate
