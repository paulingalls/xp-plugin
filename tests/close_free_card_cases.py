"""Mandatory free-card lifecycle cases, collected from test_close_free.py."""

import json
from pathlib import Path

from close_helpers import CONFIG_PATCH, free, free_repo, launches, marker_file, stub_reviewer
from spawn_helpers import spawn
from test_close_salvage import KILLED, dying_reviewer


def free_identity(g):
    branch = g("branch", "--show-current").stdout.strip()
    return branch, branch.split("/", 1)[1]


def control_subprocess_date(tmp_path, env, day):
    clock = tmp_path / "clock"
    clock.mkdir(exist_ok=True)
    (clock / "sitecustomize.py").write_text(
        "import datetime, os\n"
        "class ControlledDate(datetime.date):\n"
        "    @classmethod\n"
        "    def today(cls):\n"
        "        return cls.fromisoformat(os.environ['XP_TEST_TODAY'])\n"
        "datetime.date = ControlledDate\n"
    )
    env["PYTHONPATH"] = str(clock)
    env["XP_TEST_TODAY"] = day


def add_free_card(env, key, verify="true"):
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(
        plan.read_text()
        + f"\n### Free\n#### {key} — fix typo   [planned]\n"
        + "Context: small release.\nFiles: src/free.py\nAC:\n"
        + f"- Given the patch, Then it lands.\nVerify: {verify}\n"
    )


def commit_on_free(repo, g, text="B = 1\n", path="src/free.py", msg="free work"):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    g("add", "-A")
    g("commit", "-qm", msg)


def carded_review(tmp_path, slug="fix-typo", verify="true"):
    repo, env, g = free_repo(tmp_path)
    assert free(repo, env, slug, "start").returncode == 0
    branch, key = free_identity(g)
    commit_on_free(repo, g)
    add_free_card(env, key, verify)
    reviewed = free(repo, env, slug, "review")
    assert reviewed.returncode == 0, reviewed.stderr + reviewed.stdout
    return repo, env, g, branch, key


class FreeCardCases:
    def test_free_verify_runs_on_the_reviewed_tree(self, tmp_path):
        sentinel = tmp_path / "verify-ran"
        gate = tmp_path / "verify"
        gate.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit 1\n")
        gate.chmod(0o755)
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key, str(gate))

        refused = free(repo, env, "fix-typo", "review")

        assert refused.returncode == 2 and "Verify red" in refused.stderr
        assert sentinel.exists(), "the reviewed-tree Verify never ran"
        assert not marker_file(tmp_path, key).exists(), "a red Verify recorded the round"

    def test_a_dirty_refusal_does_not_advance_a_free_card(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        (repo / "dirty.py").write_text("dirty = True\n")
        result = free(repo, env, "fix-typo", "review")
        assert result.returncode == 2 and "dirty" in result.stderr
        assert "[planned]" in (Path(env["XP_DATA"]) / "plan.md").read_text()

    def test_a_free_card_is_minted_reviewed_and_checked_for_drift(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        reviewed = free(repo, env, "fix-typo", "review")
        assert reviewed.returncode == 0, reviewed.stderr
        assert f"#### {key}" in launches(tmp_path)[-1]["stdin"]
        plan = Path(env["XP_DATA"]) / "plan.md"
        assert "[in-progress]" in plan.read_text()
        assert (Path(env["XP_DATA"]) / "markers" / f"{key}.ready.json").exists()
        plan.write_text(plan.read_text().replace("Verify: true", "Verify: false"))
        landed = free(repo, env, "fix-typo", "land")
        assert landed.returncode == 2 and "edited after its plan review" in landed.stderr
        assert "--- reviewed" in landed.stderr and "+++ now" in landed.stderr
        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]"))
        verified = free(repo, env, "fix-typo", "review")
        assert verified.returncode == 2 and "Verify red" in verified.stderr

    def test_a_deleted_free_card_cannot_drop_its_credential(self, tmp_path):
        repo, env, _g, _branch, key = carded_review(tmp_path)
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().split(f"#### {key} ")[0])
        result = free(repo, env, "fix-typo", "land")
        assert result.returncode == 2 and key in result.stderr

    def test_a_free_reviewer_editing_a_gate_file_is_refused(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        free(repo, env, "fix-typo", "start")
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        stub_reviewer(tmp_path, patch=CONFIG_PATCH)
        result = free(repo, env, "fix-typo", "review")
        assert result.returncode == 2, result.stdout
        assert ".xp/config.yml" in result.stderr and "Files line" in result.stderr

    def test_cardless_review_refuses_with_the_card_heading_to_add(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = free_identity(g)
        commit_on_free(repo, g)

        result = free(repo, env, "fix-typo", "review")

        assert result.returncode == 2, result.stdout
        assert f"#### {key} — <title>   [planned]" in result.stderr
        assert "Context, Files, AC, and Verify" in result.stderr
        assert "close.py free fix-typo review" in result.stderr
        assert launches(tmp_path) == [], "a card-less branch reached the reviewer"

    def test_a_free_card_amends_without_changing_status_or_buying_a_round(self, tmp_path):
        repo, env, _g, _branch, key = carded_review(tmp_path)
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true", "Verify: printf verified"))
        before_launches = len(launches(tmp_path))
        drifted = free(repo, env, "fix-typo", "land", "--dry-run")
        assert drifted.returncode == 2 and "edited after its plan review" in drifted.stderr

        amended = spawn(
            repo,
            env,
            "amend",
            key,
            "--reason",
            "the card now names the focused verification",
        )

        assert amended.returncode == 0, amended.stderr
        assert "[in-progress]" in plan.read_text()
        marker = json.loads((Path(env["XP_DATA"]) / "markers" / f"{key}.ready.json").read_text())
        assert marker["amendments"][-1]["reason"] == "the card now names the focused verification"
        landed = free(repo, env, "fix-typo", "land", "--dry-run")
        assert landed.returncode == 0, landed.stderr
        assert len(launches(tmp_path)) == before_launches

    def test_a_lost_free_credential_names_and_walks_amend(self, tmp_path):
        repo, env, _g, _branch, key = carded_review(tmp_path)
        ready = Path(env["XP_DATA"]) / "markers" / f"{key}.ready.json"
        ready.unlink()

        refused = free(repo, env, "fix-typo", "land", "--dry-run")

        command = f"spawn.py amend {key}"
        assert refused.returncode == 2 and command in refused.stderr, refused.stderr
        repaired = spawn(repo, env, "amend", key, "--reason", "repair the lost credential")
        assert repaired.returncode == 0, repaired.stderr
        assert "[in-progress]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
        assert free(repo, env, "fix-typo", "land", "--dry-run").returncode == 0

    def test_a_killed_free_review_names_and_runs_free_salvage(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "Fix Typo.", "start").returncode == 0
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        dying_reviewer(tmp_path, patch="")

        killed = free(repo, env | KILLED, "Fix Typo.", "review")

        assert killed.returncode == 2
        assert "close.py free fix-typo salvage" in killed.stderr, killed.stderr
        salvaged = free(repo, env, "Fix Typo.", "salvage")
        assert salvaged.returncode == 0, salvaged.stderr
        assert len(json.loads(marker_file(tmp_path, key).read_text())["rounds"]) == 1
        assert (tmp_path / "spawns").read_text().splitlines() == ["launched"]

    def test_free_land_uses_the_branch_derived_slug(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        started = free(repo, env, "Fix Typo.", "start")
        assert started.returncode == 0
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        stub_reviewer(tmp_path)
        assert free(repo, env, "Fix Typo.", "review").returncode == 0

        preview = free(repo, env, "Fix Typo.", "land", "--dry-run")

        assert preview.returncode == 0, preview.stderr
        assert "free fix-typo" in preview.stdout
        assert "Fix Typo." not in preview.stdout

    def test_a_planned_free_card_review_preview_does_not_mint_or_flip(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = free_identity(g)
        commit_on_free(repo, g)
        add_free_card(env, key)

        preview = free(repo, env, "fix-typo", "review", "--dry-run")

        assert preview.returncode == 0, preview.stderr
        assert "#### " + key in preview.stdout
        assert "[planned]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
        assert not (Path(env["XP_DATA"]) / "markers" / f"{key}.ready.json").exists()
