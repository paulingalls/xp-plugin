"""story-003: SessionStart hook. Verify: pytest -q tests/test_session_start.py"""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "session_start.py"
HOOKS_JSON = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "hooks" / "hooks.json"


def run_hook(cwd, data_dir, session_id="sess-abc123"):
    stdin = json.dumps({"cwd": str(cwd), "session_id": session_id, "source": "startup"})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env={"PATH": "/usr/bin:/bin", "HOME": str(data_dir), "XP_DATA": str(data_dir / "xp")},
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def xp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(
        "# plan\n#### story-042 — demo   [in-progress]\nVerify: true\n"
    )
    (repo / ".xp" / "constraints.md").write_text("# Constraints\nCONSTRAINT-SENTINEL\n")
    (repo / "f.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    return repo, g


class TestScope:
    def test_outside_git_repo_silent(self, tmp_path):
        r = run_hook(tmp_path, tmp_path)
        assert r.returncode == 0 and r.stdout == ""

    def test_git_repo_without_xp_silent(self, tmp_path):
        repo = tmp_path / "plain"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, env={"PATH": "/usr/bin:/bin"}, check=True)
        r = run_hook(repo, tmp_path)
        assert r.returncode == 0 and r.stdout == ""


class TestInjection:
    def test_lead_profile_injected(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook(repo, tmp_path)
        assert r.returncode == 0, r.stderr
        for sentinel in ("XP Values", "CONSTRAINT-SENTINEL", "story-042", "main"):
            assert sentinel in r.stdout, f"missing {sentinel}"

    def test_banner_names_version_and_gates(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook(repo, tmp_path)
        assert "xp-plugin" in r.stdout and "0.1.0" in r.stdout
        assert "git hooks: none detected" in r.stdout  # fixture has no lefthook/.githooks

    def test_fresh_digest_injected_without_stale(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir()
        (data / "session.md").write_text(f"# Session digest — written x at {head}\nDIGEST-BODY\n")
        r = run_hook(repo, tmp_path)
        assert "DIGEST-BODY" in r.stdout and "STALE" not in r.stdout

    def test_stale_digest_prefixed_with_distance(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir()
        (data / "session.md").write_text(f"# Session digest — written x at {old}\nDIGEST-BODY\n")
        (repo / "f.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "one")
        (repo / "f.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "two")
        r = run_hook(repo, tmp_path)
        assert "STALE" in r.stdout and "2 commit" in r.stdout

    def test_stampless_digest_reads_stale_unknown(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        data.mkdir()
        (data / "session.md").write_text("no stamp here\nDIGEST-BODY\n")
        r = run_hook(repo, tmp_path)
        assert "STALE" in r.stdout and "unknown" in r.stdout

    def test_no_digest_recovery_block_only(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook(repo, tmp_path)
        assert r.returncode == 0
        assert "STALE" not in r.stdout and "story-042" in r.stdout

    def test_liveness_touchfile_session_scoped(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        run_hook(repo, tmp_path, session_id="sess-xyz")
        assert (tmp_path / "xp" / "markers" / "sess-xyz.alive").exists()

    def test_output_capped_with_notice(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text("HUGE\n" * 5000)
        r = run_hook(repo, tmp_path)
        assert len(r.stdout) <= 12_000 and "truncated" in r.stdout


class TestRegistration:
    def test_hooks_json_registers_the_script(self):
        cfg = json.loads(HOOKS_JSON.read_text())
        entries = cfg["hooks"]["SessionStart"]
        cmds = [h["command"] for e in entries for h in e["hooks"]]
        assert any("${CLAUDE_PLUGIN_ROOT}/scripts/session_start.py" in c for c in cmds)


class TestReviewFindings:
    """story-003 close review: resilience, content, guard pins."""

    def test_corrupt_session_md_degrades_one_section_not_all(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        data.mkdir()
        (data / "session.md").write_bytes(b"\xff\xfe garbage \xff")
        r = run_hook(repo, tmp_path, session_id="sess-corrupt")
        assert r.returncode == 0
        assert "CONSTRAINT-SENTINEL" in r.stdout  # other sections survive
        assert (tmp_path / "xp" / "markers" / "sess-corrupt.alive").exists()

    def test_recovery_block_carries_work_item_claims(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        import subprocess as sp

        work = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"
        sp.run(
            [sys.executable, str(work), "note", "OPEN-ITEM-CLAIM lives here"],
            cwd=repo,
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "XP_DATA": str(tmp_path / "xp")},
            check=True,
        )
        r = run_hook(repo, tmp_path)
        assert "OPEN-ITEM-CLAIM" in r.stdout  # content, not just timestamps

    def test_branch_line_pinned(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook(repo, tmp_path)
        assert "branch: main" in r.stdout

    def test_scope_refusals_leave_no_marker(self, tmp_path):
        r = run_hook(tmp_path, tmp_path, session_id="sess-outside")
        assert r.returncode == 0 and r.stdout == ""
        assert not (tmp_path / "xp" / "markers").exists()

    def test_truncation_preserves_recovery_block(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text("HUGE\n" * 5000)
        r = run_hook(repo, tmp_path)
        assert len(r.stdout) <= 12_000 and "truncated" in r.stdout
        assert "story-042" in r.stdout  # the freshest layer survives the cap


class TestTrustBoundary:
    def test_repo_sourced_sections_are_fenced_as_data(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook(repo, tmp_path)
        assert "BEGIN project content" in r.stdout and "END project content" in r.stdout
        fenced = r.stdout.split("BEGIN project content")[1]
        assert "CONSTRAINT-SENTINEL" in fenced  # repo files inside the fence
        head = r.stdout.split("BEGIN project content")[0]
        assert "XP Values" in head  # plugin-owned prose outside it


class TestSprintCloseFindings:
    def test_done_stories_excluded_from_recovery_block(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text() + "#### story-001 — ancient   [done]\nVerify: true\n")
        r = run_hook(repo, tmp_path)
        assert "story-042" in r.stdout and "ancient" not in r.stdout
