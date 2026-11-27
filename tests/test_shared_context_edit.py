import pytest
import xp
from test_land import git
from test_records import repo, state  # noqa: F401
from test_shared import CARD, agents, plan, save  # noqa: F401
from xpcore import cards


@pytest.mark.parametrize("republish", [False, True])
def test_claimed_context_edits_stay_local(repo, agents, republish):  # noqa: F811
    root = repo / "r"
    git(root, "branch", "-M", "main")
    git(root, "add", ".xp/config.yml")
    git(root, "commit", "-qm", "roles")
    plan(
        CARD.replace("Executor: codex", "Executor: codex/exec-model").replace(
            "private local detail", "public Context\npublic original, see: continuation"
        )
        + "Do: original\nRelease steps: none\n\nTrailing prose\n"
    )
    assert xp.main(["card", "publish", "free-share"]) == 0
    assert xp.main(["card", "claim", "224"]) == 0
    path = cards.plan_path()
    path.write_text(
        path.read_text()
        .replace(
            "public Context\npublic original, see: continuation",
            "private customer report\nprivate, see: continuation\nRejected: private choice",
        )
        .replace("Do: original", "Do: edited")
        .replace("Trailing prose", "Edited prose")
    )
    published = state(repo)
    body = published["issues"][0]["body"]
    published["issues"][0]["body"] = body.replace(
        "Context: public Context\npublic original, see: continuation",
        "Context: issue-owned\npublic, see: continuation",
    )
    save(repo, published)
    before = len(state(repo)["calls"])
    command = ["card", "publish"] if republish else ["story"]
    assert xp.main([*command, "free-share"]) == 0
    expected = cards.find_card("free-share").text.replace(
        "Context: private customer report\nprivate, see: continuation\nRejected: private choice",
        "Context: issue-owned\npublic, see: continuation",
    )
    assert state(repo)["issues"][0]["body"] == expected
    assert expected.count("Published by:") == 1
    assert "private, see: continuation" not in str(state(repo)["calls"][before:])
    assert "private choice" not in str(state(repo)["calls"][before:])
    assert "private customer report" not in str(state(repo)["calls"][before:])
    assert cards.find_card("free-share").field("Context") == "private customer report"
