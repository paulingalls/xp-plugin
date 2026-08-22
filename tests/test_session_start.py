"""story-003: SessionStart hook. Verify: pytest -q tests/test_session_start.py"""

import json
import subprocess
import sys
from pathlib import Path

from session_start_close_cases import LastCloseCases
from session_start_helpers import HOOK, HOOKS_JSON, run_hook, run_hook_as, xp_repo


class TestLastClose(LastCloseCases):
    pass


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
        manifest = HOOK.parent.parent / ".claude-plugin" / "plugin.json"
        version = json.loads(manifest.read_text())["version"]
        assert "xp-plugin" in r.stdout and version in r.stdout
        assert "git hooks: none detected" in r.stdout  # fixture has no lefthook/.githooks

    def test_fresh_digest_injected_without_stale(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text(f"# Session digest — written x at {head}\nDIGEST-BODY\n")
        r = run_hook(repo, tmp_path)
        assert "DIGEST-BODY" in r.stdout and "STALE" not in r.stdout

    def test_stale_digest_prefixed_with_distance(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
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
        data.mkdir(exist_ok=True)
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
        data.mkdir(exist_ok=True)
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
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text(plan.read_text() + "#### story-001 — ancient   [done]\nVerify: true\n")
        r = run_hook(repo, tmp_path)
        assert "story-042" in r.stdout and "ancient" not in r.stdout


class TestRoleProfile:
    """Both paths emit POSITIVE, distinct output. A silent teammate path would
    pass identically when the hook crashes — main() ends in a bare
    `except (Exception, SystemExit): sys.exit(0)` — so "no output" cannot
    distinguish "role gate worked" from "role gate never ran" (constraint 2)."""

    def test_teammate_gets_one_line_marker_not_the_lead_profile(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook_as(repo, tmp_path, role="teammate")
        assert r.returncode == 0
        assert "teammate" in r.stdout.lower()
        assert len(r.stdout.strip().splitlines()) == 1
        # the lead profile's own sentinels must be ABSENT: spawn already inlines
        # VALUES + the card + constraints, so re-injecting them is duplicate tokens
        assert "BEGIN project content" not in r.stdout
        assert "XP Values" not in r.stdout

    def test_unset_role_is_the_lead(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook_as(repo, tmp_path, role=None)
        assert "BEGIN project content" in r.stdout

    def test_explicit_lead_role_gets_the_lead_profile(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_hook_as(repo, tmp_path, role="lead")
        assert "BEGIN project content" in r.stdout


class TestConstraintsSurviveTheBudget:
    """The rules must reach the lead. Measured at story-008 close: they did not.

    Constructed, not observed — the first falsifier for this asserted a string
    in the live repo's output and flipped GREEN when two short notes changed the
    last-3 window, with the defect fully intact.
    """

    def repo_with_long_work_entries(self, tmp_path, entries=3, body=2000):
        repo, _g = xp_repo(tmp_path)
        (repo / ".xp" / "constraints.md").write_text(
            "# Constraints\n\n"
            + "".join(f"{n}. **Rule {n}** filler.\n" for n in range(1, 10))
            + "10. **LAST-CONSTRAINT-SENTINEL** the rule most likely to be cut.\n"
        )
        xp = tmp_path / "xp"
        xp.mkdir(parents=True, exist_ok=True)
        (xp / "work.md").write_text(
            "".join(f"## note 2026-08-20T0{i}:00:00Z\n{'x' * body}\n\n" for i in range(entries))
        )
        return repo

    def test_long_work_entries_cannot_evict_the_constraints(self, tmp_path):
        repo = self.repo_with_long_work_entries(tmp_path)
        out = run_hook(repo, tmp_path).stdout
        assert "LAST-CONSTRAINT-SENTINEL" in out, (
            f"the rules were evicted by work.md entries ({len(out)} chars emitted)"
        )

    def test_a_single_enormous_entry_cannot_evict_them_either(self, tmp_path):
        repo = self.repo_with_long_work_entries(tmp_path, entries=1, body=9000)
        out = run_hook(repo, tmp_path).stdout
        assert "LAST-CONSTRAINT-SENTINEL" in out

    def test_the_recovery_block_still_reports_the_entries_it_truncates(self, tmp_path):
        """Bounded, not dropped — the lead must still see that work was filed."""
        repo = self.repo_with_long_work_entries(tmp_path)
        out = run_hook(repo, tmp_path).stdout
        assert out.count("## note 2026-08-20T0") == 3

    def test_an_oversized_digest_cannot_evict_the_constraints_either(self, tmp_path):
        """The rules outrank the narrative. A digest is recreatable from git and
        work.md; a silently-absent constraint is a rule the lead never knew it
        was breaking. This is what pins the section ORDER — the entry cap alone
        leaves the digest free to push the rules off the end."""
        repo = self.repo_with_long_work_entries(tmp_path, entries=1, body=50)
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
        ).stdout.strip()
        (tmp_path / "xp" / "session.md").write_text(
            f"# Session digest — written 2026-08-20T00:00:00Z at {sha}\n" + "narrative. " * 900
        )
        out = run_hook(repo, tmp_path).stdout
        assert "LAST-CONSTRAINT-SENTINEL" in out, "an unbounded digest evicted the rules"


class TestCodexSessionStart:
    """story-025: the payload a live codex-cli 0.147.0 SessionStart delivers, verbatim
    — no session variable reaches the process, and codex runs the hook in the session
    cwd, which is a repo SUBDIRECTORY whenever the human launched it from one.
    """

    def codex_run(self, cwd, data_dir, payload):
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            env={"PATH": "/usr/bin:/bin", "HOME": str(data_dir), "XP_DATA": str(data_dir / "xp")},
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def test_codex_payload_injects_and_keys_liveness_on_the_payload(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        sub = repo / "pkg"
        sub.mkdir()
        r = self.codex_run(
            sub,
            tmp_path,
            {
                "session_id": "01a0287c-801c-7651-bf86-d1cb2d4b2284",
                "transcript_path": "/dev/null",
                "cwd": str(sub),
                "hook_event_name": "SessionStart",
                "model": "gpt-5.6-terra",
                "permission_mode": "bypassPermissions",
                "source": "startup",
            },
        )
        assert "CONSTRAINT-SENTINEL" in r.stdout, r.stderr
        alive = tmp_path / "xp" / "markers" / "01a0287c-801c-7651-bf86-d1cb2d4b2284.alive"
        assert alive.exists()

    def test_session_id_alone_still_lands_the_touchfile(self, tmp_path):
        """Fault-injection for the key: an env-keyed touchfile has nothing to read."""
        repo, _g = xp_repo(tmp_path)
        self.codex_run(repo, tmp_path, {"session_id": "bare-id"})
        assert (tmp_path / "xp" / "markers" / "bare-id.alive").exists()

    def test_codex_payload_refreshes_the_plugin_pointer(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        path = tmp_path / "xp" / "env.json"
        path.write_text(json.dumps({"plugin_root": "/gone", "plugin_version": "0.0.1"}))

        self.codex_run(
            repo,
            tmp_path,
            {"session_id": "codex", "hook_event_name": "SessionStart", "source": "startup"},
        )

        recorded = json.loads(path.read_text())
        manifest = json.loads((HOOK.parent.parent / ".claude-plugin" / "plugin.json").read_text())
        assert recorded == {
            "plugin_root": str(HOOK.parent.parent),
            "plugin_version": manifest["version"],
        }


class TestOneHooksFileServesBothHarnesses:
    """AC1: codex loads hooks/hooks.json by its own default discovery, and an event
    name it does not know leaves the rest of the file running (both measured on
    0.147.0). A second registration could only drift."""

    def test_no_per_harness_registration_exists(self):
        plugin = HOOK.parent.parent
        assert list(plugin.rglob("hooks*.json")) == [HOOKS_JSON]
        assert list(plugin.rglob(".codex-plugin")) == []
        assert "hooks" not in json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())


class TestSkillsCarryNoPreload:
    def test_no_shipped_skill_preloads(self):
        """codex delivers a skill LOCATOR and never expands `!` — so a preload is
        content that silently vanishes on one harness."""
        skills = sorted((HOOK.parent.parent / "skills").rglob("SKILL.md"))
        assert skills, "no shipped skills found — the check would be vacuous"
        for skill in skills:
            for line in skill.read_text().splitlines():
                # the TOKEN, not the line start: `Current state: !`git status`` is the
                # ordinary spelling and expands exactly as a leading one does
                assert "!`" not in line, f"{skill.parent.name}: {line}"


class TestEnvRefresh:
    """story-027 AC2. The codex plugin cache is version-keyed, so every release
    moves the install and a seeded pointer goes stale on its own. Only this
    refresh clears it, which is why it runs on every session and both roles."""

    PLUGIN = HOOK.parent.parent

    def seed(self, tmp_path, **extra):
        d = tmp_path / "xp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "env.json").write_text(
            json.dumps({"plugin_root": "/gone/0.0.1", "plugin_version": "0.0.1", **extra})
        )
        return d / "env.json"

    def recorded(self, tmp_path):
        return json.loads((tmp_path / "xp" / "env.json").read_text())

    def assert_current(self, tmp_path):
        manifest = json.loads((self.PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        found = self.recorded(tmp_path)
        assert found["plugin_root"] == str(self.PLUGIN), found
        assert found["plugin_version"] == manifest["version"], found

    def test_the_hook_refreshes_a_stale_pointer(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        self.seed(tmp_path)
        assert run_hook(repo, tmp_path).returncode == 0
        self.assert_current(tmp_path)

    def test_the_refresh_leaves_non_plugin_keys_alone(self, tmp_path):
        """AC1's merge clause, on the path that can reach an existing file — setup's
        own .xp/ and plan refusals block every route to one."""
        repo, _g = xp_repo(tmp_path)
        self.seed(tmp_path, scratch="keep me")
        run_hook(repo, tmp_path)
        assert self.recorded(tmp_path)["scratch"] == "keep me"
        self.assert_current(tmp_path)

    def test_a_teammate_session_refreshes_it_too(self, tmp_path):
        """The write sits ABOVE the XP_ROLE gate: the teammate path returns before
        the profile builders, so a write below it would refresh on lead sessions
        only — and a teammate's session is a live install pointer like any other."""
        repo, _g = xp_repo(tmp_path)
        self.seed(tmp_path)
        r = run_hook_as(repo, tmp_path, role="teammate")
        assert "teammate session" in r.stdout, r.stdout
        self.assert_current(tmp_path)

    def test_a_hook_that_cannot_write_keeps_injecting(self, tmp_path):
        """A pointer-write failure must not trade away the whole lead profile."""
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "env.json").mkdir(parents=True)
        r = run_hook(repo, tmp_path)
        assert r.returncode == 0
        assert "CONSTRAINT-SENTINEL" in r.stdout, r.stdout or r.stderr

    def test_an_invalid_env_is_not_replaced_and_the_hook_keeps_injecting(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        path = tmp_path / "xp" / "env.json"
        for invalid in ('{"consumer": ', '["consumer"]'):
            path.write_text(invalid)

            r = run_hook(repo, tmp_path)

            assert r.returncode == 0
            assert "CONSTRAINT-SENTINEL" in r.stdout, r.stdout or r.stderr
            assert path.read_text() == invalid
