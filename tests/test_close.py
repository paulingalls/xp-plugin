"""story-002: close.py story-close pipeline. Verify: pytest -q tests/test_close.py"""

import json
import subprocess
import sys
from pathlib import Path

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"
WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: {verify}
"""


CONFIG = "roles:\n  reviewer: claude/opus\ntests:\n  story: true\n"


def stub_reviewer(tmp_path, result="findings above", exit_code=0, raw=None, report=...):
    """A fake `claude` that APPENDS one JSONL record per launch.

    Append, not overwrite: an overwriting stub makes "the reviewer was not
    launched again" pass vacuously by re-reading the previous launch's record.

    `report` is what a REAL reviewer does under story-012a: find the REPORT_PATH
    line in the bundle and write its findings there. Defaults to a clean report,
    since most tests here are about what happens AFTER a review. Pass a dict for
    specific findings, a str for malformed JSON, None to write nothing at all (the
    prose-only reviewer, which the pipeline must refuse).
    """
    if report is ...:
        report = {"fixed": [], "blocking": [], "noted": []}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launches.jsonl"
    payload = raw if raw is not None else json.dumps({"result": result})
    body = report if isinstance(report, str) or report is None else json.dumps(report)
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "stdin = sys.stdin.read()\n"
        f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'stdin': stdin}) + '\\n')\n"
        f"body = {body!r}\n"
        "if body is not None:\n"
        "    m = re.search(r'^REPORT_PATH: (.+)$', stdin, re.M)\n"
        "    assert m, 'the bundle named no REPORT_PATH'\n"
        "    open(m.group(1).strip(), 'w').write(body)\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir


def launches(tmp_path):
    rec = tmp_path / "launches.jsonl"
    return [json.loads(ln) for ln in rec.read_text().splitlines()] if rec.exists() else []


def marker(tmp_path, story_id="story-042"):
    return json.loads((tmp_path / "data" / "markers" / f"{story_id}.close.json").read_text())


def make_repo(tmp_path, status="in-progress", verify="true", branch="main"):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    g("init", "-q", "-b", branch)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, verify=verify))
    (repo / ".xp" / "config.yml").write_text(CONFIG)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "VALUES.md").write_text("# XP Values\nVALUES-SENTINEL\n")
    (repo / "src").mkdir()
    (repo / "src" / "thing.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "story-042-branch")
    (repo / "src" / "thing.py").write_text("A = 2\n")
    g("add", "-A")
    g("commit", "-qm", "story work")
    return repo, env, g


def close(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(CLOSE), "story", "story-042", *args, "--merge-mode", "local"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


class TestStart:
    def test_dirty_tree_refused_naming_reason(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 3\n")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()

    def test_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="ready")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "in-progress" in r.stderr

    def test_bundle_inlines_rules_diff_card_and_work_entries(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        subprocess.run(
            [sys.executable, str(WORK), "note", "filed-during-story"],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        bundle = launches(tmp_path)[0]["stdin"]  # the bundle is the reviewer's prompt now
        for sentinel in (
            "Communication",  # VALUES now come from the plugin root, not the repo
            "CONSTRAINT-SENTINEL",
            "SYSTEM-SENTINEL",
            "A = 2",
            "demo story",
            "filed-during-story",
        ):
            assert sentinel in bundle, f"bundle missing {sentinel}"


class TestReviewed:
    def test_verdict_flag_is_gone_so_no_verdict_can_be_hand_supplied(self, tmp_path):
        """AC 1: a lead-supplied verdict is the forgeable-verdict gap this story closes."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "unrecognized arguments: --verdict" in r.stderr

    def test_red_verify_aborts_before_merge_naming_command(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify="false")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "false" in (r.stderr + r.stdout)
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge

    def test_green_close_merges_with_verdict_and_flips_status(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        body = g("log", "main", "-1", "--format=%B").stdout
        assert "Review round 1" in body
        assert "[done]" in (repo / ".xp" / "plan.md").read_text()

    def test_conflicting_main_aborts_back_to_reviewing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "conflicting")
        g("checkout", "-q", "story-042-branch")
        # land refuses on the trunk motion, and review sends the lead to merge trunk
        # in — which is where the conflict now surfaces: on the story branch, in the
        # lead's own working tree, before any review is spent on it
        assert close(repo, env, "land").returncode == 2
        assert "git merge main" in close(repo, env, "review").stderr
        assert g("merge", "main").returncode != 0
        g("merge", "--abort")
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert g("status", "--porcelain").stdout == ""  # no half-merged tree left behind

    def test_pr_mode_dry_run_pins_gh_args(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "gh pr create" in r.stdout and "Review round 1" in r.stdout
        merge_lines = [ln for ln in r.stdout.splitlines() if "gh pr merge" in ln]
        assert len(merge_lines) == 1
        assert "--merge" in merge_lines[0] and "--delete-branch" in merge_lines[0]
        assert "Review round 1" in merge_lines[0]  # rounds ride the merge, not only create
        assert any(ln.startswith("git push") for ln in r.stdout.splitlines())

    def test_reviewed_dirty_tree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "fixed.txt").write_text("untracked dirt\n")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_story_tier_runs_after_verify(self, tmp_path):
        repo, env, g = make_repo(tmp_path)  # card Verify is green (true)
        (repo / ".xp" / "config.yml").write_text(CONFIG.replace("story: true", "story: false"))
        g("add", "-A")
        g("commit", "-qm", "red story tier")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_land_without_review_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "land")
        assert r.returncode == 2 and "review" in r.stderr
        assert "Traceback" not in r.stderr

    def test_unknown_story_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-999", "review", "--merge-mode", "local"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "story-999" in r.stderr
        assert "Traceback" not in r.stderr


class TestSecondReviewRound:
    """Findings from /code-review on the story-002 diff."""

    def test_post_merge_plan_flip_preserves_main_side_changes(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text() + "#### story-043 — other   [done]\nVerify: true\n")
        g("add", "-A")
        g("commit", "-qm", "story-043 done on main")
        g("checkout", "-q", "story-042-branch")
        g("merge", "-q", "main", "-m", "merge trunk before re-review")
        close(repo, env, "review")  # re-baseline: the merge is what moves the base
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        merged = g("show", "main:.xp/plan.md").stdout
        assert "#### story-043 — other   [done]" in merged  # main-side change survives
        assert "#### story-042 — demo story   [done]" in merged

    def test_main_motion_after_start_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "main" in (r.stderr + r.stdout)
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_local_dry_run_performs_no_mutation(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge happened
        r2 = close(repo, env, "land")
        assert r2.returncode == 0, "marker must survive a dry-run"

    def test_close_on_default_branch_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "story-042-branch")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "main" in r.stderr

    def test_missing_verify_line_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true\n", ""))
        g("add", "-A")
        g("commit", "-qm", "drop verify line")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "verify" in r.stderr.lower()

    def test_master_default_branch_supported(self, tmp_path):
        repo, env, g = make_repo(tmp_path, branch="master")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "master", "-1", "--format=%B").stdout

    def test_pr_mode_detects_origin_trunk_motion(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        # origin/main moves while local main stays put (the pr-mode workflow shape)
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        old = g("rev-parse", "HEAD~1").stdout.strip()
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        # stale tracking ref: only a real fetch can observe the motion
        g("update-ref", "refs/remotes/origin/main", old)
        g("checkout", "-q", "story-042-branch")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "moved" in r.stderr

    def test_local_trunk_motion_with_remote_present_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        # commit lands on LOCAL main only; origin/main stays put (local-mode workflow)
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "local main moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()


class TestSprintIntegration:
    """story-005: release: sprint — stories integrate on the sprint branch."""

    def sprint_repo(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("checkout", "-q", "main")
        g("add", "-A")
        g("commit", "-qm", "sprint config")
        # real mid-sprint shape: sprint-001 has DIVERGED from main before the story
        g("checkout", "-qb", "sprint-001")
        (repo / "sprint-work.txt").write_text("earlier story landed here\n")
        g("add", "-A")
        g("commit", "-qm", "earlier sprint story")
        # story branches off the sprint branch, not main
        g("branch", "-D", "story-042-branch")
        g("checkout", "-qb", "story-042-branch")
        (repo / "src" / "thing.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "story work")
        return repo, env, g

    def test_close_merges_into_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        r = close(repo, env, "review")
        # bundle diff is story-only: already-landed sprint work must not appear (B1)
        assert "earlier story landed here" not in r.stdout
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "sprint-001", "-1", "--format=%B").stdout
        assert "[done]" in g("show", "sprint-001:.xp/plan.md").stdout
        assert "Review round" not in g("log", "main", "--format=%B").stdout  # main untouched

    def test_sprint_release_without_branch_key_falls_back_to_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "sprint release, no branch yet")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_story_release_ignores_sprint_branch_key(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: story\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("branch", "sprint-001", "main")
        g("add", "-A")
        g("commit", "-qm", "story release")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_guards_watch_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "sprint-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "sprint branch moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr

    def test_main_motion_does_not_block_sprint_close(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "main-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved — sprint close's concern, not ours")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr

    def test_pr_mode_with_sprint_target_refused(self, tmp_path):
        repo, env, _g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr

    def test_start_from_default_branch_still_refused(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("checkout", "-q", "main")
        r = close(repo, env, "review")
        assert r.returncode == 2

    def test_configured_sprint_branch_missing_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("add", "-A")
        g("commit", "-qm", "config names a branch that does not exist")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "sprint-001" in r.stderr  # fail-safe, never fall back to main

    def test_tag_named_like_sprint_branch_cannot_freeze_the_guard(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("tag", "sprint-001", "main")  # refs/tags wins plain rev-parse; guard must not care
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "sprint-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "sprint branch moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr

    def test_pr_refusal_precedes_moved_check(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "sprint-001")
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "sprint-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "moved")
        g("push", "-q", "origin", "sprint-001")  # origin's sprint branch moves too
        g("checkout", "-q", "story-042-branch")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr and "moved" not in r.stderr


class TestSprintCloseFindings:
    """sprint-001 broad review: consumer-facing correctness before release."""

    def test_start_works_from_repo_subdirectory(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        sub = repo / "src"
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "review", "--merge-mode", "local"],
            cwd=sub,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0 and "demo story" in launches(tmp_path)[0]["stdin"]

    def test_bundle_values_come_from_plugin_root(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / "VALUES.md").unlink()  # consumer repos have no VALUES.md of their own
        subprocess.run(["git", "add", "-A"], cwd=repo, env=env, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, env=env, capture_output=True)
        r = close(repo, env, "review")
        assert r.returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "Communication" in bundle and "(missing" not in bundle

    def test_missing_gh_refused_before_any_push(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env={**env, "PATH": "/usr/bin:/bin"},  # no gh on PATH
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "gh" in r.stderr and "Traceback" not in r.stderr

    def test_missing_plan_md_refused_cleanly(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "plan.md").unlink()
        g("add", "-A")
        g("commit", "-qm", "no plan")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "plan.md" in r.stderr and "Traceback" not in r.stderr

    def test_bracketless_story_header_refused_cleanly(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("   [in-progress]", ""))
        g("add", "-A")
        g("commit", "-qm", "malformed header")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr


class TestPipelineReceivedVerdict:
    """story-008 AC 1/4: the pipeline spawns the reviewer and records its verdict."""

    def test_review_launches_the_reviewer_with_the_bundle_inlined(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        assert "--plugin-dir" in argv and "-p" in argv
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--output-format") + 1] == "json"
        prompt = launch["stdin"]
        assert "fault-inject" in prompt.lower()  # the charter, inlined
        assert "demo story" in prompt  # the card
        assert "-A = 1" in prompt and "+A = 2" in prompt  # the cumulative diff
        assert "CONSTRAINT-SENTINEL" in prompt and "SYSTEM-SENTINEL" in prompt

    def test_the_spawned_reviewer_is_not_a_lead_and_cannot_close(self, tmp_path):
        """N10: the only thing pinning the reviewer's role otherwise lives in
        test_spawn.py, which this story's Verify does not run."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (launch,) = launches(tmp_path)
        assert launch["env"]["XP_ROLE"] == "reviewer"

    def test_reviewer_cannot_edit_the_lead_tree_it_is_reviewing(self, tmp_path):
        """G1: spawn's bypass posture was justified by a THROWAWAY worktree; the
        reviewer runs in the lead's live tree, so the write tools are denied."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        denied = argv[argv.index("--disallowedTools") + 1]
        assert {"Edit", "Write", "NotebookEdit"} <= set(denied.split(","))

    def test_a_reviewer_that_commits_is_refused_not_certified(self, tmp_path):
        """G1 fault-injection: the stub commits, exactly as a bypassed agent could.

        It must ALSO write a valid report. story-012a put the no-report refusal in
        front of this guard, so a report-less stub greened on THAT instead and the
        moved-HEAD guard could be deleted with all 113 tests still passing — a
        fault-injection that had stopped injecting the fault it names.
        """
        repo, env, _g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "echo 'x = 1' >> src/thing.py\n"
            "git add -A && git commit -qm 'reviewer wrote this'\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            'printf \'{"result": "clean, and I committed"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reviewer" in r.stderr.lower()
        assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_reviewer_crash_refuses_cleanly_surfacing_its_stderr(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, raw="not json at all", exit_code=1)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_reviewer_non_json_output_refuses_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, raw="not json at all", exit_code=0)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_dry_run_review_launches_nothing(self, tmp_path):
        """N4: --dry-run is on the shared parser; silently spawning a real opus
        session on a dry run is an expensive surprise."""
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review", "--dry-run")
        assert r.returncode == 0 and launches(tmp_path) == []


class TestTrunkMotionGuards:
    """story-008 AC 2: drift is reviewed in-pipeline, on the delta only."""

    def test_a_bare_re_review_cannot_clear_the_trunk_guard(self, tmp_path):
        """Re-running review after trunk motion used to re-baseline the guard while
        the reviewer saw nothing new: merge-base does not move when trunk advances.
        The refusal must hold, and `git merge <trunk>` must be what clears it —
        a guard whose remediation does not work is a wall."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "other.txt").write_text("someone else landed a story\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved")
        g("checkout", "-q", "story-042-branch")
        assert close(repo, env, "land").returncode == 2
        bare = close(repo, env, "review")
        assert bare.returncode == 2 and "git merge main" in bare.stderr
        g("merge", "-q", "main", "-m", "merge trunk")
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "someone else landed a story" in (repo / "other.txt").read_text()


class TestSelfCloseRefusal:
    """story-008 AC 6: the hard property behind TEAMMATE.md's declaration."""

    def test_non_lead_roles_are_refused(self, tmp_path):
        """N3: parametrized, or this fault-injects the AC and not the widening."""
        for role in ("teammate", "reviewer", "sprint-close", ""):
            repo, env, _g = make_repo(tmp_path / f"r-{role or 'empty'}")
            r = close(repo, {**env, "XP_ROLE": role}, "review")
            assert r.returncode == 2, f"XP_ROLE={role!r} was allowed to close"
            assert "close" in r.stderr.lower()

    def test_the_lead_passes_the_same_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, {**env, "XP_ROLE": "lead"}, "review").returncode == 0


class TestLandBookkeeping:
    """story-008 AC 3/7/8: what land does after the merge lands."""

    def with_origin(self, tmp_path, push_story_branch=True):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        if push_story_branch:
            g("push", "-q", "-u", "origin", "story-042-branch")
        return repo, env, g

    def test_land_pushes_trunk_and_deletes_the_story_branch_both_sides(self, tmp_path):
        repo, env, g = self.with_origin(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "story-042-branch" not in g("branch", "--list").stdout
        assert "story-042-branch" not in g("ls-remote", "--heads", "origin").stdout
        local_main = g("rev-parse", "main").stdout.strip()
        assert g("rev-parse", "origin/main").stdout.strip() == local_main

    def test_unpushed_story_branch_does_not_produce_a_spurious_failure(self, tmp_path):
        """N2b: a story closed with `spawn --in-place` never pushed its branch —
        this repo's own story-007 did exactly that."""
        repo, env, g = self.with_origin(tmp_path, push_story_branch=False)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "story-042-branch" not in g("branch", "--list").stdout

    def test_incomplete_bookkeeping_exits_nonzero_not_zero(self, tmp_path):
        """N2a: a warning above 'closed.' is a hand-step the lead will miss."""
        repo, env, _g = self.with_origin(tmp_path)
        close(repo, env, "review")
        subprocess.run(["rm", "-rf", str(tmp_path / "origin.git")], check=True)
        r = close(repo, env, "land")
        assert r.returncode == 3, "push failure must not read as success"
        assert "git push origin main" in r.stderr
        # the merge, flip and amend all landed and merge_sha is on a ref — only a
        # failed AMEND orphans it. Withholding the record here made the close
        # unrecordable by any command, because the card already reads [done].
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["story"] == "story-042"
        assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_land_clears_the_stories_test_status_markers(self, tmp_path):
        """AC 3: cleared, never greened — close.py may not forge another
        session's measurement (DESIGN §4)."""
        repo, env, _g = make_repo(tmp_path)
        d = tmp_path / "data" / "markers"
        d.mkdir(parents=True, exist_ok=True)
        stale = d / "sess-old.story-042.test-status"
        stale.write_text(json.dumps({"story": "story-042", "verify": "true", "red": True}))
        keep = d / "sess-old.story-099.test-status"
        keep.write_text(json.dumps({"story": "story-099", "verify": "true", "red": True}))
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        assert not stale.exists()
        assert keep.exists(), "another story's gate state is not this close's business"

    def test_close_record_is_appended_and_names_the_real_merge_commit(self, tmp_path):
        """AC 8 + G6: a sha read before the --amend is on no ref."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        lines = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["story"] == "story-042" and rec["title"] == "demo story"
        assert rec["rounds"] == [{"fixed": [], "blocking": [], "noted": []}]
        assert rec["merge_sha"] == g("rev-parse", "main").stdout.strip()
        assert g("cat-file", "-t", rec["merge_sha"]).stdout.strip() == "commit"

    def test_a_second_close_appends_rather_than_overwriting(self, tmp_path):
        """N7: overwriting would be the project-global mutable marker
        constraints #10 forbids, and would lose the sprint's history."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        close(repo, env, "land")
        plan = repo / ".xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — second   [in-progress]\nVerify: true\n"
        )
        g("add", "-A")
        g("commit", "-qm", "second story card")
        g("checkout", "-qb", "story-043-branch")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "second story work")
        for action in ("review", "land"):
            subprocess.run(
                [sys.executable, str(CLOSE), "story", "story-043", action, "--merge-mode", "local"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
        records = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert [json.loads(r)["story"] for r in records] == ["story-042", "story-043"]


class TestStoryReviewFindings:
    """story-008 close review, run by this story's own pipeline."""

    def test_a_comment_on_the_tests_header_cannot_silence_the_story_tier(self, tmp_path):
        """G2: the twin of the roles: bug, and this copy fails OPEN — a red tier
        is skipped and the story closes green."""
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:   # fast / story / full\n  story: false\n"
        )
        g("add", "-A")
        g("commit", "-qm", "commented tests header")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_a_reviewer_that_writes_without_committing_is_also_refused(self, tmp_path):
        """G5: the `or dirtied` half was vacuous — Bash is deliberately not
        denied, so an uncommitted scratch write is the likelier defect."""
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\necho 'scratch' >> src/thing.py\nprintf '{\"result\": \"VERDICT: clean\"}'\n"
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reviewer" in r.stderr.lower()

    def test_a_dashless_card_header_does_not_poison_the_close_log(self, tmp_path):
        """G6: _log_close reimplemented card_title without its guard."""
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("#### story-042 — demo story", "#### story-042"))
        g("add", "-A")
        g("commit", "-qm", "dashless header")
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert "####" not in rec["title"]

    def test_a_broken_plugin_install_refuses_instead_of_tracebacking(self, tmp_path):
        """G7: review.charter() read the agent file unguarded, in a module where
        nine tests assert no traceback reaches the lead."""
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys, pathlib; sys.path.insert(0, {str(CLOSE.parent)!r}); import review;"
                " review.PLUGIN_ROOT = pathlib.Path('/nonexistent'); review.charter()",
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0 and "Traceback" not in r.stderr

    def test_pr_mode_records_the_real_merge_and_lands_done_on_trunk(self, tmp_path):
        """G3: pr mode is the argparse DEFAULT and the only mode a release: story
        consumer gets, and no test executed it to a merge. It recorded the story
        branch's HEAD as the merge sha — on a branch gh is about to delete — and
        committed the [done] flip onto the story branch, so trunk never learned."""
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            '#!/bin/sh\ncase "$*" in *"pr merge"*) git push -q origin HEAD:main ;; esac\n'
        )
        gh.chmod(0o755)
        close(repo, env, "review")
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr + r.stdout
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        ancestor = g("merge-base", "--is-ancestor", rec["merge_sha"], "origin/main")
        assert ancestor.returncode == 0, "recorded sha is not on trunk"
        assert "[done]" in g("show", "origin/main:.xp/plan.md").stdout, "trunk never learned"


class TestLandFailureModes:
    """story-008 close review, round 2 (the delta the drift path reviewed)."""

    def pr_repo(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'case "$*" in *"pr merge"*)\n'
            "  git checkout -q -b _pr origin/main\n"
            '  git merge -q --no-ff -m "Merge PR" story-042-branch\n'
            "  git push -q origin _pr:main\n"
            "  git checkout -q main\n"
            "  git branch -qD _pr\n"
            # server-side delete, as the real gh API does: the tracking ref is
            # deliberately left stale, because `git fetch` without --prune keeps it
            f"  git --git-dir={origin} update-ref -d refs/heads/story-042-branch\n"
            "  git branch -qD story-042-branch ;; esac\n"
        )
        gh.chmod(0o755)
        return repo, env, g

    def land_pr(self, repo, env):
        return subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_a_failing_amend_hook_does_not_traceback_or_lose_the_flip(self, tmp_path):
        """F1: git() defaults check=True, and the amend re-runs the commit wall
        on a tree that just gained a merge — a hook failure raised, leaving the
        merge landed and the plan flip abandoned."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        r = close(repo, env, "land")
        assert "Traceback" not in r.stderr, r.stderr
        assert r.returncode != 0, "an abandoned plan flip must not read as success"
        assert "amend" in (r.stderr + r.stdout).lower()
        assert "[done]" in (repo / ".xp" / "plan.md").read_text(), "the flip was discarded"

    def test_pr_merge_sha_is_the_merge_not_the_story_tip(self, tmp_path):
        """F2: --is-ancestor cannot tell them apart — the story tip is an
        ancestor of the merge too, so the assertion passed against the defect."""
        repo, env, g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        story_head = g("rev-parse", "HEAD").stdout.strip()
        assert self.land_pr(repo, env).returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["merge_sha"] != story_head, "recorded the story tip, not the PR merge"

    def test_pr_mode_also_deletes_the_local_story_branch(self, tmp_path):
        """F3: AC 7 was met in local mode only. gh runs FROM the story branch,
        so --delete-branch cannot remove it locally."""
        repo, env, g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        assert self.land_pr(repo, env).returncode == 0
        assert "story-042-branch" not in g("branch", "--list").stdout

    def test_pr_dry_run_previews_the_steps_that_actually_run(self, tmp_path):
        """F4: the preview still printed a bare `git push` that no longer runs,
        and omitted the three post-merge steps the delta added."""
        repo, env, _g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        for step in (
            "git fetch -q origin",
            "git checkout -q main",
            "git merge --ff-only origin/main",
            "git branch -d story-042-branch",
        ):
            assert step in r.stdout, f"preview omits {step!r}"
        assert "\ngit push\n" not in r.stdout, "previewed a bare push that no longer runs"

    def test_a_successful_pr_close_does_not_cry_wolf_on_exit_3(self, tmp_path):
        """R3F1: gh --delete-branch had already removed the branch, so the
        unconditional delete 'failed' and every successful pr close exited 3
        naming a command that fails again on re-run."""
        repo, env, _g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        r = self.land_pr(repo, env)
        assert r.returncode == 0, f"clean close reported incomplete: {r.stderr}"
        assert "incomplete" not in r.stderr

    def test_a_failed_amend_writes_no_close_record(self, tmp_path):
        """R3F2: the record is the fact layer AC 8 exists for — it must not name
        a sha that close.py's own printed remediation orphans."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        assert close(repo, env, "land").returncode == 3
        assert not (tmp_path / "data" / "closes.jsonl").exists(), "recorded an incomplete close"
        assert (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_local_dry_run_previews_the_destructive_steps_too(self, tmp_path):
        """R3F4: F4's rule was applied to the pr arm only, and local is the mode
        release: sprint forces — the un-fixed copy is the one in daily use."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "git branch -d story-042-branch" in r.stdout
        # make_repo has NO remote, and both pushes are runtime-guarded on one —
        # previewing them here is the same overstatement F4 was filed for
        assert "git push origin" not in r.stdout, "previewed pushes that never run"


class TestFullReviewFindings:
    """story-008 close review, round 5 — the first review over the whole story."""

    def test_a_full_re_review_appends_rather_than_erasing_prior_rounds(self, tmp_path):
        """R5F1: the non-delta path reset verdicts while the delta path appended
        — the same rule fixed in one of its two implementations. The merge body
        then labelled the survivor 'round 1', asserting round 1 found what round
        2 found. This is the exact workflow the full_sha bug prescribes."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, report={"fixed": [], "blocking": ["round one blocker"], "noted": []}
        )
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 7\n")
        g("add", "-A")
        g("commit", "-qm", "lead fixes the findings")
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [], "noted": ["round two note"]})
        close(repo, env, "review")
        rounds = marker(tmp_path)["rounds"]
        assert [r["blocking"] for r in rounds] == [["round one blocker"], []]
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B", "main").stdout
        assert "Review round 1: 0 fixed · 1 blocking · 0 noted" in body
        assert "blocking: round one blocker" in body
        assert "Review round 2: 0 fixed · 0 blocking · 1 noted" in body


CLEAN = {"fixed": [], "blocking": [], "noted": []}
PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"


def marker_file(tmp_path, story_id="story-042"):
    return tmp_path / "data" / "markers" / f"{story_id}.close.json"


class TestStructuredGate:
    """story-012a: the report replaces the VERDICT line, and land never spawns."""

    def test_land_refuses_on_drift_naming_review_and_spawns_nothing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "lead fix after review")
        r = close(repo, env, "land")
        assert r.returncode == 2
        assert "close.py story story-042 review" in r.stderr
        assert len(launches(tmp_path)) == 1, "land spawned the reviewer"

    def test_land_on_drift_is_idempotent(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "lead fix after review")
        first, second = close(repo, env, "land"), close(repo, env, "land")
        assert first.returncode == second.returncode == 2
        # the SAME refusal twice, not "refuses, then proceeds": land used to review
        # on the first call by construction, so a close cost two invocations minimum
        assert first.stderr == second.stderr
        assert "close.py story story-042 review" in first.stderr
        assert len(launches(tmp_path)) == 1

    def test_a_second_round_reviews_the_whole_story_diff_not_a_delta(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "more story work")
        assert close(repo, env, "review").returncode == 0
        # `-A = 1` is the trunk-side line only a merge-base..HEAD diff carries; a
        # delta (reviewed..HEAD) would show `-A = 2`. The inverse of the assertion
        # the deleted delta path used to earn.
        assert "-A = 1" in launches(tmp_path)[1]["stdin"]

    def test_review_refuses_while_trunk_is_ahead_of_the_merge_base(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        (repo / "other.py").write_text("x = 1\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on trunk")
        g("checkout", "-q", "story-042-branch")
        stub_reviewer(tmp_path, report=CLEAN)
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert "merge main" in r.stderr
        assert launches(tmp_path) == [], "opus was spent on a diff that cannot cover the merge"

    def test_shown_sha_is_head_at_the_end_of_a_clean_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        assert marker(tmp_path)["shown_sha"] == g("rev-parse", "HEAD").stdout.strip()

    def test_land_refuses_when_the_recorded_base_is_not_todays_merge_base(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        state = json.loads(marker_file(tmp_path).read_text())
        state["review_base"] = "0" * 40  # construct the condition; never observe it
        marker_file(tmp_path).write_text(json.dumps(state))
        r = close(repo, env, "land")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_report_items_are_capped_at_the_write(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={"fixed": ["x" * 5000], "blocking": [], "noted": [f"n{i}" for i in range(200)]},
        )
        assert close(repo, env, "review").returncode == 0
        round1 = marker(tmp_path)["rounds"][0]
        assert len(round1["fixed"][0]) <= 400
        assert len(round1["noted"]) <= 20

    def test_a_prose_only_reviewer_is_refused_and_its_output_is_printed_first(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, result="VERDICT: clean\nthe findings I spent ten minutes on", report=None
        )
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert "the findings I spent ten minutes on" in r.stdout, "a good review was destroyed"
        assert not marker_file(tmp_path).exists(), "a round was recorded without a report"

    def test_an_unparseable_report_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report="{not json at all")
        r = close(repo, env, "review")
        # name the real refusal: "exit 2" alone also greens on a stub that dies
        # because no REPORT_PATH was ever offered to it
        assert r.returncode == 2 and "not JSON" in r.stderr
        assert not marker_file(tmp_path).exists()

    def test_a_report_without_the_three_keys_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report={"findings": ["something"]})
        r = close(repo, env, "review")
        assert r.returncode == 2 and "blocking" in r.stderr, "the refusal must name what is missing"
        assert not marker_file(tmp_path).exists()

    def test_a_planted_report_cannot_certify_a_round_that_wrote_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        (reports / "story-042.round-1.json").write_text(
            json.dumps({"fixed": ["a fix that never happened"], "blocking": [], "noted": []})
        )
        stub_reviewer(tmp_path, report=None)
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert not marker_file(tmp_path).exists(), "a stale report certified an empty round"

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={"fixed": [], "blocking": ["B1: the new guard is vacuous"], "noted": []},
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "B1: the new guard is vacuous" in r.stderr

    def test_land_prints_noted_items_for_filing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, report={"fixed": [], "blocking": [], "noted": ["N1: this name misleads"]}
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "N1: this name misleads" in r.stdout and "PROCESS.md" in r.stdout

    def test_three_rounds_are_labelled_by_their_true_round_number(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        for i in (1, 2, 3):
            stub_reviewer(
                tmp_path, report={"fixed": [f"round {i} fix"], "blocking": [], "noted": []}
            )
            assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B").stdout
        for i in (1, 2, 3):
            assert f"Review round {i}" in body and f"round {i} fix" in body


class TestStoryReviewFindings012a:
    """Blocking findings from story-012a's own close review."""

    def test_pr_mode_review_refuses_on_ORIGIN_trunk_motion(self, tmp_path):
        """B1: the new guard read the LOCAL trunk ref only. pr mode — the argparse
        default — integrates against origin, which the local ref never tracks, so a
        bare re-review still cleared land's origin guard with the reviewer seeing
        nothing new. The exact twin AC 4 claims to close, on the other axis."""
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        old = g("rev-parse", "HEAD~1").stdout.strip()
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        g("update-ref", "refs/remotes/origin/main", old)
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "review")
        assert r.returncode == 2, "a bare re-review re-baselined the origin guard"
        assert "git merge" in r.stderr

    def test_the_newest_round_survives_the_close_detail_bound(self, tmp_path):
        """B3: the cap kept the HEAD of the joined string, so one long early round
        silently dropped the round that actually gated the merge."""
        sys.path.insert(0, str(CLOSE.parent))
        import session_start

        record = {
            "rounds": [
                {"fixed": ["x" * 2000], "blocking": [], "noted": []},
                {"fixed": [], "blocking": [], "noted": []},
                {"fixed": [], "blocking": ["R3-THE-BLOCKER-THAT-GATED-THE-MERGE"], "noted": []},
            ]
        }
        detail = session_start._close_detail(record)
        assert "R3-THE-BLOCKER-THAT-GATED-THE-MERGE" in detail
        assert len(detail) <= session_start.CLOSE_CAP + 120


class TestShippedProseMatchesTheMechanism:
    """The prose is what a consuming project believes. story-012a AC 11/12."""

    def test_no_verdict_token_survives_in_the_shipped_prose(self):
        for path in (
            PLUGIN / "skills" / "story-close" / "SKILL.md",
            PLUGIN / "PROCESS.md",
            PLUGIN / "scripts" / "close.py",  # --help is the first surface a lead reads
        ):
            head = path.read_text().split("import argparse")[0]
            assert "VERDICT" not in head, f"{path.name} still ships the deleted gate"
            # found by USING the pipeline: land refuses unless the last round covers
            # HEAD, and every fix moves HEAD, so this promise cannot be kept
            assert "close WITHOUT re-review" not in head, f"{path.name} promises what land refuses"

    def test_the_charter_names_the_report_path_and_the_route_left_open(self):
        charter = (PLUGIN / "agents" / "story-reviewer.md").read_text()
        assert "REPORT_PATH" in charter
        assert "heredoc" in charter.lower(), "Write is denied; the only route must be named"

    def test_the_plan_reviewer_charter_asks_for_a_file(self):
        assert (
            "write your findings to a file"
            in (PLUGIN / "agents" / "plan-reviewer.md").read_text().lower()
        )
