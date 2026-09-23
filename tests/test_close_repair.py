"""A red completed review can be recorded after a bounded green repair."""

import json
import subprocess

import pytest
from close_free_card_cases import (
    add_free_card,
    checkout_free,
    commit_on_free,
    spawn_free,
)
from close_helpers import (
    close,
    free,
    free_repo,
    launches,
    make_repo,
    marker,
    marker_file,
    stub_reviewer,
)

BROKEN_PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+broken =
"""


class TestStoryRepair:
    def test_records_bounded_repair_and_lands(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify="python3 -m py_compile src/thing.py")
        stub_reviewer(tmp_path, patch=BROKEN_PATCH)
        reviewed_head = g("rev-parse", "HEAD").stdout.strip()
        red = close(repo, env, "review")
        assert red.returncode == 2, red.stderr
        verify_head = g("rev-parse", "HEAD").stdout.strip()
        launch = tmp_path / "data/markers/story-042.review-launch"
        assert json.loads(launch.read_text())["verify_head"] == verify_head
        assert "refused" in (tmp_path / "data/reports/story-042.round-1.json").read_text()
        assert not marker_file(tmp_path).exists()
        refused = close(repo, env, "land")
        assert refused.returncode == 2 and "story story-042 repair" in refused.stderr

        (repo / "src/thing.py").write_text("A = 2\nbroken = True\n")
        g("add", "src/thing.py")
        assert g("commit", "-qm", "lead repair").returncode == 0
        repaired_head = g("rev-parse", "HEAD").stdout.strip()
        result = close(repo, env, "repair")
        assert result.returncode == 0, result.stderr
        round_ = marker(tmp_path)["rounds"][0]
        assert round_["reviewed_head"] == reviewed_head
        assert round_["shown_sha"] == verify_head
        assert round_["repair"] == {
            "range": f"{verify_head}..{repaired_head}",
            "paths": ["src/thing.py"],
            "verify": [["python3", "-m", "py_compile", "src/thing.py"]],
            "result": "green",
        }
        diff = (tmp_path / "data/reports/story-042.round-1.diff").read_text()
        assert "broken =" in diff and "lead repair" not in diff and "broken = True" not in diff
        report = json.loads((tmp_path / "data/reports/story-042.round-1.json").read_text())
        assert "refused" not in report and report["repaired"] == round_["repair"]["range"]
        assert not launch.exists()
        assert len(launches(tmp_path)) == 1
        landed = close(repo, env, "land")
        assert landed.returncode == 0, landed.stderr
        assert "the reviewer changed this tree" in landed.stdout
        assert "merging unreviewed" in landed.stdout
        assert "lead repair" in landed.stdout
        closes = [
            json.loads(line) for line in (tmp_path / "data/closes.jsonl").read_text().splitlines()
        ]
        assert closes[-1]["rounds"][0]["repair"] == round_["repair"]

    def test_card_files_allows_a_path_the_review_did_not_touch(self, tmp_path):
        repo, env, g = make_repo(
            tmp_path,
            verify="python3 -m py_compile src/thing.py",
            files="src/thing.py, src/extra.py",
        )
        stub_reviewer(tmp_path, patch=BROKEN_PATCH)
        assert close(repo, env, "review").returncode == 2
        commit(g, repo, "src/extra.py", "extra = True\n")
        commit(g, repo, "src/thing.py", "A = 2\nbroken = True\n")
        repaired = close(repo, env, "repair")
        assert repaired.returncode == 0, repaired.stderr
        assert marker(tmp_path)["rounds"][0]["repair"]["paths"] == [
            "src/extra.py",
            "src/thing.py",
        ]


def red_round(tmp_path):
    repo, env, g = make_repo(tmp_path, verify="python3 -m py_compile src/thing.py")
    stub_reviewer(tmp_path, patch=BROKEN_PATCH)
    assert close(repo, env, "review").returncode == 2
    return repo, env, g, tmp_path / "data/markers/story-042.review-launch"


def commit(g, repo, path, content):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    g("add", path)
    assert g("commit", "-qm", "lead repair").returncode == 0


class TestRepairRefusals:
    def test_dry_run_never_records_a_round(self, tmp_path):
        repo, env, _g, launch = red_round(tmp_path)
        refused = close(repo, env, "repair", "--dry-run")
        assert refused.returncode == 2 and "without --dry-run" in refused.stderr
        assert launch.exists() and not marker_file(tmp_path).exists()

    @pytest.mark.parametrize(
        ("fault", "message", "action"),
        [
            ("dirty", "dirty", "repair"),
            ("red", "Verify red", "repair"),
            ("missing", "no launch marker", "review"),
            ("unreadable", "unreadable launch marker", "review"),
            ("no_red", "no verify_red", "review"),
            ("sidecar", "queued review sidecar", "salvage"),
            ("card", "card changed", "review"),
            ("ancestor", "does not contain verify_head", "review"),
            ("outside", "stray.py", "review"),
            ("gate", ".xp/config.yml", "review"),
            ("ledger", "ledger changed", "review"),
            ("ledger_shape", "unreadable close marker", "review"),
            ("round_identity", "lacks round identity", "review"),
            ("base", "review base does not precede", "review"),
            ("report", "unusable or blocking", "review"),
            ("blocking", "unusable or blocking", "review"),
            ("reviewed", "reviewed head does not precede", "review"),
        ],
    )
    def test_each_guard_records_nothing(self, tmp_path, fault, message, action):
        repo, env, g, launch = red_round(tmp_path)
        before = launch.read_bytes()
        if fault == "dirty":
            (repo / "untracked.txt").write_text("dirty")
        elif fault == "red":
            commit(g, repo, "src/thing.py", "A = 2\nbroken =\n# still red\n")
        elif fault == "missing":
            launch.unlink()
        elif fault == "unreadable":
            launch.write_text("{")
        elif fault == "no_red":
            at = json.loads(before)
            at.pop("verify_red")
            launch.write_text(json.dumps(at))
        elif fault == "sidecar":
            launch.with_name("story-042.round-2.launch").write_text("{}")
        elif fault == "card":
            plan = tmp_path / "data/plan.md"
            plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
        elif fault == "ancestor":
            g("reset", "--hard", "HEAD~1")
        elif fault == "outside":
            commit(g, repo, "stray.py", "stray = True\n")
        elif fault == "gate":
            commit(g, repo, ".xp/config.yml", "tests:\n  story: true\n")
        elif fault == "ledger":
            marker_file(tmp_path).write_text('{"rounds": []}')
        elif fault == "ledger_shape":
            marker_file(tmp_path).write_text('{"rounds": {}}')
        elif fault == "round_identity":
            at = json.loads(before)
            at.pop("base")
            launch.write_text(json.dumps(at))
        elif fault == "base":
            at = json.loads(before)
            at["base"] = "missing-sha"
            launch.write_text(json.dumps(at))
        elif fault in ("report", "blocking", "reviewed"):
            commit(g, repo, "src/thing.py", "A = 2\nbroken = True\n")
            report = tmp_path / "data/reports/story-042.round-1.json"
            if fault == "report":
                report.unlink()
            elif fault == "blocking":
                report.write_text('{"fixed": [], "blocking": ["x"], "noted": []}')
            else:
                at = json.loads(before)
                at["head"] = "missing-sha"
                launch.write_text(json.dumps(at))
        refused = close(repo, env, "repair")
        assert refused.returncode == 2 and message in refused.stderr, refused.stderr
        assert f"close.py story story-042 {action}" in refused.stderr
        if fault == "unreadable":
            assert str(launch) in refused.stderr
        assert not marker_file(tmp_path).exists() or fault in ("ledger", "ledger_shape")
        if fault not in ("missing", "unreadable", "no_red", "round_identity", "base", "reviewed"):
            assert launch.read_bytes() == before
        assert close(repo, env, "land").returncode == 2

    def test_green_rerun_on_same_head_is_a_flake(self, tmp_path):
        gate = tmp_path / "verify-gate"
        gate.write_text("#!/bin/sh\nexit 1\n")
        gate.chmod(0o755)
        repo, env, _g = make_repo(tmp_path, verify=str(gate))
        stub_reviewer(tmp_path, patch=BROKEN_PATCH)
        assert close(repo, env, "review").returncode == 2
        gate.write_text("#!/bin/sh\nexit 0\n")
        refused = close(repo, env, "repair")
        assert refused.returncode == 2 and "flake" in refused.stderr
        assert "close.py story story-042 review" in refused.stderr
        assert not marker_file(tmp_path).exists()
        assert close(repo, env, "land").returncode == 2

    def test_a_commit_that_leaves_the_reviewed_tree_is_a_flake(self, tmp_path):
        gate = tmp_path / "verify-gate"
        gate.write_text("#!/bin/sh\nexit 1\n")
        gate.chmod(0o755)
        repo, env, g = make_repo(tmp_path, verify=str(gate))
        stub_reviewer(tmp_path, patch=BROKEN_PATCH)
        assert close(repo, env, "review").returncode == 2
        gate.write_text("#!/bin/sh\nexit 0\n")
        assert g("commit", "-q", "--allow-empty", "-m", "no change").returncode == 0
        refused = close(repo, env, "repair")
        assert refused.returncode == 2 and "flake" in refused.stderr, refused.stderr
        assert not marker_file(tmp_path).exists()

    def test_red_rerun_on_same_head_requests_a_fix(self, tmp_path):
        repo, env, _g, _launch = red_round(tmp_path)
        refused = close(repo, env, "repair")
        assert refused.returncode == 2 and "Verify red" in refused.stderr
        assert "close.py story story-042 repair" in refused.stderr

    def test_gate_path_refuses_even_when_declared(self, tmp_path):
        repo, env, g = make_repo(
            tmp_path,
            verify="python3 -m py_compile src/thing.py",
            files="src/thing.py, .xp/config.yml",
        )
        stub_reviewer(tmp_path, patch=BROKEN_PATCH)
        assert close(repo, env, "review").returncode == 2
        commit(g, repo, ".xp/config.yml", "tests:\n  story: true\n")
        refused = close(repo, env, "repair")
        assert refused.returncode == 2 and ".xp/config.yml" in refused.stderr
        assert "close.py story story-042 review" in refused.stderr
        assert not marker_file(tmp_path).exists()

    def test_rotated_red_launch_keeps_salvage_route_at_land(self, tmp_path):
        repo, env, _g, launch = red_round(tmp_path)
        launch.rename(launch.with_name("story-042.round-2.launch"))
        refused = close(repo, env, "land")
        assert refused.returncode == 2 and "salvage" in refused.stderr
        assert "repair" not in refused.stderr


class TestFreeRepair:
    def test_free_repairs_the_reviewed_tree(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key, "python3 -m py_compile src/free.py")
        tree = spawn_free(repo, env, g, tmp_path, key)
        patch = """diff --git a/src/free.py b/src/free.py
--- a/src/free.py
+++ b/src/free.py
@@ -1 +1,2 @@
 B = 1
+broken =
"""
        stub_reviewer(tmp_path, patch=patch)
        assert free(tree, env, "fix-typo", "review").returncode == 2
        land = free(tree, env, "fix-typo", "land")
        assert land.returncode == 2 and "free fix-typo repair" in land.stderr
        (tree / "src/free.py").write_text("B = 1\nbroken = True\n")
        subprocess.run(["git", "add", "src/free.py"], cwd=tree, check=True)
        subprocess.run(["git", "commit", "-qm", "lead repair"], cwd=tree, check=True)
        repaired = free(tree, env, "fix-typo", "repair")
        assert repaired.returncode == 0, repaired.stderr
        assert marker(tmp_path, key)["rounds"][-1]["repair"]["result"] == "green"

    def test_free_red_verify_refusal_names_its_leg(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key, "python3 -m py_compile src/free.py")
        tree = spawn_free(repo, env, g, tmp_path, key)
        stub_reviewer(
            tmp_path,
            patch="""diff --git a/src/free.py b/src/free.py
--- a/src/free.py
+++ b/src/free.py
@@ -1 +1,2 @@
 B = 1
+broken =
""",
        )
        assert free(tree, env, "fix-typo", "review").returncode == 2
        refused = free(tree, env, "fix-typo", "repair")
        assert refused.returncode == 2 and "free fix-typo repair" in refused.stderr
