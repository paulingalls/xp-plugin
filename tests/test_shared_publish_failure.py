import pytest
from test_records import refused, repo, state  # noqa: F401
from test_shared import plan
from xpcore import cards


@pytest.mark.parametrize("failure", ["secret", "gh"])
def test_failed_publish_preserves_plan(repo, monkeypatch, capsys, failure):  # noqa: F811
    plan("""#### free-share — shared work   [planned]
Context: public
Do: xp_canary_0123456789abcdef0123456789abcdef
""")
    before = cards.plan_path().read_bytes()
    if failure == "gh":
        monkeypatch.setenv("GH_CREATE_FAIL", "1")
    else:
        (repo / "r/.gitleaks.toml").write_text(
            '[[rules]]\nid = "canary"\ndescription = "canary"\nregex = "xp_canary_[a-f0-9]{32}"\n'
        )
    refused(capsys, ["card", "publish", "free-share"])
    assert cards.plan_path().read_bytes() == before
    s = state(repo)
    assert not s["issues"]
    if failure != "gh":
        assert all(call[0][:2] == ["auth", "status"] for call in s["calls"])
