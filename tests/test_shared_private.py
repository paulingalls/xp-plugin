import xp
from test_records import repo, state  # noqa: F401
from test_shared import CARD, plan
from xpcore import cards


def test_private_text_never_reaches_github(repo):  # noqa: F811
    marker = "PRIVATE_PERSONAL_CONTEXT_QUIET_MARKER"
    plan(
        CARD.replace("private local detail", marker + "\nmore " + marker + "\n- " + marker).replace(
            "Files:", "Unknown: " + marker + "\n- " + marker + "\nFiles:"
        )
    )
    assert xp.main(["card", "publish", "free-share"]) == 0
    s = state(repo)
    assert marker not in s["issues"][0]["body"]
    assert all(marker not in str(call) for call in s["calls"])
    assert marker in cards.plan_path().read_text()
