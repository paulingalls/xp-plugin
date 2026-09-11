"""A shipped sprint is durable terminal state, not an inferred absence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from session_start_helpers import HOOK, run_hook_as, xp_repo
from sprint_helpers import CONFIG, make_repo, sprint

REPO = Path(__file__).parent.parent
RELEASE_PLAN = """# plan
## Milestone 1   [in-progress]
### Sprint 2
#### story-042 — done thing   [done]
Verify: true
#### story-043 — retired thing   [retired]
Verify: true
"""


def release_path(root, sprint_id=2):
    return root / "data" / "releases" / f"sprint-{sprint_id}.json"


def released_repo(root, *, versioning_off=False, merged=True):
    config = CONFIG + "lifecycle_command: true\n"
    if versioning_off:
        config += "versioning: off\n"
    repo, env, g = make_repo(root, plan=RELEASE_PLAN, config=config)
    g("tag", "v0.2.0", "main")
    g("checkout", "-q", "main")
    if merged:
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release Sprint 2")
    return repo, env, g


def run_lead(repo, root):
    payload = json.dumps({"cwd": str(repo), "session_id": "released", "source": "startup"})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        cwd=repo,
        env=env_for(root) | {"XP_ROLE": "lead"},
        capture_output=True,
        text=True,
    )


def env_for(root):
    return {"PATH": "/usr/bin:/bin", "HOME": str(root), "XP_DATA": str(root / "data")}


def next_lines(output):
    return [line for line in output.splitlines() if line.startswith("NEXT:")]


def write_record(data, sprint_id=1, **changes):
    record = {"sprint": sprint_id, "merged_sha": "a" * 40, "tag": "v0.3.0"}
    record.update(changes)
    path = data / "releases" / f"sprint-{sprint_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


class TestReleaseRecord:
    def assert_session_reads_record(self, repo, root):
        closed = next_lines(run_lead(repo, root).stdout)
        assert closed == ["NEXT: Sprint 2 was released — run `/create-sprint`"]
        plan = root / "data" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-099 — found after release   [planned]\nVerify: true\n"
        )
        opened = next_lines(run_lead(repo, root).stdout)
        assert opened == ["NEXT: Sprint 2 was released — schedule story-099 into a new sprint"]
        assert "spawn.py" not in opened[0]

    def test_versioned_post_merge_records_the_merged_head_and_tag(self, tmp_path):
        repo, env, g = released_repo(tmp_path)
        merged = g("rev-parse", "HEAD").stdout.strip()

        result = sprint(repo, env, "post-merge", sprint_id="002")

        assert result.returncode == 0, result.stderr + result.stdout
        record = json.loads(release_path(tmp_path).read_text())
        assert record == {"sprint": 2, "merged_sha": merged, "tag": "v0.3.0"}
        assert g("rev-list", "-n1", record["tag"]).stdout.strip() == merged
        assert not (tmp_path / "data" / "sprint_branch").exists()
        self.assert_session_reads_record(repo, tmp_path)

    def test_versioning_off_post_merge_records_the_merged_head_and_no_tag(self, tmp_path):
        repo, env, g = released_repo(tmp_path, versioning_off=True)
        merged = g("rev-parse", "HEAD").stdout.strip()
        tags = g("tag", "--list").stdout

        result = sprint(repo, env, "post-merge")

        assert result.returncode == 0, result.stderr + result.stdout
        assert g("tag", "--list").stdout == tags
        assert json.loads(release_path(tmp_path).read_text()) == {
            "sprint": 2,
            "merged_sha": merged,
            "tag": None,
        }
        assert not (tmp_path / "data" / "sprint_branch").exists()
        self.assert_session_reads_record(repo, tmp_path)

    @pytest.mark.parametrize("versioning_off", [False, True], ids=["versioned", "off"])
    @pytest.mark.parametrize("mode", ["dry-run", "lifecycle-refusal"])
    def test_dry_run_and_lifecycle_refusal_never_record_a_release(
        self, tmp_path, versioning_off, mode
    ):
        repo, env, _g = released_repo(tmp_path, versioning_off=versioning_off)
        if mode == "lifecycle-refusal":
            config = repo / ".xp" / "config.yml"
            config.write_text(
                config.read_text().replace("lifecycle_command: true", "lifecycle_command: false")
            )

        result = sprint(repo, env, "post-merge", *(("--dry-run",) if mode == "dry-run" else ()))

        expected = 0 if mode == "dry-run" else 2
        assert result.returncode == expected, result.stderr + result.stdout
        stream = result.stdout if mode == "dry-run" else result.stderr
        assert ("dry run" if mode == "dry-run" else "lifecycle") in stream
        assert not release_path(tmp_path).exists()
        assert (tmp_path / "data" / "sprint_branch").exists()

        if mode == "lifecycle-refusal":
            config.write_text(
                config.read_text().replace("lifecycle_command: false", "lifecycle_command: true")
            )
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()

    @pytest.mark.parametrize(
        "case",
        [
            "invalid-versioning",
            "wrong-trunk",
            "missing-branch",
            "empty-branch",
            "wrong-owner",
            "unmerged",
        ],
    )
    def test_structural_refusals_never_record_a_release(self, tmp_path, case):
        repo, env, g = released_repo(tmp_path, merged=case != "unmerged")
        branch = tmp_path / "data" / "sprint_branch"
        config = repo / ".xp" / "config.yml"
        original_config = config.read_text()
        if case == "invalid-versioning":
            config.write_text(original_config + "versioning: tags\n")
        elif case == "wrong-trunk":
            g("checkout", "-q", "sprint-002")
        elif case == "missing-branch":
            branch.unlink()
        elif case == "empty-branch":
            branch.write_text("")
        elif case == "wrong-owner":
            branch.write_text("sprint-003\n")

        refused = sprint(repo, env, "post-merge")

        assert refused.returncode == 2, refused.stderr + refused.stdout
        semantic = {
            "invalid-versioning": "only valid value",
            "wrong-trunk": "not main",
            "missing-branch": "no sprint branch recorded",
            "empty-branch": "is empty",
            "wrong-owner": "does not own",
            "unmerged": "not merged",
        }
        assert semantic[case] in refused.stderr
        assert not release_path(tmp_path).exists()
        if case == "invalid-versioning":
            config.write_text(original_config)
        elif case == "wrong-trunk":
            g("checkout", "-q", "main")
        elif case in {"missing-branch", "empty-branch", "wrong-owner"}:
            branch.write_text("sprint-002\n")
        elif case == "unmerged":
            g("merge", "-q", "--no-ff", "sprint-002", "-m", "release Sprint 2")
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()

    @pytest.mark.parametrize(
        ("case", "body"),
        [
            ("unbumpable", None),
            ("existing-tag", None),
            ("missing-config", None),
            ("unset-files", None),
            ("empty-files", None),
            ("missing-manifest", None),
            ("malformed-manifest", "{bad"),
            ("behind-manifest", '{"version": "0.2.0"}'),
            ("ahead-manifest", '{"version": "0.4.0"}'),
        ],
    )
    def test_versioned_validation_refusals_never_record_a_release(self, tmp_path, case, body):
        repo, env, g = released_repo(tmp_path)
        config = repo / ".xp" / "config.yml"
        manifest = repo / "manifest.json"
        original_config, original_manifest = config.read_text(), manifest.read_text()
        if case == "unbumpable":
            g("tag", "-d", "v0.2.0")
            g("tag", "nightly")
        elif case == "existing-tag":
            tree = g("rev-parse", "HEAD^{tree}").stdout.strip()
            other = g("commit-tree", tree, "-m", "unreachable tag owner").stdout.strip()
            g("tag", "v0.3.0", other)
        elif case == "missing-config":
            config.unlink()
        elif case == "unset-files":
            config.write_text("lifecycle_command: true\n")
        elif case == "empty-files":
            config.write_text("lifecycle_command: true\nversion_files:\n")
        elif case == "missing-manifest":
            manifest.unlink()
        else:
            manifest.write_text(body)

        refused = sprint(repo, env, "post-merge")

        assert refused.returncode == 2, refused.stderr + refused.stdout
        semantic = {
            "unbumpable": "cannot bump",
            "existing-tag": "already exists",
            "missing-config": "no .xp/config.yml",
            "unset-files": "version_files is unset or empty",
            "empty-files": "version_files is unset or empty",
            "missing-manifest": "is missing",
            "malformed-manifest": "no readable",
            "behind-manifest": "BEHIND",
            "ahead-manifest": "does not match",
        }
        assert semantic[case] in refused.stderr
        assert not release_path(tmp_path).exists()
        if case == "unbumpable":
            g("tag", "-d", "nightly")
            g("tag", "v0.2.0", "main~1")
        elif case == "existing-tag":
            g("tag", "-d", "v0.3.0")
        if not config.exists() or config.read_text() != original_config:
            config.parent.mkdir(exist_ok=True)
            config.write_text(original_config)
        if not manifest.exists() or manifest.read_text() != original_manifest:
            manifest.write_text(original_manifest)
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()

    @pytest.mark.parametrize("versioning_off", [False, True], ids=["versioned", "off"])
    def test_a_release_record_write_refusal_is_retryable(self, tmp_path, versioning_off):
        repo, env, g = released_repo(tmp_path, versioning_off=versioning_off)
        before = g("tag", "--list").stdout
        releases = tmp_path / "data" / "releases"
        releases.write_text("not a directory")

        refused = sprint(repo, env, "post-merge")

        assert refused.returncode == 2 and str(release_path(tmp_path)) in refused.stderr
        assert g("tag", "--list").stdout == before
        assert (tmp_path / "data" / "sprint_branch").read_text().strip() == "sprint-002"
        assert not release_path(tmp_path).exists()
        releases.unlink()
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()

    def test_a_tag_command_refusal_never_records_a_release(self, tmp_path):
        repo, env, g = released_repo(tmp_path)
        before = g("tag", "--list").stdout
        binary = tmp_path / "git-bin"
        binary.mkdir()
        wrapper = binary / "git"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = tag ] && [ "$2" = v0.3.0 ]; then exit 1; fi\n'
            'exec /usr/bin/git "$@"\n'
        )
        wrapper.chmod(0o755)
        original_path = env["PATH"]
        env["PATH"] = f"{binary}:{original_path}"

        refused = sprint(repo, env, "post-merge")

        assert refused.returncode == 2 and "could not create tag" in refused.stderr
        assert g("tag", "--list").stdout == before
        assert not release_path(tmp_path).exists()
        env["PATH"] = original_path
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()

    def test_a_failed_tag_compensation_names_the_stranded_state(self, tmp_path):
        repo, env, g = released_repo(tmp_path)
        releases = tmp_path / "data" / "releases"
        releases.write_text("not a directory")
        binary = tmp_path / "git-bin"
        binary.mkdir()
        wrapper = binary / "git"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = tag ] && [ "$2" = -d ]; then exit 1; fi\n'
            'exec /usr/bin/git "$@"\n'
        )
        wrapper.chmod(0o755)
        original_path = env["PATH"]
        env["PATH"] = f"{binary}:{original_path}"

        refused = sprint(repo, env, "post-merge")

        assert refused.returncode == 2
        assert str(release_path(tmp_path)) in refused.stderr
        assert "tag v0.3.0 was created but could not be removed" in refused.stderr
        assert g("tag", "--list", "v0.3.0").stdout.strip() == "v0.3.0"
        assert (tmp_path / "data" / "sprint_branch").exists()
        env["PATH"] = original_path
        releases.unlink()
        g("tag", "-d", "v0.3.0")
        retried = sprint(repo, env, "post-merge")
        assert retried.returncode == 0, retried.stderr + retried.stdout
        assert release_path(tmp_path).exists()


class TestReleasedNextAction:
    @pytest.mark.parametrize("status", ["planned", "ready", "in-progress"])
    def test_a_released_sprints_open_card_is_named_for_a_new_sprint(self, tmp_path, status):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: Sprint 1 was released — schedule story-042 into a new sprint"]
        assert "spawn.py" not in lines[0] and "/story-close" not in lines[0]

    @pytest.mark.parametrize("status", ["done", "retired"])
    def test_a_released_sprint_with_only_terminal_cards_names_create_sprint(self, tmp_path, status):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            f"# plan\n### Sprint 1\n#### story-042 — demo   [{status}]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: Sprint 1 was released — run `/create-sprint`"]
        assert "/sprint-close" not in lines[0]

    def test_a_released_sprints_surviving_tree_still_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        (tmp_path / "xp" / "worktrees" / "story-042").mkdir(parents=True)
        write_record(tmp_path / "xp")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

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

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

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

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]

    def test_an_undecodable_release_record_names_recovery(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        path = tmp_path / "xp" / "releases" / "sprint-1.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff")

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]

    def test_a_different_sprints_record_does_not_release_the_selected_sprint(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 2\n#### story-042 — demo   [done]\nVerify: true\n"
        )
        write_record(tmp_path / "xp", sprint_id=1)

        lines = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

        assert lines == ["NEXT: no open card in Sprint 2 — run `/sprint-close`"]

    def test_the_longest_released_NEXT_sentence_preserves_the_real_lead_profile(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        rules = (REPO / ".xp" / "constraints.md").read_text()
        (repo / ".xp" / "constraints.md").write_text(rules)
        (tmp_path / "xp" / "plan.md").write_text(
            "# plan\n### Sprint 1\n#### story-042 — demo   [planned]\nVerify: true\n"
        )
        write_record(tmp_path / "xp")

        output = run_hook_as(repo, tmp_path, role="lead").stdout

        assert next_lines(output) == [
            "NEXT: Sprint 1 was released — schedule story-042 into a new sprint"
        ]
        headings = [line for line in rules.splitlines() if line[:1].isdigit()]
        assert headings and all(line in output for line in headings)
        assert "--- END project content ---" in output
        assert len(output.encode()) <= 9_500

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

        output = run_hook_as(repo, tmp_path, role="lead").stdout

        lines = next_lines(output)
        assert len(lines) == 1 and str(path) in lines[0] and "unreadable" in lines[0]
        headings = [line for line in rules.splitlines() if line[:1].isdigit()]
        assert headings and all(line in output for line in headings)
        assert "--- END project content ---" in output
        assert len(output.encode()) <= 9_500
