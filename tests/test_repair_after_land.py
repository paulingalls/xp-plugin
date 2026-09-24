"""Measured land reds can be repaired on the recorded round."""

import json
import subprocess
import sys

import pytest
from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import (
    CLOSE,
    close,
    free,
    free_repo,
    gh_calls,
    launches,
    make_repo,
    marker,
    stub_reviewer,
)

sys.path.insert(0, str(CLOSE.parent / "close"))
import overlap

BROKEN = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+broken =
"""


def commit(g, repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    assert g("add", path).returncode == 0
    assert g("commit", "-qm", "lead repair").returncode == 0


def land_red(tmp_path, kind="tier", files="src/thing.py"):
    phase = tmp_path / "land-phase"
    gate = tmp_path / "verify-gate"
    gate.write_text(
        f"#!/bin/sh\nif [ ! -f {phase} ]; then exit 0; fi\ngrep -q fixed src/thing.py\n"
    )
    gate.chmod(0o755)
    verify = str(gate) if kind == "Verify" else "true"
    mapped = f"{files}, .xp/config.yml" if kind == "tier" else files
    repo, env, g = make_repo(tmp_path, verify=verify, files=mapped)
    stub_reviewer(tmp_path)
    if kind == "tier":
        (repo / ".xp/config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:\n  story: grep -q fixed src/thing.py\n"
        )
        g("add", ".xp/config.yml")
        g("commit", "-qm", "set failing tier")
    assert close(repo, env, "review").returncode == 0
    if kind == "Verify":
        phase.write_text("land")
        commit(g, repo, "src/thing.py", "A = 2\nland_motion = True\n")
    red = close(repo, env, "land")
    assert red.returncode == 2 and f"{kind} red" in red.stderr, red.stderr
    return repo, env, g


@pytest.mark.parametrize("kind", ["tier", "Verify"])
def test_land_red_repair_merges_on_existing_round(tmp_path, kind):
    repo, env, g = land_red(tmp_path, kind)
    record = tmp_path / "data/markers/story-042.land-red.json"
    assert record.exists()
    assert "close.py story story-042 repair" in close(repo, env, "land").stderr
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    repaired = close(repo, env, "repair")
    assert repaired.returncode == 0, repaired.stderr
    assert not record.exists()
    repair_range = marker(tmp_path)["rounds"][0]["repair"]["range"]
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert repair_range in g("show", "-s", "--format=%B", "main").stdout
    assert len(launches(tmp_path)) == 1
    assert not record.exists()


def test_green_land_without_repair_clears_the_record(tmp_path):
    repo, env, _g = land_red(tmp_path, "Verify")
    (tmp_path / "land-phase").unlink()
    assert close(repo, env, "land").returncode == 0
    assert not (tmp_path / "data/markers/story-042.land-red.json").exists()


def test_land_red_repair_rejects_outside_review_and_files(tmp_path):
    repo, env, g = land_red(tmp_path)
    record = tmp_path / "data/markers/story-042.land-red.json"
    before = record.read_bytes()
    ledger = (tmp_path / "data/markers/story-042.close.json").read_bytes()
    commit(g, repo, "stray.py", "stray = True\n")
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    refused = close(repo, env, "repair")
    assert refused.returncode == 2 and "stray.py" in refused.stderr
    assert record.read_bytes() == before
    assert (tmp_path / "data/markers/story-042.close.json").read_bytes() == ledger


def test_late_unreviewed_path_is_not_counted_as_seen(tmp_path):
    repo, env, g = make_repo(tmp_path, files="src/thing.py, .xp/config.yml")
    (repo / ".xp/config.yml").write_text(
        "roles:\n  reviewer: claude/opus\ntests:\n  story: grep -q fixed src/thing.py\n"
    )
    g("add", ".xp/config.yml")
    g("commit", "-qm", "tier")
    stub_reviewer(tmp_path)
    assert close(repo, env, "review").returncode == 0
    commit(g, repo, "stray.py", "pre_red = True\n")
    assert "test tier red" in close(repo, env, "land").stderr
    commit(g, repo, "stray.py", "pre_red = True\nrepair = True\n")
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    refused = close(repo, env, "repair")
    assert refused.returncode == 2 and "stray.py" in refused.stderr


def test_no_record_distinguishes_round_states(tmp_path):
    repo, env, _ = make_repo(tmp_path)
    first = close(repo, env, "repair")
    assert "no launch marker" in first.stderr and "review" in first.stderr
    stub_reviewer(tmp_path)
    assert close(repo, env, "review").returncode == 0
    second = close(repo, env, "repair")
    assert "no launch marker" in second.stderr and "review" in second.stderr
    assert first.stderr != second.stderr
    assert "land" in second.stderr


def test_review_then_land_repairs_append_and_render(tmp_path):
    repo, env, g = make_repo(
        tmp_path, verify="python3 -m py_compile src/thing.py", files="src/thing.py, .xp/config.yml"
    )
    (repo / ".xp/config.yml").write_text(
        "roles:\n  reviewer: claude/opus\ntests:\n  story: grep -q landed src/thing.py\n"
    )
    g("add", ".xp/config.yml")
    g("commit", "-qm", "tier")
    stub_reviewer(tmp_path, patch=BROKEN)
    assert close(repo, env, "review").returncode == 2
    commit(g, repo, "src/thing.py", "A = 2\nbroken = True\n")
    assert close(repo, env, "repair").returncode == 0
    first = marker(tmp_path)["rounds"][0]["repair"]
    red = close(repo, env, "land")
    assert red.returncode == 2 and "test tier red" in red.stderr
    commit(g, repo, "src/thing.py", "A = 2\nbroken = True\nlanded = True\n")
    assert close(repo, env, "repair").returncode == 0
    round_ = marker(tmp_path)["rounds"][0]
    assert round_["repair"] == first
    second = round_["repairs"][0]
    assert second["range"] != first["range"]
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    body = g("show", "-s", "--format=%B", "main").stdout
    assert first["range"] in body and second["range"] in body


def test_review_time_repair_alone_is_rendered(tmp_path):
    repo, env, g = make_repo(tmp_path, verify="python3 -m py_compile src/thing.py")
    stub_reviewer(tmp_path, patch=BROKEN)
    assert close(repo, env, "review").returncode == 2
    commit(g, repo, "src/thing.py", "A = 2\nbroken = True\n")
    assert close(repo, env, "repair").returncode == 0
    repair_range = marker(tmp_path)["rounds"][0]["repair"]["range"]
    assert close(repo, env, "land").returncode == 0
    assert repair_range in g("show", "-s", "--format=%B", "main").stdout


def test_declared_unseen_path_is_allowed_for_land_repair(tmp_path):
    repo, env, g = land_red(tmp_path, files="src/thing.py, src/extra.py")
    commit(g, repo, "src/extra.py", "extra = True\n")
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    repaired = close(repo, env, "repair")
    assert repaired.returncode == 0, repaired.stderr
    assert marker(tmp_path)["rounds"][0]["repair"]["paths"] == [
        "src/extra.py",
        "src/thing.py",
    ]


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("dirty", "dirty"),
        ("gate", ".xp/config.yml"),
        ("card", "card changed"),
        ("ledger", "ledger changed"),
        ("ancestor", "does not contain"),
        ("empty", "no repair delta"),
        ("blocking", "blocking"),
        ("sidecar", "queued review sidecar"),
    ],
)
def test_land_repair_guards_keep_record_and_ledger(tmp_path, fault, message):
    repo, env, g = land_red(tmp_path)
    record = tmp_path / "data/markers/story-042.land-red.json"
    ledger = tmp_path / "data/markers/story-042.close.json"
    before_record = record.read_bytes()
    if fault == "dirty":
        (repo / "untracked").write_text("dirty")
    elif fault == "gate":
        commit(g, repo, ".xp/config.yml", "tests:\n  story: true\n")
    elif fault == "card":
        plan = tmp_path / "data/plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
    elif fault == "ledger":
        ledger.write_text(ledger.read_text() + " ")
    elif fault == "ancestor":
        g("reset", "--hard", "HEAD~1")
    elif fault == "blocking":
        report = tmp_path / "data/reports/story-042.round-1.json"
        raw = json.loads(report.read_text())
        raw["blocking"] = ["late finding"]
        report.write_text(json.dumps(raw))
    elif fault == "sidecar":
        record.with_name("story-042.round-2.launch").write_text("{}")
    if fault not in ("dirty", "ancestor", "empty", "ledger", "card"):
        commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    before_ledger = ledger.read_bytes()
    refused = close(repo, env, "repair")
    assert refused.returncode == 2 and message in refused.stderr, refused.stderr
    assert record.read_bytes() == before_record
    assert ledger.read_bytes() == before_ledger


def test_land_red_record_is_bound_to_the_reviewed_round(tmp_path):
    repo, env, g = land_red(tmp_path)
    record = tmp_path / "data/markers/story-042.land-red.json"
    old = json.loads(record.read_text())
    assert old["head"] == g("rev-parse", "HEAD").stdout.strip()
    assert old["round_index"] == 1
    assert old["card"]
    assert old["digest"]
    assert old["kind"] == "test tier"
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    assert close(repo, env, "review").returncode == 0
    refused = close(repo, env, "repair")
    assert refused.returncode == 2 and "ledger changed" in refused.stderr
    assert json.loads(record.read_text()) == old


def test_unreadable_land_red_record_is_distinct_from_missing(tmp_path):
    repo, env, _g = land_red(tmp_path)
    record = tmp_path / "data/markers/story-042.land-red.json"
    record.write_text("{")
    refused = close(repo, env, "repair")
    assert refused.returncode == 2 and "unreadable land-red record" in refused.stderr
    assert record.read_text() == "{"


@pytest.mark.parametrize("kind", ["tier_rc127", "verify_rc127", "unset_tier"])
def test_unmeasured_gate_refusal_writes_no_land_red(tmp_path, kind):
    gate = tmp_path / "verify-gate"
    gate.write_text("#!/bin/sh\nexit 0\n")
    gate.chmod(0o755)
    verify = str(gate) if kind == "verify_rc127" else "true"
    repo, env, g = make_repo(tmp_path, verify=verify, files="src/thing.py, .xp/config.yml")
    if kind != "verify_rc127":
        tier = "not-a-command-anywhere-155" if kind == "tier_rc127" else "EDIT-ME"
        (repo / ".xp/config.yml").write_text(
            f"roles:\n  reviewer: claude/opus\ntests:\n  story: {tier}\n"
        )
        g("add", ".xp/config.yml")
        g("commit", "-qm", "configure refusal")
    stub_reviewer(tmp_path)
    assert close(repo, env, "review").returncode == 0
    if kind == "verify_rc127":
        gate.write_text("#!/bin/sh\nexit 127\n")
        commit(g, repo, "src/thing.py", "A = 2\nland_motion = True\n")
    refused = close(repo, env, "land")
    assert refused.returncode == 2, refused.stderr
    assert ("could not be RUN" if "rc127" in kind else "unset") in refused.stderr
    assert not (tmp_path / "data/markers/story-042.land-red.json").exists()


def test_trial_merge_conflict_does_not_report_a_measured_red(tmp_path, monkeypatch):
    repo, env, g = make_repo(tmp_path)
    g("checkout", "-q", "main")
    commit(g, repo, "src/thing.py", "A = 9\n")
    g("checkout", "-q", "story-042-branch")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("XP_DATA", env["XP_DATA"])
    recorded = []
    refusal, _ = overlap.gates(
        "main", [], "story", True, measured_red=lambda kind, red: recorded.append((kind, red))
    )
    assert "conflicts" in refusal
    assert recorded == []


def test_free_land_red_repair_opens_pr_and_clears_record(tmp_path):
    repo, env, g = free_repo(tmp_path)
    assert free(repo, env, "fix-typo", "start").returncode == 0
    _branch, key = checkout_free(g)
    commit_on_free(repo, g)
    gate = tmp_path / "verify-gate"
    gate.write_text("#!/bin/sh\nexit 0\n")
    gate.chmod(0o755)
    add_free_card(env, key, str(gate))
    tree = spawn_free(repo, env, g, tmp_path, key)
    stub_reviewer(tmp_path)
    assert free(tree, env, "fix-typo", "review").returncode == 0
    gate.write_text("#!/bin/sh\ngrep -q fixed src/free.py\n")
    (tree / "src/free.py").write_text("B = 1\nland_motion = True\n")
    subprocess.run(["git", "add", "src/free.py"], cwd=tree, check=True)
    subprocess.run(["git", "commit", "-qm", "later story work"], cwd=tree, check=True)
    red = free(tree, env, "fix-typo", "land")
    assert red.returncode == 2 and "free fix-typo repair" in red.stderr, red.stderr
    record = tmp_path / "data/markers" / f"{key}.land-red.json"
    assert record.exists()
    (tree / "src/free.py").write_text("B = 1\nfixed = True\n")
    subprocess.run(["git", "add", "src/free.py"], cwd=tree, check=True)
    subprocess.run(["git", "commit", "-qm", "lead repair"], cwd=tree, check=True)
    repaired = free(tree, env, "fix-typo", "repair")
    assert repaired.returncode == 0, repaired.stderr
    landed = free(tree, env, "fix-typo", "land")
    assert landed.returncode == 0, landed.stderr
    assert not record.exists()
    assert gh_calls(tmp_path)
