"""Disposed-record compaction keeps executable state and moves durable prose."""

import subprocess
import sys

from sprint_helpers import PLUGIN, make_repo, sprint

WORK = PLUGIN / "scripts" / "work.py"
sys.path.insert(0, str(WORK.parent))
import sprint_close  # noqa: E402
import work  # noqa: E402


def run(root, *args, story=""):
    env = {"XP_DATA": str(root), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(WORK), *args],
        env=env | ({"XP_STORY_ID": story} if story else {}),
        capture_output=True,
        text=True,
    )


def last_id(root):
    return run(root, "list").stdout.strip().splitlines()[-1].split()[0]


def seed(root):
    run(root, "note", "ACTIVE RECORD SENTINEL")
    active = dict(work.entries(root))[last_id(root)]
    run(root, "note", "archived note claim and evidence", story="story-042")
    note = last_id(root)
    run(root, "archive", "--ref", note, "--disposition", "superseded", story="story-042")
    run(
        root,
        "debt",
        "--claim",
        "archived debt claim",
        "--falsifier",
        "true",
        "--files",
        "d.py",
        story="story-042",
    )
    debt = last_id(root)
    run(root, "resolve", "--ref", debt, "--falsifier", "printf resolved >/dev/null")
    run(root, "archive", "--ref", debt, "--disposition", "accepted risk", story="story-042")
    run(root, "bug", "--claim", "resolved bug claim", "--falsifier", "false", "--files", "b.py")
    bug = last_id(root)
    run(root, "resolve", "--ref", bug, "--falsifier", "true")
    return active, (note, debt, bug)


def execute_corpus(root):
    return [
        (ref, headline, command, subprocess.run(command, shell=True).returncode)
        for ref, headline, command in sprint_close.corpus(root)
    ]


def test_compact_preserves_the_executed_corpus_and_active_record(tmp_path):
    active, refs = seed(tmp_path)
    before = execute_corpus(tmp_path)
    assert run(tmp_path, "compact").returncode == 0
    assert execute_corpus(tmp_path) == before

    compacted = (tmp_path / "work.md").read_text()
    archived = (tmp_path / "archive.md").read_text()
    assert active in compacted
    for ref in refs:
        assert f"Id: {ref}" in compacted and f"# Record {ref}" in archived
    assert "Disposition: superseded\n" in compacted
    assert "printf resolved >/dev/null" in compacted
    assert "Disposition: resolved" in compacted
    assert "archived note claim and evidence" not in compacted
    assert "archived note claim and evidence" in archived
    assert "Files: d.py" not in compacted and "Files: d.py" in archived
    assert "Files: b.py" not in compacted and "Files: b.py" in archived


def test_archive_failure_leaves_the_only_work_copy_unchanged(tmp_path):
    seed(tmp_path)
    before = (tmp_path / "work.md").read_bytes()
    (tmp_path / "archive.md").mkdir()
    result = run(tmp_path, "compact")
    assert result.returncode == 2
    assert (tmp_path / "work.md").read_bytes() == before


def test_archive_verification_failure_precedes_work_rewrite(tmp_path):
    _active, refs = seed(tmp_path)
    before = (tmp_path / "work.md").read_bytes()
    (tmp_path / "archive.md").write_text(f"# Record {refs[0]}\n\nCORRUPT\n")
    result = run(tmp_path, "compact")
    assert result.returncode == 2 and "does not match" in result.stderr
    assert (tmp_path / "work.md").read_bytes() == before


def test_retry_after_archive_write_does_not_duplicate_prose(tmp_path):
    first, retry = tmp_path / "first", tmp_path / "retry"
    seed(first)
    original = (first / "work.md").read_bytes()
    assert run(first, "compact").returncode == 0
    retry.mkdir()
    (retry / "work.md").write_bytes(original)
    (retry / "archive.md").write_bytes((first / "archive.md").read_bytes())
    assert run(retry, "compact").returncode == 0
    assert (retry / "archive.md").read_bytes() == (first / "archive.md").read_bytes()
    assert (retry / "work.md").read_bytes() == (first / "work.md").read_bytes()


def test_a_second_disposal_of_a_compacted_record_still_compacts(tmp_path):
    _active, refs = seed(tmp_path)
    assert run(tmp_path, "compact").returncode == 0
    assert (
        run(tmp_path, "archive", "--ref", refs[0], "--disposition", "dropped later").returncode == 0
    )
    result = run(tmp_path, "compact")
    assert result.returncode == 0, result.stderr
    compacted = (tmp_path / "work.md").read_text()
    assert "Disposition: dropped later\n" in compacted and "## archived " not in compacted
    assert "dropped later" in (tmp_path / "archive.md").read_text()


def test_only_active_records_is_a_no_op(tmp_path):
    run(tmp_path, "note", "ACTIVE ONLY")
    before = (tmp_path / "work.md").read_bytes()
    assert run(tmp_path, "compact").returncode == 0
    assert (tmp_path / "work.md").read_bytes() == before
    assert not (tmp_path / "archive.md").exists()


def test_free_text_cannot_forge_a_compacted_record_id(tmp_path):
    run(tmp_path, "note", "body\nId: deadbeef")
    assert last_id(tmp_path) != "deadbeef"


def test_compacted_archived_note_stays_out_of_sprint_triage(tmp_path):
    repo, env, _git = make_repo(tmp_path)

    def project_work(*args):
        return subprocess.run(
            [sys.executable, str(WORK), *args], cwd=repo, env=env, capture_output=True, text=True
        )

    project_work("note", "ARCHIVE-ME-SENTINEL")
    ref = project_work("list").stdout.split()[0]
    project_work("archive", "--ref", ref, "--disposition", "dropped")
    assert project_work("compact").returncode == 0
    result = sprint(repo, env, "start")
    assert result.returncode == 0 and "ARCHIVE-ME-SENTINEL" not in result.stdout
