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
                report.write_text(
                    '{"fixed": [], "blocking": ["x"], "schema":2,"dropped":[],"debt":[]}'
                )
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


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("scope", ["story", "free"])
def test_installed_consumer_evidence_walk(tmp_path, harness, scope):
    import shutil
    import subprocess
    import sys

    from close_free_card_cases import add_free_card, checkout_free, commit_on_free
    from close_helpers import PLUGIN, free, free_repo
    from spawn_helpers import make_repo as spawn_repo
    from test_spawn_stages import stub_stages
    from test_verify_evidence import locator

    installed = tmp_path / "installed"
    import os

    shutil.copytree(os.environ.get("XP_VERIFY_TEST_PLUGIN", str(PLUGIN)), installed)
    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\nprintf out-evidence\nprintf err-evidence >&2\nexit 7\n")
    gate.chmod(0o755)
    if scope == "story":
        repo, env, g = spawn_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
        identity = "story-042"
        args = ["story", identity]
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true", f"Verify: {gate}"))
    else:
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "evidence", "start").returncode == 0
        branch, identity = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, identity, str(gate))
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/free.py", "Files: src/free.py, src/thing.py")
        )
        g("checkout", "-q", "main")
        args = ["free", "evidence"]
    stub_stages(tmp_path)
    if harness == "codex":
        binary = tmp_path / "bin" / "claude"
        text = (
            binary.read_text()
            .replace(
                'print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]\')',
                'print(\'{"installed":[{"pluginId":"xp-plugin@xp-plugin","version":"fixture"}]}\')',
            )
            .replace(
                "print(json.dumps({'type':'result','subtype':'success','result':'done'}))",
                "print(json.dumps({'type':'thread.started','thread_id':'scratch'})); "
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}))",
            )
        )
        (tmp_path / "bin" / "codex").write_text(text)
        (tmp_path / "bin" / "codex").chmod(0o755)
    config = repo / ".xp" / "config.yml"
    config.write_text(
        f"roles:\n  planner: {harness}/model\n  plan-reviewer: {harness}/model\n"
        f"  executor: {harness}/model\n  reviewer: {harness}/model\n"
        "codex_sandbox: danger-full-access\ntests:\n  story: true\n"
    )
    g("add", "-A")
    g("commit", "-qm", "scratch harness config")
    if scope == "free":
        g("checkout", "-q", branch)
        g("merge", "-q", "main")
        g("checkout", "-q", "main")

    def invoke(script, argv, cwd=repo):
        return subprocess.run(
            [sys.executable, str(installed / "scripts" / script), *argv],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )

    assert invoke("spawn.py", ["ready", identity]).returncode == 0
    red = invoke("spawn.py", [identity])
    assert red.returncode == 2, red.stderr + red.stdout
    original = locator(red.stderr)
    saved = {p.name: p.read_bytes() for p in original.iterdir()}
    assert saved["1.stdout"] == b"out-evidence" and saved["1.stderr"] == b"err-evidence"
    tree = tmp_path / "data" / "worktrees" / identity
    gate.write_text("#!/bin/sh\nprintf green-evidence\n")
    options = ["--merge-mode", "local"] if scope == "story" else []
    repair = invoke("close.py", [*args, "repair", *options], tree)
    assert repair.returncode == 2 and "green rerun" in repair.stderr
    assert invoke("close.py", [*args, "review", *options], tree).returncode == 0
    (tree / "src" / "thing.py").write_text("later = True\n")
    subprocess.run(["git", "commit", "-qam", "later run"], cwd=tree, env=env, check=True)
    later = invoke("close.py", [*args, "review", *options], tree)
    assert later.returncode == 0, later.stderr
    assert {p.name: p.read_bytes() for p in original.iterdir()} == saved
    assert len(list((tmp_path / "data/logs/verify").glob("*/run.json"))) == 4


@pytest.mark.parametrize("unlink_fault", [False, True])
def test_repair_invalidates_prior_green_receipt(tmp_path, unlink_fault):
    import sys

    from test_verify_evidence import TEST_CLOSE

    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\nexit 0\n")
    gate.chmod(0o755)
    repo, env, _g = make_repo(tmp_path, verify=str(gate))
    assert close(repo, env, "review").returncode == 0
    receipt = tmp_path / "data/markers/story-042.verify.json"
    prior = receipt.read_bytes()
    gate.write_text("#!/bin/sh\nexit 7\n")
    assert close(repo, env, "review").returncode == 2
    receipt.write_bytes(prior)
    injection = (
        (
            "from pathlib import Path\noriginal=Path.unlink\n"
            "def unlink(self,*a,**k):\n"
            "    if self.name.endswith('.verify.json'): raise OSError('unlink fault')\n"
            "    return original(self,*a,**k)\nPath.unlink=unlink\n"
        )
        if unlink_fault
        else ""
    )
    script = (
        f"import sys; sys.path.insert(0,{str(TEST_CLOSE.parent)!r}); import close\n"
        + injection
        + "sys.argv=['close.py','story','story-042','repair','--merge-mode','local']\n"
        + "sys.exit(close.main())\n"
    )
    before = list((tmp_path / "data/logs/verify").iterdir())
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    if unlink_fault:
        assert "unlink fault" in result.stderr
        assert receipt.exists() and list((tmp_path / "data/logs/verify").iterdir()) == before
    else:
        assert not receipt.exists()
        assert len(list((tmp_path / "data/logs/verify").iterdir())) == len(before) + 1
