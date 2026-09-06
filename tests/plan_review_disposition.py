import json

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
        {"status": "edited", "reasons": ["the guard needs an executable acceptance check"]}
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

    def test_a_reason_split_by_hard_wrapping_is_present(self):
        reason = "the guard needs an executable acceptance check"
        report = json.dumps({"status": "edited", "reasons": [reason]})
        plan = b"Reason: the guard needs an executable\nacceptance check.\n"
        assert disposition_result(report, b"before", plan) == ""

    def test_the_reported_two_reason_markdown_edit_is_present(self):
        # The reporter disclosed only the first reason's length; this content is constructed.
        control = (
            "The first review reason is intentionally constructed to fit the reporter's "
            "measured length. It verifies that a long reason written verbatim remains accepted "
            "before the second reason reaches the Markdown boundary. Its exact prose was not "
            "disclosed, so this fixture does not pretend to reproduce it."
        )
        assert len(control) == 297
        prefix = (
            "Honesty and constraint 4 — this is the plan's one silent-data-loss path. "
            "Both normalizers return "
        )
        assert len(prefix) == 97
        reason = prefix + '"" on unparseable input (ContactNormalizer.swift:47, :71), so'
        report = json.dumps({"status": "edited", "reasons": [control, reason]})
        plan = (
            f"# plan\n\nReason: {control}\n\nReason: Honesty and constraint 4 — this is "
            'the plan\'s one silent-data-loss path. Both\nnormalizers return `""` on '
            "unparseable input\n(`ContactNormalizer.swift:47`, `:71`), so\n"
        ).encode()
        assert disposition_result(report, b"before", plan) == ""

    def test_reason_content_survives_markdown_punctuation_inside_the_sentence(self):
        reason = "the guard compares meaningful content words"
        report = json.dumps({"status": "edited", "reasons": [reason]})
        plan = b"Reason: the guard compares meaningful **content** words.\n"
        assert disposition_result(report, b"before", plan) == ""

    def test_a_reason_set_apart_as_a_blockquote_is_present(self):
        """bug 6677e018, measured on story-036's own round 1: six reasoned edits
        landed in the plan and the verdict was discarded, because a blockquote
        carries a `> ` on every WRAPPED line that the reason string cannot. A
        one-line quote matches by luck — `>` only precedes the reason — so the
        marker has to survive a wrap to model the defect at all.
        """
        reason = "Reason: Simplicity - one copy drifts from the other."
        report = json.dumps({"status": "edited", "reasons": [reason]})
        plan = b"# plan\n\n> Reason: Simplicity - one copy\n> drifts from the other.\n"
        assert disposition_result(report, b"# plan\n", plan) == ""

    def test_a_reason_genuinely_absent_from_the_plan_refuses(self):
        report = json.dumps({"status": "edited", "reasons": ["a missing reason"]})
        problem = disposition_result(report, b"before", b"changed plan with unrelated prose\n")
        assert "every plan edit" in problem

    def test_a_reason_with_different_words_refuses(self):
        reason = "the guard compares meaningful content words"
        report = json.dumps({"status": "edited", "reasons": [reason]})
        plan = b"Reason: the guard compares misleading **content** words.\n"
        problem = disposition_result(report, b"before", plan)
        assert "every plan edit" in problem

    def test_a_reason_matching_only_inside_longer_words_refuses(self):
        """Drop the word boundaries around the comparison and this greens: "act now"
        is a substring of "contract nowhere", so a reason the plan never carries
        reports as present."""
        report = json.dumps({"status": "edited", "reasons": ["act now"]})
        problem = disposition_result(report, b"before", b"Reason: we contract nowhere else.\n")
        assert "every plan edit" in problem

    def test_a_reason_assembled_from_scattered_plan_words_refuses(self):
        """Adjacency, not the vocabulary a reason draws on, is what makes it present.
        Every word below is in the plan, so relaxing the comparison to
        `all(w in plan_words ...)` greens on a reason the plan never states."""
        report = json.dumps({"status": "edited", "reasons": ["the guard needs a test"]})
        plan = b"Simplicity: a guard the plan needs is\nnot a test it already needs.\n"
        problem = disposition_result(report, b"before", plan)
        assert "every plan edit" in problem

    def test_a_reason_with_no_content_words_refuses(self):
        report = json.dumps({"status": "edited", "reasons": ["***"]})
        problem = disposition_result(report, b"before", b"---\n")
        assert "every plan edit" in problem

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
            ('{"status":"blocked","question":"human?"}', "", "blocked for the human"),
            ('{"status":"blocked","question":"human?"}', "edit", "human-only"),
            (CLEAN, "edit", "clean review changed"),
            (EDITED, "", "edited disposition left"),
            ('{"status":"edited","reasons":[]}', "edit-no-reason", "every plan edit"),
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
        teammate = (PLUGIN / "EXECUTOR.md").read_text().lower()
        assert "re-read" in teammate and "reviewed plan" in teammate
