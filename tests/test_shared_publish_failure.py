import json

import pytest
from test_records import refused, repo, state  # noqa: F401
from test_shared import plan, publisher  # noqa: F401
from xpcore import cards


@pytest.mark.parametrize(
    "failure", ["exit", "json", "missing", "blank", "type", "multiline", "secret", "gh"]
)
def test_failed_publish_preserves_plan(repo, publisher, monkeypatch, capsys, failure):  # noqa: F811
    plan()
    before = cards.plan_path().read_bytes()
    outputs = {
        "json": "invalid",
        "missing": "{}",
        "blank": '{"context":" "}',
        "type": '{"context":3}',
        "multiline": json.dumps({"context": "one\ntwo"}),
    }
    if failure == "exit":
        monkeypatch.setenv("PUBLISH_EXIT", "1")
    elif failure == "gh":
        monkeypatch.setenv("GH_CREATE_FAIL", "1")
    elif failure == "secret":
        (repo / "r/.gitleaks.toml").write_text(
            '[[rules]]\nid = "canary"\ndescription = "canary"\nregex = "xp_canary_[a-f0-9]{32}"\n'
        )
        monkeypatch.setenv(
            "PUBLISH_RESULT", json.dumps({"context": "xp_canary_0123456789abcdef0123456789abcdef"})
        )
    else:
        monkeypatch.setenv("PUBLISH_RESULT", outputs[failure])
    refused(capsys, ["card", "publish", "free-share"])
    assert cards.plan_path().read_bytes() == before
    s = state(repo)
    assert not s["issues"]
    if failure != "gh":
        assert all(call[0][:2] == ["auth", "status"] for call in s["calls"])
