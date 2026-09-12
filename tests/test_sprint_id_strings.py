"""Sprint identifiers remain opaque across open, release, and SessionStart."""

import json
import sys
from types import SimpleNamespace

import pytest
import slate_review
from session_start_helpers import run_hook_as, run_recovery, xp_repo
from sprint_helpers import PLUGIN, sprint

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))
import release

LETTERED_PLAN = """# plan
### Sprint 2b-11 — lettered
#### story-201 — work   [{status}]
Verify: true
LETTERED-SENTINEL
"""


def next_lines(output):
    return [line for line in output.splitlines() if line.startswith("NEXT:")]


def sprint_slice(output):
    return output.split("## sprint slice\n", 1)[1].split("--- END project content ---", 1)[0]


def configure_release(repo):
    (repo / ".xp" / "config.yml").write_text(
        "release: sprint\ntrunk: main\nversion_files: manifest.json\nlifecycle_command: true\n"
    )
    (repo / "manifest.json").write_text('{"version": "0.3.0"}\n')


def test_a_lettered_sprint_opens_releases_and_reads_back_as_released(tmp_path):
    repo, g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text(LETTERED_PLAN.format(status="ready"))
    (data / "sprint_branch").write_text("sprint-2b-11\n")

    opened = run_hook_as(repo, tmp_path, role="lead")
    recovered = run_recovery(repo, tmp_path)

    assert next_lines(opened.stdout) == ["NEXT: story-201 is [ready] — run `spawn.py story-201`"]
    assert "LETTERED-SENTINEL" in sprint_slice(recovered.stdout)

    configure_release(repo)
    g("add", "-A")
    g("commit", "-qm", "configure release")
    g("tag", "v0.2.0")
    g("checkout", "-qb", "sprint-2b-11")
    (repo / "f.py").write_text("A = 2\n")
    g("add", "-A")
    g("commit", "-qm", "lettered sprint work")
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-2b-11", "-m", "release Sprint 2b-11")
    merged_sha = g("rev-parse", "HEAD").stdout.strip()
    (data / "plan.md").write_text(LETTERED_PLAN.format(status="done"))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(data)}

    closed = sprint(repo, env, "post-merge", sprint_id="2b-11")

    assert closed.returncode == 0, closed.stderr + closed.stdout
    record = json.loads((data / "releases" / "sprint-2b-11.json").read_text())
    assert record == {"sprint": "2b-11", "merged_sha": merged_sha, "tag": "v0.3.0"}
    assert g("rev-list", "-n1", "v0.3.0").stdout.strip() == merged_sha
    assert not (data / "sprint_branch").exists()
    assert next_lines(run_hook_as(repo, tmp_path, role="lead").stdout) == [
        "NEXT: Sprint 2b-11 was released — run `/create-sprint`"
    ]


def test_a_lettered_recorded_branch_selects_only_its_derived_heading(tmp_path):
    repo, _g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text(
        LETTERED_PLAN.format(status="ready")
        + "### Sprint 99\n#### story-999 — later   [ready]\nLATER-SENTINEL\n"
    )
    (data / "sprint_branch").write_text("sprint-2b-11\n")

    recovered = sprint_slice(run_recovery(repo, tmp_path).stdout)
    opened = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

    assert "recorded branch sprint-2b-11 selected plan Sprint 2b-11" in recovered
    assert "LETTERED-SENTINEL" in recovered and "LATER-SENTINEL" not in recovered
    assert opened == ["NEXT: story-201 is [ready] — run `spawn.py story-201`"]


@pytest.mark.parametrize("recorded", [True, False], ids=["recorded", "fallback"])
def test_numeric_heading_punctuation_keeps_legacy_numeric_selection(tmp_path, recorded):
    repo, _g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text(
        "# plan\n### Sprint 21: title\nTWENTY-ONE\n### Sprint 22: later\nTWENTY-TWO\n"
    )
    if recorded:
        (data / "sprint_branch").write_text("sprint-021\n")

    shown = sprint_slice(run_recovery(repo, tmp_path).stdout)

    expected = "21" if recorded else "22"
    assert f"plan Sprint {expected}" in shown
    assert ("TWENTY-ONE" in shown) is recorded
    assert ("TWENTY-TWO" in shown) is not recorded
    if not recorded:
        assert "highest-numbered fallback" in shown


def test_a_recorded_branch_with_no_derived_heading_never_falls_back(tmp_path):
    repo, _g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text(LETTERED_PLAN.format(status="ready"))
    (data / "sprint_branch").write_text("sprint-2b-12\n")

    recovered = sprint_slice(run_recovery(repo, tmp_path).stdout)
    opened = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

    assert "sprint slice UNAVAILABLE" in recovered
    assert "recorded branch sprint-2b-12 has no matching heading" in recovered
    assert "LETTERED-SENTINEL" not in recovered
    assert opened == [
        "NEXT: recovery required — next-action state is unreadable: recorded branch "
        "sprint-2b-12 has no matching heading in the plan; available headings: Sprint 2b-11"
    ]


@pytest.mark.parametrize(
    ("headings", "selected"),
    [
        ([("10", "TEN"), ("2b-11", "LETTERED"), ("2", "TWO")], "2"),
        ([("10", "TEN"), ("2", "TWO"), ("2b-11", "LETTERED")], "2b-11"),
    ],
    ids=["non-numeric-middle", "non-numeric-last"],
)
def test_a_non_numeric_heading_uses_the_last_heading_fallback(tmp_path, headings, selected):
    repo, _g = xp_repo(tmp_path)
    plan = "# plan\n" + "".join(
        f"### Sprint {identifier}\n{sentinel}-SENTINEL\n" for identifier, sentinel in headings
    )
    (tmp_path / "xp" / "plan.md").write_text(plan)

    shown = sprint_slice(run_recovery(repo, tmp_path).stdout)

    assert f"last-heading fallback selected plan Sprint {selected}" in shown
    assert "non-numeric" in shown
    selected_sentinel = dict(headings)[selected] + "-SENTINEL"
    assert selected_sentinel in shown
    assert all(
        sentinel + "-SENTINEL" not in shown
        for identifier, sentinel in headings
        if identifier != selected
    )


@pytest.mark.parametrize(
    ("sprint_id", "filename", "recorded"),
    [
        ("2b-11", "sprint-2b-11.json", "2b-12"),
        ("21", "sprint-21.json", "21"),
    ],
    ids=["another-sprint", "numeric-string"],
)
def test_release_record_identity_and_numeric_type_are_strict(
    tmp_path, sprint_id, filename, recorded
):
    repo, _g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text(
        f"# plan\n### Sprint {sprint_id}\n#### story-201 — done   [done]\n"
    )
    releases = data / "releases"
    releases.mkdir()
    (releases / filename).write_text(
        json.dumps({"sprint": recorded, "merged_sha": "a" * 40, "tag": "v0.3.0"})
    )

    opened = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

    assert opened == [
        f"NEXT: recovery required — release record {releases / filename} is unreadable"
    ]


def test_a_lettered_slate_review_marker_uses_the_writer_spelling(tmp_path, monkeypatch):
    repo, _g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    (data / "plan.md").write_text("# plan\n### Sprint 2b-11\n#### story-201 — work   [planned]\n")
    monkeypatch.setenv("XP_DATA", str(data))
    marker = slate_review.review_marker("2b-11", "slate")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}")

    opened = next_lines(run_hook_as(repo, tmp_path, role="lead").stdout)

    assert marker.name == "2b-11.slate-review-incomplete"
    assert opened == ["NEXT: Sprint 2b-11 slate review incomplete — run `slate_review.py 2b-11`"]


def test_a_non_oserror_after_tag_is_compensated_and_retryable(tmp_path, monkeypatch, capsys):
    repo, g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    configure_release(repo)
    g("add", "-A")
    g("commit", "-qm", "configure release")
    g("tag", "v0.2.0")
    g("checkout", "-qb", "sprint-002")
    g("commit", "-q", "--allow-empty", "-m", "sprint work")
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release Sprint 2")
    (data / "sprint_branch").write_text("sprint-002\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XP_DATA", str(data))
    writer = release.write_release_record

    def fail_write(_release_id, _tag):
        raise ValueError("injected record failure")

    monkeypatch.setattr(release, "write_release_record", fail_write)
    refused = release.cmd_post_merge("2")
    refusal = capsys.readouterr().err

    assert refused == 2 and "injected record failure" in refusal
    assert g("tag", "--list", "v0.3.0").stdout.strip() == ""
    assert (data / "sprint_branch").read_text().strip() == "sprint-002"
    assert not (data / "releases" / "sprint-2.json").exists()
    monkeypatch.setattr(release, "write_release_record", writer)
    assert release.cmd_post_merge("2") == 0
    assert g("tag", "--list", "v0.3.0").stdout.strip() == "v0.3.0"
    assert (data / "releases" / "sprint-2.json").is_file()


def test_versioning_off_turns_a_non_oserror_write_failure_into_a_retryable_refusal(
    tmp_path, monkeypatch, capsys
):
    repo, g = xp_repo(tmp_path)
    data = tmp_path / "xp"
    configure_release(repo)
    config = repo / ".xp" / "config.yml"
    config.write_text(config.read_text() + "versioning: off\n")
    g("add", "-A")
    g("commit", "-qm", "configure release")
    g("checkout", "-qb", "sprint-002")
    g("commit", "-q", "--allow-empty", "-m", "sprint work")
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release Sprint 2")
    (data / "sprint_branch").write_text("sprint-002\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("XP_DATA", str(data))
    writer = release.write_release_record

    def fail_write(_release_id, _tag):
        raise ValueError("injected off-mode record failure")

    monkeypatch.setattr(release, "write_release_record", fail_write)
    refused = release.cmd_post_merge("2")

    assert refused == 2 and "injected off-mode record failure" in capsys.readouterr().err
    assert (data / "sprint_branch").read_text().strip() == "sprint-002"
    monkeypatch.setattr(release, "write_release_record", writer)
    assert release.cmd_post_merge("2") == 0
    assert (data / "releases" / "sprint-2.json").is_file()


@pytest.mark.parametrize("sprint_id", ["/", ".", ".."])
def test_unsafe_sprint_ids_refuse_before_tagging_or_writing(tmp_path, monkeypatch, sprint_id):
    calls = []
    written = []
    cleared = []

    def fake_git(*args, **_kwargs):
        calls.append(args)
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return SimpleNamespace(stdout="main\n", returncode=0)
        if args[:3] == ("rev-parse", "--verify", "-q"):
            return SimpleNamespace(stdout="", returncode=1)
        if args == ("rev-parse", "HEAD"):
            return SimpleNamespace(stdout="a" * 40 + "\n", returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    (tmp_path / ".xp").mkdir()
    (tmp_path / ".xp" / "config.yml").write_text("version_files: manifest.json\n")
    monkeypatch.setattr(release, "git", fake_git)
    monkeypatch.setattr(release, "default_branch", lambda: "main")
    monkeypatch.setattr(
        release, "sprint_branch", lambda: f"sprint-{sprint_id.lstrip('0').zfill(3)}"
    )
    monkeypatch.setattr(release, "next_version", lambda _part: "v0.3.0")
    monkeypatch.setattr(release, "version_refusal", lambda _version, _names: "")
    monkeypatch.setattr(release.lc, "run", lambda *_args: 0)
    monkeypatch.setattr(release, "write_release_record", lambda *args: written.append(args))
    monkeypatch.setattr(release, "clear_sprint_branch", lambda: cleared.append(True))

    refused = release.cmd_post_merge(sprint_id)

    assert refused == 2
    assert not [args for args in calls if args and args[0] == "tag"]
    assert written == [] and cleared == []
    assert not (tmp_path / "data" / "releases").exists()
