import xp
from test_records import repo, state  # noqa: F401
from test_shared import plan, publisher  # noqa: F401
from xpcore import cards, shared


def test_edit_during_publish_keeps_the_card(repo, publisher, monkeypatch, capsys):  # noqa: F811
    plan()
    run_agent = shared.launch.run_agent

    def lead_edits_while_seat_runs(*args, **kwargs):
        path = cards.plan_path()
        path.write_text(path.read_text().replace("## Later", "Note: lead edit\n\n## Later"))
        return run_agent(*args, **kwargs)

    monkeypatch.setattr(shared.launch, "run_agent", lead_edits_while_seat_runs)
    assert xp.main(["card", "publish", "free-share"]) == 0
    card = cards.find_card("free-share")
    assert "Note: lead edit" in card.lines and card.field("Issue") == "#224"
    assert "edited while publishing" in capsys.readouterr().out
    assert len(state(repo)["issues"]) == 1
