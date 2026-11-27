import json

import pytest
import xp
from test_records import repo, state  # noqa: F401
from test_shared import CARD, plan, publisher  # noqa: F401
from xpcore import cards


def test_private_text_never_reaches_github(repo, publisher):  # noqa: F811
    config = repo / "r/.xp/config.yml"
    config.write_text(config.read_text() + "  publisher: claude/public-model\n")
    marker = "PRIVATE_PERSONAL_CONTEXT_QUIET_MARKER"
    plan(
        "## Sprint 1\n"
        + CARD.replace(
            "private local detail", marker + "\nmore " + marker + "\n- " + marker
        ).replace("Files:", "Unknown: " + marker + "\n- " + marker + "\nFiles:")
    )
    assert xp.main(["card", "publish", "free-share"]) == 0
    s = state(repo)
    assert marker not in s["issues"][0]["body"]
    assert all(marker not in str(call) for call in s["calls"])
    assert marker in cards.plan_path().read_text()

    assert xp.main(["card", "publish", "free-share"]) == 0
    assert marker not in str(state(repo)["calls"])
    assert cards.find_card("free-share").field("Issue") == "#224"
    assert not publisher.exists()


@pytest.mark.parametrize(
    "prefix,retained",
    [
        ("## Sprint s\n### Work\n", True),
        ("## Milestone\n### Sprint s\n", True),
        ("## Sprint outer\n### Sprint inner\n### More\n", True),
        ("## Sprint s\n## Free\n", False),
        ("## Milestone\n### Sprint s\n### Free\n", False),
    ],
)
@pytest.mark.parametrize("identifier", ["free-share", "story-001"])
def test_publish_section_membership(repo, publisher, prefix, retained, identifier):  # noqa: F811
    config = repo / "r/.xp/config.yml"
    config.write_text(config.read_text() + "  publisher: claude/public-model\n")
    plan(prefix + CARD.replace("free-share", identifier))
    assert xp.main(["card", "publish", identifier]) == 0
    found = cards.read_cards()
    assert bool(found) == retained
    if retained:
        assert found[0].field("Issue") == "#224"
        assert not publisher.exists()
    else:
        calls = [json.loads(line) for line in publisher.read_text().splitlines()]
        assert len(calls) == 1 and "public-model" in calls[0][0]


@pytest.mark.parametrize("status", ["in-progress", "done", "retired"])
def test_publish_retains_started_cards(repo, publisher, status):  # noqa: F811
    plan(CARD.replace("[planned]", f"[{status}]"))
    assert xp.main(["card", "publish", "free-share"]) == 0
    assert cards.find_card("free-share").field("Issue") == "#224"
    assert not publisher.exists()
