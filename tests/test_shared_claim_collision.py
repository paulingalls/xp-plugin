import xp
from test_records import refused, repo, state  # noqa: F401
from test_shared import CARD, plan
from xpcore import cards


def test_claim_collision_leaves_issue_unheld(repo, capsys):  # noqa: F811
    plan()
    assert xp.main(["card", "publish", "free-share"]) == 0
    plan(CARD.replace("shared work", "different local work"))
    before = cards.plan_path().read_bytes()
    calls = len(state(repo)["calls"])
    error = refused(capsys, ["card", "claim", "224"])
    assert "free-share" in error and "collision" in error
    assert cards.plan_path().read_bytes() == before
    assert state(repo)["issues"][0]["labels"] == [{"name": "card"}]
    assert not any("--add-label" in call[0] for call in state(repo)["calls"][calls:])
