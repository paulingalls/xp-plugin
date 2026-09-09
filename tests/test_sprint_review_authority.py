"""story-014: the sprint close marshals its reviews.
Split from test_sprint_close.py at sprint-004 open."""

import json
import shutil

import pytest
from close_helpers import launches
from sprint_helpers import (
    PLAN,
    PLUGIN,
    head,
    make_repo,
    marker_path,
    record_reviews,
    sprint,
    staged_stub,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"


class TestReviewAuthority:
    @pytest.mark.parametrize("name", ["JUDGMENT.md", "VALUES.md", "constraints.md", "system.md"])
    @pytest.mark.parametrize("state", ["MISSING", "EMPTY", "UNREADABLE"])
    def test_required_input_state_refuses_before_sprint_launch(self, tmp_path, name, state):
        repo, env, g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        plugin_owned = name in {"JUDGMENT.md", "VALUES.md"}
        target = plugin / name if plugin_owned else repo / ".xp" / name
        target.unlink()
        if state == "EMPTY":
            target.write_text(" \n\t")
        elif state == "UNREADABLE":
            target.mkdir()
        if not plugin_owned:
            g("add", "-A")
            assert g("commit", "-qm", f"construct {state.lower()} {name}").returncode == 0
        record_reviews(tmp_path, repo, env)
        marker = marker_path(tmp_path)
        before = marker.read_bytes()

        result = sprint(repo, env, "review", close=plugin / "scripts" / "close.py")

        shown_path = str(target) if plugin_owned else f".xp/{name}"
        assert result.returncode == 2
        assert state in result.stderr and shown_path in result.stderr
        assert "review again" in result.stderr
        assert "Traceback" not in result.stderr
        assert launches(tmp_path) == []
        assert "(missing:" not in result.stdout + result.stderr
        assert marker.read_bytes() == before

    def test_a_fixer_that_deletes_a_rubric_still_records_the_round_it_ran(self, tmp_path):
        """A rubric read per stage refuses from the CLOSER's bundle, and that exit
        is a SystemExit past leg()'s error return — the one place the incomplete
        round is written. Six launches and the fixer's committed patch are then
        recorded nowhere. stages.check_roles resolves roles up front for this same
        reason, one stage earlier."""
        card = "#### story-042 — done thing   [done]"
        declaring = PLAN.replace(card, f"{card}\nFiles: .xp/system.md")
        repo, env, _g = make_repo(tmp_path, plan=declaring)
        blocking = {"fixed": [], "blocking": ["a silent one"], "noted": []}
        staged_stub(tmp_path, find=blocking, verify=blocking)
        deletion = (
            "diff --git a/.xp/system.md b/.xp/system.md\n"
            "deleted file mode 100644\n"
            "--- a/.xp/system.md\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-# System\n"
            "-SYSTEM-SENTINEL\n"
        )
        claude = tmp_path / "bin" / "claude"
        write = "sys.stdout.write("
        claude.write_text(
            claude.read_text().replace(
                write,
                f"open(pm.group(1).strip(), 'w').write({deletion!r}) if key == 'fix' else None\n"
                + write,
                1,
            )
        )
        claude.chmod(0o755)

        result = sprint(repo, env, "review")

        assert not (repo / ".xp" / "system.md").exists(), "the fixer's patch never applied"
        assert result.returncode == 0, result.stderr
        recorded = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert "incomplete" not in recorded, recorded
        assert recorded["shown_sha"] == head(repo, env), recorded
        after_fixer = launches(tmp_path)[-1]["stdin"]
        assert "## System context\n\n# System\nSYSTEM-SENTINEL\n\n" in after_fixer
        assert "(missing:" not in after_fixer
