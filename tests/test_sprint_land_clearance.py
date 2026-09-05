import json
import subprocess

import pytest
from review_report import ITEM_CAP
from sprint_helpers import (
    CONFIG,
    commit_as_reviewer,
    head,
    make_repo,
    marker_path,
    sprint,
    staged_stub,
)


def record_round(tmp_path, repo, env, blockers, bindings, **extra):
    path = marker_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shown = extra.pop("shown_sha", head(repo, env))
    reviewed = extra.pop("reviewed_head", shown)
    round_ = {
        "fixed": [],
        "blocking": list(blockers),
        "noted": [],
        "clearable_by_full": bindings,
        "reviewed_head": reviewed,
        "shown_sha": shown,
    } | extra
    path.write_text(json.dumps({"rounds": [round_], "reviewed_head": reviewed, "shown_sha": shown}))
    return path


def config_for(command):
    if command is None:
        return CONFIG.replace("  full: true\n", "")
    return CONFIG.replace("full: true", f"full: {command}")


def release_tools(tmp_path, env, g):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    g("remote", "add", "origin", str(origin))
    gh = tmp_path / "bin" / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(0o755)


class TestBoundFullClearance:
    def test_green_full_tier_clears_bound_blocker_without_agent_round(self, tmp_path):
        sentinel = tmp_path / "full-ran"
        repo, env, g = make_repo(tmp_path, config=config_for(f"/usr/bin/touch {sentinel}"))
        record_round(tmp_path, repo, env, ["GATE-ME"], ["GATE-ME"])
        marker_before = marker_path(tmp_path).read_bytes()
        release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        assert result.returncode == 0, result.stderr
        assert sentinel.exists()
        assert "cleared these closer-bound blockers:\n  GATE-ME" in result.stdout
        assert marker_path(tmp_path).read_bytes() == marker_before
        assert not (tmp_path / "launches.jsonl").exists()

    def test_a_blocker_over_the_item_cap_clears_under_its_own_binding(self, tmp_path):
        # CONSTRUCTED at the cap: the parser matches the report's RAW strings and
        # records CAPPED ones, so any second count of the binding here compares two
        # different lists.
        sentinel = tmp_path / "full-ran"
        repo, env, g = make_repo(tmp_path, config=config_for(f"/usr/bin/touch {sentinel}"))
        over_cap = "x" * (ITEM_CAP + 1)
        record_round(tmp_path, repo, env, [over_cap], [over_cap])
        release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr and sentinel.exists()

    @pytest.mark.parametrize(
        "command,diagnosis",
        [
            ("/usr/bin/false", "test tier red"),
            (None, "tests.full is unset or still EDIT-ME"),
            ("EDIT-ME", "tests.full is unset or still EDIT-ME"),
            ("missing-story-115-executable", "could not be RUN"),
        ],
    )
    def test_red_unset_or_unrunnable_full_tier_preserves_blocker_and_gate_result(
        self, tmp_path, command, diagnosis
    ):
        repo, env, _g = make_repo(tmp_path, config=config_for(command))
        record_round(tmp_path, repo, env, ["BOUND-IDENTITY"], ["BOUND-IDENTITY"])
        before = marker_path(tmp_path).read_bytes()
        result = sprint(repo, env, "land")
        assert result.returncode == 2
        assert "BOUND-IDENTITY" in result.stderr and diagnosis in result.stderr
        assert marker_path(tmp_path).read_bytes() == before

    def test_shell_argv_and_command_fields_are_inert(self, tmp_path):
        tier = tmp_path / "tier"
        payloads = [tmp_path / key for key in ("shell", "argv", "command")]
        repo, env, _g = make_repo(tmp_path, config=config_for(f"/usr/bin/touch {tier}"))
        staged_stub(
            tmp_path,
            close={
                "fixed": [],
                "blocking": ["B"],
                "noted": [],
                "clearable_by_full": ["B"],
                "shell": f"touch {payloads[0]}",
                "argv": ["touch", str(payloads[1])],
                "command": f"touch {payloads[2]}",
            },
        )
        assert sprint(repo, env, "review").returncode == 0
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert not {"shell", "argv", "command"} & round_.keys()
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "gh" in result.stderr
        assert tier.exists() and not any(path.exists() for path in payloads)


class TestClearanceBoundary:
    def test_dirty_tree_refuses_before_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"])
        (repo / "dirty.py").write_text("DIRTY = 1\n")
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "dirty" in result.stderr.lower()
        assert not sentinel.exists()

    def test_any_post_review_motion_refuses_before_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"])
        (repo / "later.py").write_text("LATER = 1\n")
        g("add", "-A")
        g("commit", "-qm", "motion after review")
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "did not cover HEAD" in result.stderr
        assert not sentinel.exists()

    def test_reviewer_owned_gate_file_in_the_covered_range_refuses_before_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        reviewed = head(repo, env)
        (repo / ".xp" / "system.md").write_text("# changed gate\n")
        commit_as_reviewer(g, "reviewer changed gate")
        record_round(
            tmp_path,
            repo,
            env,
            ["B"],
            ["B"],
            reviewed_head=reviewed,
            shown_sha=head(repo, env),
        )
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and ".xp/system.md" in result.stderr
        assert not sentinel.exists()

    def test_renaming_a_gate_file_out_of_the_gate_set_refuses_before_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        reviewed = head(repo, env)
        g("mv", ".xp/system.md", ".xp/system-old.md")
        commit_as_reviewer(g, "reviewer renamed gate")
        record_round(
            tmp_path,
            repo,
            env,
            ["B"],
            ["B"],
            reviewed_head=reviewed,
            shown_sha=head(repo, env),
        )
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and ".xp/system.md" in result.stderr
        assert not sentinel.exists()

    @pytest.mark.parametrize("motion", ["add", "delete"])
    def test_adding_or_deleting_a_gate_file_refuses_before_clearance(self, tmp_path, motion):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        gate = repo / ".xp/system.md"
        if motion == "add":
            gate.unlink()
            g("commit", "-qam", "lead removes gate before review")
        reviewed = head(repo, env)
        if motion == "add":
            gate.write_text("# reviewer restored gate\n")
            g("add", ".xp/system.md")
        else:
            g("rm", ".xp/system.md")
        commit_as_reviewer(g, f"reviewer {motion}s gate")
        record_round(
            tmp_path,
            repo,
            env,
            ["B"],
            ["B"],
            reviewed_head=reviewed,
            shown_sha=head(repo, env),
        )
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and ".xp/system.md" in result.stderr
        assert not sentinel.exists()

    def test_gate_motion_in_an_earlier_round_refuses_before_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        first_start = head(repo, env)
        (repo / ".xp/system.md").write_text("# first-round gate motion\n")
        commit_as_reviewer(g, "first round changes gate")
        first_end = head(repo, env)
        (repo / "src.py").write_text("A = 2\n")
        commit_as_reviewer(g, "second round changes code")
        second_end = head(repo, env)
        rounds = [
            {
                "fixed": [],
                "blocking": [],
                "noted": [],
                "reviewed_head": first_start,
                "shown_sha": first_end,
            },
            {
                "fixed": [],
                "blocking": ["B"],
                "noted": [],
                "clearable_by_full": ["B"],
                "reviewed_head": first_end,
                "shown_sha": second_end,
            },
        ]
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": rounds, "shown_sha": second_end}))
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and ".xp/system.md" in result.stderr
        assert not sentinel.exists()

    def test_non_reviewer_gate_motion_keeps_the_code_motion_refusal(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"])
        (repo / ".xp" / "system.md").write_text("# later gate\n")
        g("commit", "-qam", "lead changed gate")
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "review did not cover HEAD" in result.stderr
        assert not sentinel.exists()

    def test_pending_trunk_refuses_clearance_until_the_combined_tree_is_reviewed(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"])
        g("checkout", "-q", "main")
        (repo / "trunk.py").write_text("TRUNK = 1\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved")
        g("checkout", "-q", "sprint-002")
        result = sprint(repo, env, "land")
        assert result.returncode == 2
        assert "refs/heads/main" in result.stderr and "review" in result.stderr
        assert not sentinel.exists()

    def test_pending_trunk_still_trial_merges_without_a_clearable_blocker(self, tmp_path):
        repo, env, g = make_repo(tmp_path, config=config_for("test -f trunk.py"))
        record_round(tmp_path, repo, env, [], [])
        state = json.loads(marker_path(tmp_path).read_text())
        state["rounds"][-1].pop("clearable_by_full")
        marker_path(tmp_path).write_text(json.dumps(state))
        g("checkout", "-q", "main")
        (repo / "trunk.py").write_text("TRUNK = 1\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved")
        g("checkout", "-q", "sprint-002")
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "gh" in result.stderr
        assert "tier" not in result.stderr and g("status", "--porcelain").stdout == ""

    def test_the_preview_clears_nothing_and_runs_no_tier(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"])
        before = marker_path(tmp_path).read_bytes()
        result = sprint(repo, env, "land", "--dry-run")
        assert result.returncode == 0, result.stderr
        assert "if green, the full gate clears these closer-bound blockers:\n  B" in result.stdout
        assert not sentinel.exists() and marker_path(tmp_path).read_bytes() == before

    def test_the_preview_names_the_bound_blocker_when_the_tier_cannot_run(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, config=config_for(None))
        record_round(tmp_path, repo, env, ["BOUND-IDENTITY"], ["BOUND-IDENTITY"])
        result = sprint(repo, env, "land", "--dry-run")
        assert result.returncode == 2 and "tests.full is unset" in result.stderr
        assert "did not clear these bound blockers:\n  BOUND-IDENTITY" in result.stderr

    def test_an_unbound_sprint_keeps_both_tier_refusals_undecorated(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, config=config_for(None))
        record_round(tmp_path, repo, env, [], [])
        for preview in ([], ["--dry-run"]):
            result = sprint(repo, env, "land", *preview)
            assert result.returncode == 2 and "tests.full is unset" in result.stderr
            assert "bound blockers" not in result.stderr


class TestClearancePrecedence:
    def test_ordinary_blocker_refusal_is_byte_exact_and_first(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["ORDINARY", "BOUND"], ["BOUND"])
        (repo / "dirty.py").write_text("DIRTY = 1\n")
        result = sprint(repo, env, "land")
        assert result.stderr == (
            "refused: the last round left blocking findings:\n  ORDINARY\n  BOUND\n"
            "Fix them, then review again — a flag cannot clear these\n"
        )
        assert not sentinel.exists()

    def test_identical_fixer_occurrence_remains_blocking(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["SAME", "SAME"], ["SAME"])
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and result.stderr.count("SAME") == 2
        assert not sentinel.exists()

    @pytest.mark.parametrize("binding", [None, "B", [1], ["ABSENT"], ["B", "B"]])
    def test_corrupt_round_binding_refuses_before_the_tier(self, tmp_path, binding):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], binding)
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "clearable_by_full" in result.stderr
        assert not sentinel.exists()

    def test_incomplete_round_refusal_precedes_clearance(self, tmp_path):
        sentinel = tmp_path / "tier"
        repo, env, _g = make_repo(tmp_path, config=config_for(f"touch {sentinel}"))
        record_round(tmp_path, repo, env, ["B"], ["B"], incomplete="stopped")
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "incomplete" in result.stderr
        assert "clearable_by_full" not in result.stderr and not sentinel.exists()
