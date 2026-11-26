import pytest
import xp
from test_land import git, make_project


def test_open_refuses_slate_questions_then_resumes(tmp_path, monkeypatch, capsys):
    root, data = make_project(tmp_path, monkeypatch)
    slate = data / "plan.md"
    slate.write_text(
        "## Sprint questions — s\n\n#### story-001 — a   [planned]\nFiles: a.py\nAcceptance: true\n"
    )
    review = data / "sprints" / "questions" / "slate-review.md"
    review.parent.mkdir(parents=True)
    questions = [
        "QUESTION: Which source owns provenance?",
        "- QUESTION (lead): Contributor or sponsor?",
        "**QUESTION:** Which migration ruling applies?",
    ]
    # Field reviewers mostly write a bare marker with the question as the next paragraph.
    bare = "QUESTION:\n\n**story-001.** Which inviter becomes sponsor?"
    prose = "The prose mentions QUESTION without asking one.\nQUESTIONABLE is not a question.\n"
    review.write_text("\n".join(questions) + "\n" + bare + "\n\n" + prose)
    git(root, "switch", "-qc", "sprint-questions", "main")
    original_slate, original_review = slate.read_bytes(), review.read_bytes()
    record = data / "sprint_branch"

    for flags in (["--dry-run"], []):
        with pytest.raises(SystemExit) as exit_:
            xp.main(["sprint", "open", "questions", *flags])
        assert exit_.value.code == 2
        err = capsys.readouterr().err
        assert str(review) in err
        for question in questions:
            assert question in err
        assert "QUESTION: **story-001.** Which inviter becomes sponsor?" in err
        assert "ask the human" in err
        assert "a flat reading is the lead's own call" in err
        assert "record the ruling in the card as `Lead decisions (slate review, <date>):`" in err
        assert "delete the QUESTION line" in err
        assert "xp.py sprint open questions" in err
        assert slate.read_bytes() == original_slate
        assert review.read_bytes() == original_review
        assert not record.exists()

    slate.write_text(
        slate.read_text()
        + "Lead decisions (slate review, 2026-11-26): Preserve contributor provenance.\n"
    )
    review.write_text(prose)
    ruled_slate, ruled_review = slate.read_bytes(), review.read_bytes()
    assert xp.main(["sprint", "open", "questions", "--dry-run"]) == 0
    assert not record.exists()
    assert xp.main(["sprint", "open", "questions"]) == 0
    assert "Sprint questions open on sprint-questions" in capsys.readouterr().out
    assert record.read_text().strip() == "sprint-questions"
    assert slate.read_bytes() == ruled_slate
    assert review.read_bytes() == ruled_review
