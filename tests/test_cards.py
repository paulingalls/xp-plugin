import threading
import time

import pytest
from xpcore import cards

PLAN = """\
# Roadmap

## Milestone 1 — first
Done when: shipped

## Sprint 12 — the slate
#### story-012 — parse cards   [planned]
Context: one paragraph.
AC:
- Given a plan When read Then cards
Files: a.py, b/c.py (new)
Acceptance: pytest -q tests/test_a.py
Executor: codex/gpt-6/medium

#### free-typo — fix a typo   [in-progress]
Files: README.md
Executor: (default)

## Sprint 13 — next
#### story-013 — later   [planned]
Files: d.py
"""


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    path = tmp_path / "plan.md"
    path.write_text(PLAN)
    return path


def refused(capsys, call, *args):
    with pytest.raises(SystemExit) as exit_info:
        call(*args)
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("refused: ")
    return err


def test_read_cards_parses_headings_and_fields(plan):
    story, free, later = cards.read_cards()
    assert (story.id, story.title, story.status) == ("story-012", "parse cards", "planned")
    assert story.files == ["a.py", "b/c.py"]
    assert story.acceptance == "pytest -q tests/test_a.py"
    assert story.executor == "codex/gpt-6/medium"
    assert story.lines[-1].startswith("Executor:")
    assert free.executor == "" and free.acceptance == ""
    assert later.files == ["d.py"]
    assert story.text.startswith("#### story-012") and story.text.endswith("medium\n")


def test_read_cards_accepts_text():
    assert [c.id for c in cards.read_cards("#### x-1 — t   [done]\n")] == ["x-1"]


def test_find_card_absent_refuses(plan, capsys):
    assert "story-999" in refused(capsys, cards.find_card, "story-999")


def test_duplicate_card_id_refuses(plan, capsys):
    plan.write_text(PLAN + "\n#### story-012 — again   [planned]\n")
    assert "2 cards" in refused(capsys, cards.find_card, "story-012")


def test_set_status_touches_only_the_heading(plan):
    cards.set_status("story-012", "in-progress")
    assert cards.find_card("story-012").status == "in-progress"
    assert plan.read_text() == PLAN.replace(
        "parse cards   [planned]", "parse cards   [in-progress]"
    )


def test_set_status_rejects_unknown_status(plan, capsys):
    assert "planned" in refused(capsys, cards.set_status, "story-012", "blocked")
    assert plan.read_text() == PLAN


def test_replace_card_keeps_its_neighbours(plan):
    cards.replace_card(
        "free-typo", "#### free-typo — fix two typos   [done]\nFiles: README.md, a.md\n"
    )
    text = plan.read_text()
    assert "fix two typos   [done]\nFiles: README.md, a.md\n\n## Sprint 13" in text
    assert text.startswith(PLAN.split("#### free-typo")[0])
    assert cards.find_card("free-typo").files == ["README.md", "a.md"]


def test_replace_card_requires_a_heading(plan, capsys):
    refused(capsys, cards.replace_card, "free-typo", "Files: x\n")


def test_sprint_slate_is_one_section(plan):
    slate = cards.sprint_slate("012")
    assert slate.startswith("## Sprint 12 — the slate")
    assert "free-typo" in slate and "story-013" not in slate
    assert cards.sprint_slate(13).endswith("Files: d.py\n")


def test_sprint_slate_missing_refuses(plan, capsys):
    assert "Sprint 99" in refused(capsys, cards.sprint_slate, "99")


def test_missing_plan_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    refused(capsys, cards.read_cards)


def test_plan_lock_serializes_two_writers(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    counter = tmp_path / "counter"
    counter.write_text("0")

    def writer():
        for _ in range(25):
            with cards.plan_lock():
                value = int(counter.read_text())
                time.sleep(0.001)
                counter.write_text(str(value + 1))

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counter.read_text() == "50"


def test_mint_free_appends_under_free_once(plan):
    assert cards.mint_free("free-x", "#### free-x — x   [planned]") is True
    assert cards.mint_free("free-x", "#### free-x — x   [planned]") is False
    text = plan.read_text()
    assert text.count("free-x") == 1
    assert text.endswith("Files: d.py\n\n## Free\n\n#### free-x — x   [planned]\n")
