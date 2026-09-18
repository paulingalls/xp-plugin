"""Recovery decisions after a sprint release."""

import json
from pathlib import Path

import pytest
from session_start import OUTPUT_CAP
from session_start_helpers import run_hook_as, run_recovery, xp_repo

REPO = Path(__file__).parent.parent


def next_lines(output):
    return [line for line in output.splitlines() if line.startswith("NEXT:")]


def write_record(data, sprint_id=1):
    path = data / "releases" / f"sprint-{sprint_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sprint": sprint_id, "merged_sha": "a" * 40, "tag": "v0.3.0"}))


class ReleasedNextActionCases:
    @pytest.mark.parametrize("status", ["planned", "ready", "in-progress"])
    def test_a_released_sprints_open_card_is_named_for_a_new_sprint(self, tmp_path, status):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert lines == ["NEXT: Sprint 1 was released — schedule story-042 into a new sprint"]
        assert "spawn.py" not in lines[0] and "/story-close" not in lines[0]

    @pytest.mark.parametrize("status", ["done", "retired"])
    def test_a_released_sprint_with_only_terminal_cards_names_create_sprint(self, tmp_path, status):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert lines == ["NEXT: Sprint 1 was released — run `/create-sprint`"]
        assert "/sprint-close" not in lines[0]

    def test_a_released_sprints_surviving_tree_still_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        (tmp_path / "xp" / "worktrees" / "story-042").mkdir(parents=True)
        write_record(tmp_path / "xp")

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert lines == ["NEXT: recovery required — story-042 remains after close: ABSENT"]

    @pytest.mark.parametrize(
        "body",
        [
            "{bad",
            "[]",
            "{}",
            '{"sprint": 2, "merged_sha": "abc", "tag": null}',
            '{"sprint": 1, "merged_sha": "", "tag": null}',
            '{"sprint": 1, "merged_sha": "abc", "tag": 3}',
        ],
        ids=["json", "object", "fields", "sprint", "sha", "tag"],
    )
    def test_an_unreadable_release_record_names_recovery(self, tmp_path, body):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        path = tmp_path / "xp" / "releases" / "sprint-1.json"
        path.parent.mkdir(parents=True)
        path.write_text(body)

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]
        forbidden = ("was released", "spawn.py", "/sprint-close", "/create-sprint")
        assert not any(term in lines[0] for term in forbidden)

    def test_a_directory_release_record_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        path = tmp_path / "xp" / "releases" / "sprint-1.json"
        path.mkdir(parents=True)

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]

    def test_an_undecodable_release_record_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        path = tmp_path / "xp" / "releases" / "sprint-1.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff")

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]

    def test_a_different_sprints_record_does_not_release_the_selected_sprint(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 2\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        write_record(tmp_path / "xp", sprint_id=1)

        lines = next_lines(run_recovery(repo, tmp_path).stdout)

        assert lines == ["NEXT: no open card in Sprint 2 — run `/sprint-close`"]

    def test_the_longest_released_NEXT_sentence_preserves_the_real_lead_profile(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        rules = (REPO / ".xp" / "constraints.md").read_text()
        (repo / ".xp" / "constraints.md").write_text(rules)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [planned]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        recovery = run_recovery(repo, tmp_path).stdout
        profile = run_hook_as(repo, tmp_path, role="lead").stdout

        assert next_lines(recovery) == [
            "NEXT: Sprint 1 was released — schedule story-042 into a new sprint"
        ]
        assert next_lines(profile) == []
        headings = [line for line in rules.splitlines() if line[:1].isdigit()]
        assert headings and all(line in profile for line in headings)
        assert "--- END project content ---" in profile
        assert len(profile.encode()) <= OUTPUT_CAP

    def test_an_unreadable_record_path_preserves_the_real_lead_profile(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        rules = (REPO / ".xp" / "constraints.md").read_text()
        (repo / ".xp" / "constraints.md").write_text(rules)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        path = tmp_path / "xp" / "releases" / "sprint-1.json"
        path.parent.mkdir(parents=True)
        path.write_text("{bad")

        recovery = run_recovery(repo, tmp_path).stdout
        profile = run_hook_as(repo, tmp_path, role="lead").stdout

        lines = next_lines(recovery)
        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]
        assert next_lines(profile) == []
        headings = [line for line in rules.splitlines() if line[:1].isdigit()]
        assert headings and all(line in profile for line in headings)
        assert "--- END project content ---" in profile
        assert len(profile.encode()) <= OUTPUT_CAP
