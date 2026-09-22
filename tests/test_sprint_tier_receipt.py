"""The sprint full-tier receipt names the exact tree the command passed on."""

import json
import subprocess
import sys

import pytest
from sprint_helpers import (
    CONFIG,
    PLUGIN,
    head,
    make_repo,
    marker_path,
    record_reviews,
    sprint,
    staged_stub,
    work,
)

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))
import overlap


def config_for(command):
    return CONFIG.replace("full: true", f"full: {command}")


def state(tmp_path):
    path = marker_path(tmp_path)
    return json.loads(path.read_text()) if path.exists() else {}


def tree(g):
    return g("write-tree").stdout.strip()


def counted_repo(tmp_path, command=""):
    events = tmp_path / "tier-events"
    tier = command or f"printf x >> {events}"
    repo, env, g = make_repo(tmp_path, config=config_for(tier))
    return repo, env, g, events, tier


def run_count(events):
    return len(events.read_text()) if events.exists() else 0


def test_a_nonpassing_receipt_never_matches_the_shipping_tree():
    receipt = {
        "tier": "full",
        "command": "true",
        "tree": "same-tree",
        "head": "head",
        "verdict": "failed",
        "ran_by": "start",
        "reused": False,
    }

    assert overlap._receipt_matches(receipt, "true", "same-tree") == (False, "unreadable")


def add_origin(tmp_path, repo, env, g):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    g("remote", "add", "origin", str(origin))
    assert g("push", "-q", "origin", "main").returncode == 0


def advance_origin(repo, g, filename=None, content="", empty=False):
    sprint_head = head(repo, None)
    g("checkout", "-q", "main")
    if filename:
        (repo / filename).write_text(content)
        g("add", filename)
    args = (
        ("commit", "-qm", "trunk moved", "--allow-empty")
        if empty
        else (
            "commit",
            "-qm",
            "trunk moved",
        )
    )
    assert g(*args).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    g("checkout", "-q", "sprint-002")
    assert head(repo, None) == sprint_head


class TestStartReceipt:
    def test_start_emits_close_material_without_running_the_full_tier(self, tmp_path):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"rounds": [{"sentinel": "preserved"}]}))

        result = sprint(repo, env, "start")

        assert result.returncode == 0, result.stderr
        assert run_count(events) == 0
        assert "full_tier" not in state(tmp_path)
        assert "notes to triage" in result.stdout
        assert "Session digest" in result.stdout
        assert state(tmp_path)["rounds"] == [{"sentinel": "preserved"}]

    @pytest.mark.parametrize("kind", ["tracked", "untracked"])
    def test_start_refuses_dirt_before_the_batch(self, tmp_path, kind):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        target = repo / ("src.py" if kind == "tracked" else "untracked.py")
        target.write_text(target.read_text() + "DIRT = 1\n" if target.exists() else "DIRT = 1\n")

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "before the close batch" in result.stderr.lower()
        assert run_count(events) == 0
        assert not marker_path(tmp_path).exists() or "full_tier" not in state(tmp_path)

    @pytest.mark.parametrize("kind", ["tracked", "untracked"])
    def test_land_refuses_dirt_created_by_the_falsifier_batch(self, tmp_path, kind):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        generated = repo / ("src.py" if kind == "tracked" else "generated.py")
        before = generated.read_text() if generated.exists() else None
        falsifier = f"printf '\\nDIRT = 1' >> {generated}" if before else f"touch {generated}"
        result = work(
            repo,
            env,
            "debt",
            "--claim",
            "batch can move the tree",
            "--falsifier",
            falsifier,
            "--files",
            "generated.py",
        )
        assert result.returncode == 0, result.stderr
        generated.write_text(before) if before is not None else generated.unlink()

        assert sprint(repo, env, "start").returncode == 0
        record_reviews(tmp_path, repo, env)
        result = sprint(repo, env, "land")

        assert result.returncode == 2 and "dirty" in result.stderr.lower()
        assert run_count(events) == 0

    def test_an_initial_unfinished_open_still_records_without_close_checks(self, tmp_path):
        plan = """# plan
### Sprint 2
#### story-042 — unfinished   [ready]
Verify: true
"""
        events = tmp_path / "tier-events"
        repo, env, _g = make_repo(tmp_path, plan=plan, config=config_for(f"touch {events}"))
        (tmp_path / "data" / "sprint_branch").unlink()
        (repo / "untracked.py").write_text("DIRT = 1\n")

        result = sprint(repo, env, "start")

        assert result.returncode == 0 and "close checks wait" in result.stdout
        assert not events.exists()

    @pytest.mark.parametrize("kind", ["tracked", "untracked", "commit"])
    def test_start_does_not_run_a_tier_that_moves_the_tree(self, tmp_path, kind):
        if kind == "tracked":
            command = "printf '\\nMOVED = 1' >> src.py"
        elif kind == "untracked":
            command = "touch generated.py"
        else:
            command = "printf '\\nMOVED = 1' >> src.py && git commit -qam tier-motion"
        repo, env, g, _events, _tier = counted_repo(tmp_path, command)
        before, old_head = (repo / "src.py").read_bytes(), head(repo, env)

        result = sprint(repo, env, "start")

        assert result.returncode == 0, result.stderr
        assert (repo / "src.py").read_bytes() == before and head(repo, env) == old_head
        assert not g("status", "--porcelain").stdout
        assert not (repo / "generated.py").exists()
        assert "full_tier" not in state(tmp_path)

    def test_start_reentry_preserves_the_land_receipt(self, tmp_path):
        flag = tmp_path / "red"
        repo, env, _g, _events, _tier = counted_repo(tmp_path, f"test ! -e {flag}")
        assert sprint(repo, env, "start").returncode == 0
        record_reviews(tmp_path, repo, env)
        assert sprint(repo, env, "land").returncode == 2
        before = marker_path(tmp_path).read_bytes()
        flag.touch()
        result = sprint(repo, env, "start")
        assert result.returncode == 0 and marker_path(tmp_path).read_bytes() == before

    def test_start_refuses_an_unreadable_sprint_marker_without_overwriting_it(self, tmp_path):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        before = path.read_bytes()

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "unreadable sprint marker" in result.stderr.lower()
        assert "Traceback" not in result.stderr and run_count(events) == 0
        assert path.read_bytes() == before

    def test_start_does_not_run_a_tier_that_locks_the_index(self, tmp_path):
        repo, env, _g, _events, _tier = counted_repo(tmp_path, "touch .git/index.lock")

        result = sprint(repo, env, "start")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Traceback" not in result.stderr
        assert not (repo / ".git" / "index.lock").exists()
        assert "full_tier" not in state(tmp_path)

    def test_land_refuses_when_git_cannot_name_the_tree(self, tmp_path):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".git" / "index.lock").touch()

        result = sprint(repo, env, "land")

        assert result.returncode == 2 and "write tree" in result.stderr.lower()
        assert "Traceback" not in result.stderr and run_count(events) == 0


class TestFullTierReceipt:
    def test_review_fix_is_measured_once_by_land(self, tmp_path):
        repo, env, g, events, _tier = counted_repo(tmp_path)
        staged_stub(
            tmp_path,
            patches=[("fix", "src.py", "C = 2")],
            find={"fixed": [], "blocking": ["FIXED"], "noted": []},
            verify={"fixed": [], "blocking": ["FIXED"], "noted": []},
            fix={"fixed": ["FIXED"], "blocking": [], "noted": []},
        )
        assert sprint(repo, env, "start").returncode == 0
        assert run_count(events) == 0
        reviewed = sprint(repo, env, "review")
        assert reviewed.returncode == 0, reviewed.stderr
        assert run_count(events) == 0 and "C = 2" in (repo / "src.py").read_text()
        reviewed_tree = tree(g)

        landed = sprint(repo, env, "land")

        assert landed.returncode == 2 and "gh" in landed.stderr
        assert run_count(events) == 1
        assert state(tmp_path)["full_tier"]["tree"] == reviewed_tree
        assert state(tmp_path)["full_tier"]["ran_by"] == "land"

    def start_and_review(self, tmp_path, origin=False):
        repo, env, g, events, tier = counted_repo(tmp_path)
        if origin:
            add_origin(tmp_path, repo, env, g)
        assert sprint(repo, env, "start").returncode == 0
        assert run_count(events) == 0
        receipt = {
            "tier": "full",
            "command": tier,
            "tree": tree(g),
            "head": head(repo, env),
            "verdict": "passed",
            "ran_by": "start",
            "reused": False,
        }
        events.write_text("x")
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"full_tier": receipt}))
        record_reviews(tmp_path, repo, env)
        return repo, env, g, events, tier, receipt

    def assert_land_ran(self, tmp_path, repo, env, events, count):
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "gh" in result.stderr, result.stdout + result.stderr
        assert run_count(events) == count
        assert (
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout
            == ""
        )
        merge_head = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
        )
        assert merge_head.returncode != 0
        return result

    def test_land_reuses_the_start_receipt_for_the_identical_shipping_tree(self, tmp_path):
        repo, env, _g, events, tier, receipt = self.start_and_review(tmp_path)

        result = self.assert_land_ran(tmp_path, repo, env, events, 1)

        saved = state(tmp_path)["full_tier"]
        assert saved == receipt | {"reused": True}
        for value in (str(marker_path(tmp_path)), tier, receipt["tree"], receipt["head"]):
            assert value in result.stdout

    def test_committed_code_after_start_reruns_the_tier(self, tmp_path):
        repo, env, g, events, _tier, receipt = self.start_and_review(tmp_path)
        (repo / "after.py").write_text("AFTER = 1\n")
        g("add", "after.py")
        g("commit", "-qm", "triage moved code")
        record_reviews(tmp_path, repo, env)

        self.assert_land_ran(tmp_path, repo, env, events, 2)

        saved = state(tmp_path)["full_tier"]
        assert saved["ran_by"] == "land" and not saved["reused"]
        assert saved["tree"] != receipt["tree"]

    def test_origin_motion_reruns_with_sprint_head_held_at_start(self, tmp_path):
        repo, env, g, events, _tier, receipt = self.start_and_review(tmp_path, origin=True)
        advance_origin(repo, g, "trunk.py", "TRUNK = 1\n")
        assert head(repo, env) == receipt["head"]

        self.assert_land_ran(tmp_path, repo, env, events, 2)

        saved = state(tmp_path)["full_tier"]
        assert saved["tree"] != receipt["tree"] and saved["ran_by"] == "land"

    def test_origin_history_motion_with_the_same_tree_still_reuses(self, tmp_path):
        repo, env, g, events, _tier, receipt = self.start_and_review(tmp_path, origin=True)
        advance_origin(repo, g, empty=True)

        result = self.assert_land_ran(tmp_path, repo, env, events, 1)

        assert "reused" in result.stdout.lower()
        assert state(tmp_path)["full_tier"] == receipt | {"reused": True}

    def test_a_command_mismatch_reruns_even_when_the_receipt_tree_matches(self, tmp_path):
        """An honest writer cannot produce this while the command is in-tree;
        doctoring the persisted receipt isolates its command-integrity guard."""
        repo, env, g, events, old, _receipt = self.start_and_review(tmp_path)
        new = f"printf yy >> {events}"
        config = repo / ".xp" / "config.yml"
        config.write_text(config.read_text().replace(old, new))
        g("add", str(config.relative_to(repo)))
        g("commit", "-qm", "change full command")
        record_reviews(tmp_path, repo, env)
        marker = marker_path(tmp_path)
        current = state(tmp_path)
        current["full_tier"]["tree"] = tree(g)
        marker.write_text(json.dumps(current))

        self.assert_land_ran(tmp_path, repo, env, events, 3)

        assert state(tmp_path)["full_tier"]["command"] == new

    @pytest.mark.parametrize("receipt_state", ["missing", "unreadable"])
    def test_missing_and_unreadable_receipts_are_distinct_rerun_states(
        self, tmp_path, receipt_state
    ):
        repo, env, _g, events, _tier, _receipt = self.start_and_review(tmp_path)
        marker = marker_path(tmp_path)
        current = state(tmp_path)
        if receipt_state == "missing":
            current.pop("full_tier")
        else:
            current["full_tier"] = None
        marker.write_text(json.dumps(current))

        result = self.assert_land_ran(tmp_path, repo, env, events, 2)

        diagnosis = result.stdout.splitlines()[0].lower()
        assert receipt_state in diagnosis
        rival = "unreadable" if receipt_state == "missing" else "missing"
        assert rival not in diagnosis
        assert state(tmp_path)["full_tier"]["ran_by"] == "land"

    def test_a_full_tier_arriving_on_origin_runs_from_the_staged_tree(self, tmp_path):
        repo, env, g, events, old, _receipt = self.start_and_review(tmp_path, origin=True)
        g("checkout", "-q", "main")
        (repo / "trunk-only").write_text("yes\n")
        config = repo / ".xp" / "config.yml"
        new = f"test -f trunk-only && printf yy >> {events}"
        config.write_text(config.read_text().replace(old, new))
        g("add", "-A")
        g("commit", "-qm", "tier arrives on trunk")
        g("push", "-q", "origin", "main")
        g("checkout", "-q", "sprint-002")

        self.assert_land_ran(tmp_path, repo, env, events, 3)

        assert state(tmp_path)["full_tier"]["command"] == new

    def test_land_refuses_an_unreadable_sprint_marker_before_the_tier(self, tmp_path):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        before = path.read_bytes()

        result = sprint(repo, env, "land")

        assert result.returncode == 2 and "unreadable sprint marker" in result.stderr.lower()
        assert "Traceback" not in result.stderr and run_count(events) == 0
        assert path.read_bytes() == before

    def test_land_refuses_when_git_cannot_name_the_shipping_tree(self, tmp_path):
        repo, env, _g, events, _tier, _receipt = self.start_and_review(tmp_path)
        before = marker_path(tmp_path).read_bytes()
        (repo / ".git" / "index.lock").touch()

        result = sprint(repo, env, "land")

        assert result.returncode == 2 and "write tree" in result.stderr.lower()
        assert "Traceback" not in result.stderr and run_count(events) == 1
        assert marker_path(tmp_path).read_bytes() == before

    def test_pending_trunk_red_falsifier_runs_before_trial_merge_aborts(self, tmp_path):
        repo, env, g, _events, _tier = counted_repo(tmp_path, "test ! -f trunk-only")
        add_origin(tmp_path, repo, env, g)
        filed = work(
            repo,
            env,
            "debt",
            "--claim",
            "trunk must stay clear",
            "--falsifier",
            "test ! -f trunk-only",
            "--covered-by",
            "full",
            "--files",
            "trunk-only",
        )
        assert filed.returncode == 0
        source = filed.stdout.strip()
        assert sprint(repo, env, "start").returncode == 0
        record_reviews(tmp_path, repo, env)
        advance_origin(repo, g, "trunk-only", "present\n")

        result = sprint(repo, env, "land")

        assert result.returncode == 2 and f"source {source}" in result.stderr
        assert "`close.py sprint 2 land` again" in result.stderr
        assert "## bug " in (tmp_path / "data" / "work.md").read_text()
        assert g("rev-parse", "-q", "--verify", "MERGE_HEAD").returncode != 0
        assert not g("status", "--porcelain").stdout

    def test_green_pending_merge_receipt_names_staged_tree_without_deferred_rerun(self, tmp_path):
        repo, env, g, events, _tier = counted_repo(tmp_path, "true")
        add_origin(tmp_path, repo, env, g)
        command = f"printf x >> {events}"
        filed = work(
            repo,
            env,
            "debt",
            "--claim",
            "covered",
            "--falsifier",
            command,
            "--covered-by",
            "full",
            "--files",
            "src.py",
        )
        assert filed.returncode == 0 and run_count(events) == 1
        assert sprint(repo, env, "start").returncode == 0
        record_reviews(tmp_path, repo, env)
        advance_origin(repo, g, "trunk-only", "present\n")
        assert g("merge", "--no-commit", "--no-ff", "origin/main").returncode == 0
        staged_tree = tree(g)
        assert g("merge", "--abort").returncode == 0

        result = sprint(repo, env, "land")

        assert result.returncode == 2 and "gh" in result.stderr
        assert run_count(events) == 1
        assert state(tmp_path)["full_tier"]["tree"] == staged_tree
