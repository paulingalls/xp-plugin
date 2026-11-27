import pytest
import xp
from test_land import git
from test_records import repo, state  # noqa: F401
from test_shared import CARD, PUBLIC, plan, publisher  # noqa: F401
from xpcore import cards


@pytest.mark.parametrize("republish", [False, True])
def test_claimed_context_edits_stay_local(repo, publisher, republish):  # noqa: F811
    root = repo / "r"
    git(root, "branch", "-M", "main")
    git(root, "add", ".xp/config.yml")
    git(root, "commit", "-qm", "roles")
    plan(CARD.replace("Executor: codex", "Executor: codex/exec-model"))
    assert xp.main(["card", "publish", "free-share"]) == 0
    assert xp.main(["card", "claim", "224"]) == 0
    cards.set_field("free-share", "Context", "private customer report")
    before = len(state(repo)["calls"])
    command = ["card", "publish"] if republish else ["story"]
    assert xp.main([*command, "free-share"]) == 0
    assert f"Context: {PUBLIC}\n" in state(repo)["issues"][0]["body"]
    assert "private customer report" not in str(state(repo)["calls"][before:])
    assert cards.find_card("free-share").field("Context") == "private customer report"
