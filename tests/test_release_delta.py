"""Release checks at review and land boundaries."""

import json

import pytest
from close_helpers import launches
from sprint_helpers import CONFIG, make_repo, marker_path, record_reviews, sprint


@pytest.mark.parametrize("preview", [(), ("--dry-run",)])
def test_review_refuses_an_unbumped_manifest_before_launch(tmp_path, preview):
    repo, env, g = make_repo(tmp_path)
    (repo / "manifest.json").write_text('{"version": "0.2.0"}\n')
    g("commit", "-qam", "manifest behind")
    r = sprint(repo, env, "review", *preview)
    assert r.returncode == 2, r.stdout + r.stderr
    assert all(s in r.stderr for s in ("manifest.json", "0.2.0", "v0.3.0", "before the review"))
    assert not launches(tmp_path)
    assert not marker_path(tmp_path).exists()


@pytest.mark.parametrize("extra", ["versioning: off\n", "version_files: none\n", ""])
def test_review_skips_manifest_wall_when_not_applicable(tmp_path, extra):
    config = CONFIG.replace("version_files: manifest.json\n", "") + extra
    repo, env, _g = make_repo(tmp_path, config=config)
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr


def test_review_off_ignores_a_declared_manifest(tmp_path):
    repo, env, g = make_repo(tmp_path, config=CONFIG + "versioning: off\n")
    (repo / "manifest.json").write_text('{"version": "0.2.0"}\n')
    g("commit", "-qam", "manifest behind")
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr


def test_review_refuses_an_invalid_versioning_value_before_launch(tmp_path):
    repo, env, _g = make_repo(tmp_path, config=CONFIG + "versioning: on\n")
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 2 and "only valid value" in r.stderr
    assert not launches(tmp_path)


def test_review_unbumpable_tag_refuses_before_launch(tmp_path):
    repo, env, g = make_repo(tmp_path)
    g("tag", "-d", "v0.2.0")
    g("tag", "release-2024")
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 2 and "not vMAJOR.MINOR" in r.stderr
    assert "Traceback" not in r.stderr and not launches(tmp_path)


def test_review_unbumpable_tag_without_manifest_wall_still_previews(tmp_path):
    config = CONFIG.replace("version_files: manifest.json\n", "")
    repo, env, g = make_repo(tmp_path, config=config)
    g("tag", "-d", "v0.2.0")
    g("tag", "release-2024")
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr


def test_confirming_review_checks_the_manifest_again(tmp_path):
    repo, env, g = make_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    before = marker_path(tmp_path).read_bytes()
    (repo / "manifest.json").write_text('{"version": "0.2.0"}\n')
    g("commit", "-qam", "manifest behind")
    r = sprint(repo, env, "review", "--dry-run")
    assert r.returncode == 2 and "before the review" in r.stderr
    assert marker_path(tmp_path).read_bytes() == before and not launches(tmp_path)


def test_land_accepts_release_bump_and_retro(tmp_path):
    repo, env, g = make_repo(tmp_path)
    (repo / "manifest.json").write_text('{"version": "0.2.0", "name": "x"}\n')
    g("commit", "-qam", "old manifest")
    record_reviews(tmp_path, repo, env)
    (repo / "manifest.json").write_text('{"name": "x", "version": "0.3.0"}\n')
    (repo / "CHANGELOG.md").write_text("## v0.3.0 — release\n\nDetails.\n")
    (repo / ".xp" / "retro-notes.md").write_text("# retro\n")
    g("add", "-A")
    g("commit", "-qm", "release bump")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "release bump" in r.stdout
    assert "manifest.json" in r.stdout and "CHANGELOG.md" in r.stdout


@pytest.mark.parametrize("version", ["0.2.1", "0.3.0"])
def test_land_rejects_invalid_manifest_delta(tmp_path, version):
    repo, env, g = make_repo(tmp_path)
    (repo / "manifest.json").write_text('{"version": "0.2.0", "name": "x"}\n')
    g("commit", "-qam", "old manifest")
    record_reviews(tmp_path, repo, env)
    name = "changed" if version == "0.3.0" else "x"
    (repo / "manifest.json").write_text(json.dumps({"version": version, "name": name}))
    g("commit", "-qam", "invalid manifest bump")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "manifest.json" in r.stderr
    assert "did not cover HEAD" in r.stderr


@pytest.mark.parametrize(
    "before,after",
    [
        ('{"enabled": true}', '{"enabled": 1}'),
        ('{"nested": [1]}', '{"nested": [1.0]}'),
    ],
)
def test_land_rejects_manifest_value_type_changes(tmp_path, before, after):
    repo, env, g = make_repo(tmp_path)
    manifest = repo / "manifest.json"
    manifest.write_text('{"version": "0.2.0", "data": ' + before + "}\n")
    g("commit", "-qam", "old manifest")
    record_reviews(tmp_path, repo, env)
    manifest.write_text('{"version": "0.3.0", "data": ' + after + "}\n")
    g("commit", "-qam", "typed manifest delta")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "manifest.json" in r.stderr
    assert "did not cover HEAD" in r.stderr


@pytest.mark.parametrize("old", [None, "not JSON\n"])
def test_land_rejects_missing_or_malformed_recorded_manifest(tmp_path, old):
    repo, env, g = make_repo(tmp_path)
    manifest = repo / "manifest.json"
    if old is None:
        manifest.unlink()
    else:
        manifest.write_text(old)
    g("add", "-A")
    g("commit", "-qm", "unreadable old manifest")
    record_reviews(tmp_path, repo, env)
    manifest.write_text('{"version": "0.3.0"}\n')
    g("add", "manifest.json")
    g("commit", "-qm", "new manifest")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "manifest.json" in r.stderr
    assert "did not cover HEAD" in r.stderr


@pytest.mark.parametrize(
    "before,after",
    [
        ("Old section\n", "## v0.3.0 — new\n"),
        ("Old section\n", "Changed section\n## v0.3.0 — new\n"),
        ("Old section\n", "Old section\n## v0.4.0 — wrong\n"),
        (
            "top\n" + "middle\n" * 8 + "end\n",
            "## v0.3.0 — new\ntop\n" + "middle\n" * 8 + "end\nextra\n",
        ),
    ],
)
def test_land_rejects_changelog_that_is_not_one_new_section(tmp_path, before, after):
    repo, env, g = make_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text(before)
    g("add", "CHANGELOG.md")
    g("commit", "-qm", "old changelog")
    record_reviews(tmp_path, repo, env)
    (repo / "CHANGELOG.md").write_text(after)
    g("commit", "-qam", "invalid changelog")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "CHANGELOG.md" in r.stderr, r.stdout + r.stderr


def test_land_rejects_an_unrelated_path_with_release_bump(tmp_path):
    repo, env, g = make_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    (repo / "CHANGELOG.md").write_text("## 0.3.0 — release\n")
    (repo / "src.py").write_text("A = 2\n")
    g("add", "-A")
    g("commit", "-qm", "release and code")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "src.py" in r.stderr


def test_land_accepts_changelog_section_after_review(tmp_path):
    repo, env, g = make_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text("## v0.2.0 — old\n\nOld.\n")
    g("add", "CHANGELOG.md")
    g("commit", "-qm", "old changelog")
    record_reviews(tmp_path, repo, env)
    (repo / "CHANGELOG.md").write_text("## v0.2.0 — old\n\nOld.\n\n## 0.3.0 — new\n")
    g("commit", "-qam", "new section")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 0 and "CHANGELOG.md" in r.stdout, r.stdout + r.stderr


def test_land_does_not_exempt_a_release_bump_with_versioning_off(tmp_path):
    repo, env, g = make_repo(tmp_path, config=CONFIG + "versioning: off\n")
    record_reviews(tmp_path, repo, env)
    (repo / "CHANGELOG.md").write_text("## v0.3.0 — new\n")
    g("add", "CHANGELOG.md")
    g("commit", "-qm", "release prose")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "CHANGELOG.md" in r.stderr


def test_land_does_not_exempt_a_release_bump_without_target(tmp_path):
    repo, env, g = make_repo(tmp_path)
    g("tag", "-d", "v0.2.0")
    g("tag", "release-2024")
    record_reviews(tmp_path, repo, env)
    (repo / "CHANGELOG.md").write_text("## v0.3.0 — new\n")
    g("add", "CHANGELOG.md")
    g("commit", "-qm", "release prose")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "CHANGELOG.md" in r.stderr
    assert "Traceback" not in r.stderr


def test_land_rename_into_changelog_keeps_source_in_coverage(tmp_path):
    repo, env, g = make_repo(tmp_path)
    (repo / "old.md").write_text("Old text.\n")
    g("add", "old.md")
    g("commit", "-qm", "source prose")
    record_reviews(tmp_path, repo, env)
    g("mv", "old.md", "CHANGELOG.md")
    (repo / "CHANGELOG.md").write_text("## v0.3.0 — new\nOld text.\n")
    g("add", "-A")
    g("commit", "-qm", "rename into changelog")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "old.md" in r.stderr


def test_land_clearable_round_still_requires_same_head(tmp_path):
    repo, env, g = make_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    marker = marker_path(tmp_path)
    state = json.loads(marker.read_text())
    state["rounds"][0]["blocking"] = ["GATE-ME"]
    state["rounds"][0]["clearable_by_full"] = ["GATE-ME"]
    marker.write_text(json.dumps(state))
    (repo / "CHANGELOG.md").write_text("## v0.3.0 — new\n")
    g("add", "CHANGELOG.md")
    g("commit", "-qm", "release bump")
    r = sprint(repo, env, "land", "--dry-run")
    assert r.returncode == 2 and "did not cover HEAD" in r.stderr
