import xp
from test_records import repo, state  # noqa: F401
from test_shared import plan
from xpcore import cards, shared


def test_edit_during_publish_keeps_the_card(repo, monkeypatch, capsys):  # noqa: F811
    plan()
    create_issue = shared.create_issue

    def lead_edits_while_creating(*args, **kwargs):
        path = cards.plan_path()
        path.write_text(path.read_text().replace("## Later", "Note: lead edit\n\n## Later"))
        return create_issue(*args, **kwargs)

    monkeypatch.setattr(shared, "create_issue", lead_edits_while_creating)
    assert xp.main(["card", "publish", "free-share"]) == 0
    card = cards.find_card("free-share")
    assert "Note: lead edit" in card.lines and card.field("Issue") == "#224"
    assert "edited while publishing" in capsys.readouterr().out
    assert len(state(repo)["issues"]) == 1
    assert "Note: lead edit" not in state(repo)["issues"][0]["body"]
