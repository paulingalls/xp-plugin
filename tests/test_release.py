import json

import pytest
from test_land import commit, git, make_project, manifest
from xpcore import release


@pytest.fixture
def root(tmp_path, monkeypatch):
    return make_project(tmp_path, monkeypatch)[0]


def test_agreeing_manifest_changelog_and_free_tag_pass(root):
    assert release.version_wall("minor") == "1.1.0"
    release.tag("1.1.0")
    assert git(root, "cat-file", "-t", "v1.1.0") == "tag"
    path = release.write_release_record("3", "1.1.0", "abc")
    assert json.loads(path.read_text())["tag"] == "v1.1.0"


@pytest.mark.parametrize(
    "setup, named",
    [
        (lambda r: (r / "CHANGELOG.md").write_text("## v1.0.9 — old\n"), "names 1.0.9, not 1.1.0"),
        (lambda r: git(r, "tag", "v1.1.0"), "tag v1.1.0 already exists"),
        (lambda r: git(r, "tag", "v1.2.0"), "1.1.0 is not after the latest tag v1.2.0"),
        (
            lambda r: commit(
                r,
                {
                    ".xp/config.yml": "versioning: on\nversion_files: package.json, b.json\n",
                    "b.json": '{"version": "1.0.0"}',
                },
                "b",
            ),
            "manifests disagree (package.json=1.1.0, b.json=1.0.0)",
        ),
    ],
)
def test_wall_refuses_each_mismatch_by_name(root, capsys, setup, named):
    setup(root)
    with pytest.raises(SystemExit) as exit_:
        release.version_wall("minor")
    err = capsys.readouterr().err
    assert exit_.value.code == 2 and named in err and "run again" in err


def test_none_bumps_the_latest_tag_and_unset_refuses(root, capsys):
    (root / ".xp" / "config.yml").write_text("versioning: on\nversion_files: none\n")
    git(root, "tag", "v1.4.2")
    assert release.version_wall("patch") == "1.4.3"
    assert release.version_wall("minor") == "1.5.0"
    (root / ".xp" / "config.yml").write_text("versioning: on\nsprint_cap: 6\n")
    with pytest.raises(SystemExit):
        release.version_files()
    assert "set version_files in .xp/config.yml" in capsys.readouterr().err


def test_non_json_manifest_refuses(root, capsys):
    commit(
        root,
        {".xp/config.yml": "versioning: on\nversion_files: pyproject.toml\n", **manifest("1.1.0")},
        "t",
    )
    with pytest.raises(SystemExit):
        release.version_wall("minor")
    assert "is not JSON" in capsys.readouterr().err


def test_wall_reads_the_manifests_of_the_tree_it_is_given(root, tmp_path):
    other = tmp_path / "other"
    (other / ".xp").mkdir(parents=True)
    for name, text in manifest("1.2.0").items():
        (other / name).write_text(text)
    assert release.version_wall("patch", other) == "1.2.0"
    assert release.version_wall("patch") == "1.1.0"


def test_tag_at_head_names_the_highest_release_tag_or_nothing(root):
    assert release.tag_at_head(root) == ""
    for name in ("v1.0.0", "v1.10.0", "v1.9.0", "not-a-release"):
        git(root, "tag", name)
    assert release.tag_at_head(root) == "v1.10.0"
    commit(root, {"x.txt": "x\n"}, "past the tags")
    assert release.tag_at_head(root) == ""


def test_versioning_off_skips_the_wall_and_an_unset_key_refuses(root, capsys):
    (root / "CHANGELOG.md").write_text("## v0.0.1 — wrong on purpose\n")
    (root / ".xp" / "config.yml").write_text("versioning: off\nversion_files: package.json\n")
    assert release.version_wall("minor") == ""
    (root / ".xp" / "config.yml").write_text("version_files: package.json\n")
    with pytest.raises(SystemExit) as exit_:
        release.version_wall("minor")
    assert exit_.value.code == 2 and "set versioning: on or off" in capsys.readouterr().err
