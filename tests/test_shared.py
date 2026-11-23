import json

import xp
from test_records import refused, repo, state  # noqa: F401
from xpcore import cards

CARD = """#### free-share — shared work   [planned]
Context: private local detail
Measure: distance=1
AC:
- first
  continuation
- second
Files: a.py
Acceptance: true
Evidence: git cat-file -e origin/main:read.md
Executor: codex
"""


def plan(text=CARD):
    cards.plan_path().parent.mkdir(exist_ok=True)
    cards.plan_path().write_text("## Free\n\n" + text + "\n## Later\nuntouched\n")


def save(fixture, value):
    (fixture / "issues.json").write_text(json.dumps(value))


def test_publish_and_edit(repo):  # noqa: F811
    plan()
    before = cards.plan_path().read_text()
    assert xp.main(["card", "publish", "free-share"]) == 0
    issue = state(repo)["issues"][0]
    assert issue["labels"] == [{"name": "card"}]
    owner = issue["body"].split("Published by: ")[1].strip()
    assert (
        issue["body"]
        == CARD.replace("Context: private local detail", f"Context: local to {owner}")
        + f"Published by: {owner}\n"
    )
    assert cards.plan_path().read_text().replace("Issue: #224\n", "") == before
    cards.plan_path().write_text(cards.plan_path().read_text().replace("a.py", "b.py"))
    assert xp.main(["card", "publish", "free-share"]) == 0
    s = state(repo)
    assert len(s["issues"]) == 1 and "Files: b.py" in s["issues"][0]["body"]
    assert len([c for c in s["calls"] if c[0][:2] == ["issue", "create"]]) == 1
    assert cards.plan_path().read_text().count("Issue: #224") == 1
    assert "Context: private local detail" in cards.plan_path().read_text()
