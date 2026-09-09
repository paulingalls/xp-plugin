import json
from pathlib import Path

from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import close, free, free_repo, make_repo, marker_file
from sprint_helpers import PLAN, SPRINT_ID, marker_path, snapshot, sprint
from sprint_helpers import make_repo as sprint_repo
from test_close_salvage import FIXED, KILLED, dying_reviewer

FREE_PATCH = """diff --git a/src/free.py b/src/free.py
--- a/src/free.py
+++ b/src/free.py
@@ -1 +1,2 @@
 B = 1
+guarded = True
"""


def branch_refs(g):
    return g("branch", "--format=%(refname:short)").stdout.splitlines()


def previewed(result):
    """Exit 0 AND a line that SAYS it previewed. Silence and exit 0 is byte-identical
    to the dropped flag every case below guards, so the artifact assertions alone
    cannot tell the fix from the bug."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("dry run:"), result.stdout


class DroppedDryRunCases:
    def test_free_start_dry_run_does_not_create_the_branch(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        before = branch_refs(g)

        preview = free(repo, env, "fix-typo", "start", "--dry-run")

        previewed(preview)
        assert branch_refs(g) == before
        started = free(repo, env, "fix-typo", "start")
        assert started.returncode == 0, started.stderr
        assert len(branch_refs(g)) == len(before) + 1
        assert any(name.endswith("-fix-typo") for name in branch_refs(g))

    def test_free_salvage_dry_run_preserves_the_unrecorded_round(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        tree = spawn_free(repo, env, g, tmp_path, key)
        dying_reviewer(tmp_path, patch=FREE_PATCH)
        assert free(tree, env | KILLED, "fix-typo", "review").returncode == 2
        data = Path(env["XP_DATA"])
        assert list((data / "reports").glob("*.json"))
        assert list((data / "reports").glob("*.patch"))
        before = snapshot(data)
        head = g("-C", str(tree), "rev-parse", "HEAD").stdout.strip()

        preview = free(tree, env, "fix-typo", "salvage", "--dry-run")

        previewed(preview)
        assert snapshot(data) == before
        assert g("-C", str(tree), "rev-parse", "HEAD").stdout.strip() == head

    def test_free_post_merge_dry_run_does_not_cut_the_patch_tag(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        tree = spawn_free(repo, env, g, tmp_path, key)
        reviewed = free(tree, env, "fix-typo", "review")
        assert reviewed.returncode == 0, reviewed.stderr
        merged = g("merge", "-q", "--no-ff", branch, "-m", "merge free release")
        assert merged.returncode == 0, merged.stderr
        data = Path(env["XP_DATA"])
        before = snapshot(data)
        tags = g("tag", "--list").stdout
        assert tree.exists() and marker_file(tmp_path, key).exists()

        preview = free(repo, env, "fix-typo", "post-merge", "--dry-run")

        previewed(preview)
        assert g("tag", "--list").stdout == tags
        assert snapshot(data) == before
        assert tree.exists() and marker_file(tmp_path, key).exists()

    def test_sprint_start_dry_run_is_inert_and_real_start_opens(self, tmp_path):
        planned = PLAN.replace("[in-progress]", "[planned]", 1).replace(
            "#### story-042 — done thing   [done]",
            "#### story-042 — done thing   [planned]",
        )
        repo, env, _g = sprint_repo(tmp_path, plan=planned)
        plan = Path(env["XP_DATA"]) / "plan.md"
        record = Path(env["XP_DATA"]) / "sprint_branch"
        record.unlink()
        before = plan.read_bytes()

        preview = sprint(repo, env, "start", "--dry-run")

        previewed(preview)
        assert plan.read_bytes() == before
        assert not record.exists()
        opened = sprint(repo, env, "start")
        assert opened.returncode == 0, opened.stderr
        assert "[in-progress]" in plan.read_text()
        assert record.read_text().strip() == "sprint-002"

    def test_sprint_start_dry_run_over_an_open_sprint_previews_the_close_batch(self, tmp_path):
        """The OTHER leg `sprint start` spells: with a branch already recorded it
        re-runs the CLOSE checks and opens nothing, so a preview saying `opens`
        names an action this invocation would not take."""
        repo, env, _g = sprint_repo(tmp_path)
        data = Path(env["XP_DATA"])
        before = snapshot(data)

        preview = sprint(repo, env, "start", "--dry-run")

        previewed(preview)
        assert "close checks" in preview.stdout and "opens" not in preview.stdout
        assert snapshot(data) == before

    def test_sprint_salvage_dry_run_preserves_reports_and_marker(self, tmp_path):
        repo, env, _g = sprint_repo(tmp_path)
        report = (
            Path(env["XP_DATA"]) / "reports" / "sprint" / f"{SPRINT_ID}.find-state.round-1.json"
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(FIXED))
        body = report.read_bytes()
        marker = marker_path(tmp_path)
        assert not marker.exists()

        preview = sprint(repo, env, "salvage", "--dry-run")

        previewed(preview)
        assert report.read_bytes() == body
        assert not marker.exists()

    def test_sprint_post_merge_dry_run_does_not_cut_the_minor_tag(self, tmp_path):
        repo, env, g = sprint_repo(tmp_path)
        g("tag", "v0.2.0", "main")
        g("checkout", "-q", "main")
        merged = g("merge", "-q", "--no-ff", "sprint-002", "-m", "merge sprint release")
        assert merged.returncode == 0, merged.stderr
        tags = g("tag", "--list").stdout
        record = Path(env["XP_DATA"]) / "sprint_branch"
        branch = record.read_bytes()

        preview = sprint(repo, env, "post-merge", "--dry-run")

        previewed(preview)
        assert g("tag", "--list").stdout == tags
        assert record.read_bytes() == branch

    def test_sprint_salvage_dry_run_does_not_shift_a_queued_round_down(self, tmp_path):
        """The OTHER salvage guard, which the round-1 cases never reach: with
        nothing at this round a real salvage RENAMES the round above it down, and
        no artifact of the recorded round exists afterwards to notice it by."""
        repo, env, _g = sprint_repo(tmp_path)
        data = Path(env["XP_DATA"])
        queued = data / "reports" / "sprint" / f"{SPRINT_ID}.find-state.round-2.json"
        queued.parent.mkdir(parents=True, exist_ok=True)
        queued.write_text(json.dumps(FIXED))
        before = snapshot(data)

        preview = sprint(repo, env, "salvage", "--dry-run")

        previewed(preview)
        assert snapshot(data) == before

    def test_story_salvage_dry_run_does_not_shift_a_queued_round_down(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        data = Path(env["XP_DATA"])
        for relative, body in (
            ("reports/story-042.round-2.json", json.dumps(FIXED)),
            ("reports/story-042.round-2.patch", FREE_PATCH),
            ("markers/story-042.round-2.launch", json.dumps({"head": "0" * 40})),
        ):
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        before = snapshot(data)

        preview = close(repo, env, "salvage", "--dry-run")

        previewed(preview)
        assert snapshot(data) == before

    def test_story_salvage_dry_run_preserves_the_unrecorded_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        data = Path(env["XP_DATA"])
        assert list((data / "reports").glob("*.json"))
        assert list((data / "reports").glob("*.patch"))
        before = snapshot(data)
        head = g("rev-parse", "HEAD").stdout.strip()
        assert not marker_file(tmp_path).exists()

        preview = close(repo, env, "salvage", "--dry-run")

        previewed(preview)
        assert snapshot(data) == before
        assert g("rev-parse", "HEAD").stdout.strip() == head
        assert not marker_file(tmp_path).exists()
