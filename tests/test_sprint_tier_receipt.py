"""The sprint full-tier receipt names the exact tree the command passed on."""

import json
import subprocess

import pytest
from sprint_helpers import CONFIG, head, make_repo, marker_path, record_reviews, sprint, work


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
    def test_start_records_a_green_full_tier_receipt_for_the_clean_tree(self, tmp_path):
        repo, env, g, events, tier = counted_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"rounds": [{"sentinel": "preserved"}]}))

        result = sprint(repo, env, "start")

        assert result.returncode == 0, result.stderr
        assert run_count(events) == 1
        receipt = state(tmp_path)["full_tier"]
        assert receipt == {
            "tier": "full",
            "command": tier,
            "tree": tree(g),
            "head": head(repo, env),
            "verdict": "passed",
            "ran_by": "start",
            "reused": False,
        }
        assert state(tmp_path)["rounds"] == [{"sentinel": "preserved"}]

    @pytest.mark.parametrize("kind", ["tracked", "untracked"])
    def test_start_refuses_dirt_before_the_batch_or_tier(self, tmp_path, kind):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        target = repo / ("src.py" if kind == "tracked" else "untracked.py")
        target.write_text(target.read_text() + "DIRT = 1\n" if target.exists() else "DIRT = 1\n")

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "before the close batch" in result.stderr.lower()
        assert run_count(events) == 0
        assert not marker_path(tmp_path).exists() or "full_tier" not in state(tmp_path)

    @pytest.mark.parametrize("kind", ["tracked", "untracked"])
    def test_start_refuses_dirt_created_by_the_falsifier_batch(self, tmp_path, kind):
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

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "batch" in result.stderr.lower()
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
    def test_green_tier_motion_is_reported_without_a_receipt(self, tmp_path, kind):
        if kind == "tracked":
            command = "printf '\\nMOVED = 1' >> src.py"
        elif kind == "untracked":
            command = "touch generated.py"
        else:
            command = "printf '\\nMOVED = 1' >> src.py && git commit -qam tier-motion"
        repo, env, _g, _events, _tier = counted_repo(tmp_path, command)

        result = sprint(repo, env, "start")

        assert result.returncode == 0, result.stderr
        assert "no reusable receipt" in result.stdout.lower()
        assert "full_tier" not in state(tmp_path)

    def test_a_red_retry_invalidates_the_prior_green_receipt(self, tmp_path):
        flag = tmp_path / "red"
        repo, env, _g, _events, _tier = counted_repo(tmp_path, f"test ! -e {flag}")
        assert sprint(repo, env, "start").returncode == 0
        assert "full_tier" in state(tmp_path)
        flag.touch()

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "full tier red" in result.stderr
        assert "full_tier" not in state(tmp_path)

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

    def test_start_refuses_when_git_cannot_name_the_tree(self, tmp_path):
        repo, env, _g, events, _tier = counted_repo(tmp_path)
        (repo / ".git" / "index.lock").touch()

        result = sprint(repo, env, "start")

        assert result.returncode == 2 and "write tree" in result.stderr.lower()
        assert "Traceback" not in result.stderr and run_count(events) == 0


class TestFullTierReceipt:
    def start_and_review(self, tmp_path, origin=False):
        repo, env, g, events, tier = counted_repo(tmp_path)
        if origin:
            add_origin(tmp_path, repo, env, g)
        assert sprint(repo, env, "start").returncode == 0
        receipt = state(tmp_path)["full_tier"].copy()
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
