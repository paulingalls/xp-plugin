"""Sprint-review card motion after an applied fixer patch."""

from sprint_helpers import head, make_repo, sprint, staged_stub


def test_changed_cards_offer_no_undo_spanning_the_applied_fix(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    before = head(repo, env)
    staged_stub(
        tmp_path,
        patches=[("fix", "src.py", "C = 2")],
        find={"fixed": [], "blocking": ["F"], "noted": []},
        verify={"fixed": [], "blocking": ["F"], "noted": []},
        fix={"fixed": ["F"], "blocking": [], "noted": []},
    )
    claude = tmp_path / "bin" / "claude"
    claude.write_text(
        claude.read_text() + "if key == 'close':\n"
        "    p = os.environ['XP_DATA'] + '/plan.md'\n"
        "    t = open(p).read()\n"
        "    open(p, 'w').write(t.replace('story-042 — done thing', 'story-042 — changed'))\n"
    )
    claude.chmod(0o755)

    result = sprint(repo, env, "review")

    assert result.returncode == 2 and "cards changed" in result.stderr
    assert head(repo, env) != before, "no applied fixer commit for an undo to span"
    assert "git reset --hard" not in result.stderr and before[:8] not in result.stderr
