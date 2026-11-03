import json

import pytest
import xp
from test_land import commit, fake_gh, git, make_project
from xpcore import cards

CONFIG = "trunk: main\nversioning: notes\nversion_files: package.json, b.json\n"
NOTE = "Bump: minor\nA user change.\n\nRelease steps: none.\n"


def project(tmp_path, monkeypatch):
    root, data = make_project(tmp_path, monkeypatch, CONFIG)
    commit(root, {"b.json": '{"nested":{"version":"1.1.0"}, "version" : "1.1.0"}\n'}, "second")
    git(root, "tag", "-a", "v1.1.0", "-m", "initial")
    git(root, "push", "-q", "origin", "main", "--tags")
    return root, data


def branch_project(tmp_path, monkeypatch, kind, existing=False, mode="notes"):
    root, data = project(tmp_path, monkeypatch)
    if mode != "notes":
        commit(root, {".xp/config.yml": CONFIG.replace("notes", mode)}, "policy")
        git(root, "push", "-q", "origin", "main")
    if existing:
        branch = "free-fix-x" if kind == "free" else "sprint-1"
        commit(root, {f"changes/{branch}.md": NOTE + "Old text\n"}, "existing note")
        git(root, "push", "-q", "origin", "main")
    trace = tmp_path / "proof"
    if kind == "free":
        (data / "plan.md").write_text(
            "## Free patches\n\n#### free-fix — fix   [in-progress]\n"
            f"Acceptance: echo ran >> {trace}\n"
        )
        tree = data / "worktrees/free-fix"
        branch = "free-fix-x"
        git(root, "worktree", "add", "-qb", branch, str(tree))
        identifier = "fix"
    else:
        (data / "plan.md").write_text("## Sprint 1 — s\n")
        tree, branch, identifier = root, "sprint-1", "1"
        git(root, "switch", "-qc", branch)
        (data / "sprint_branch").write_text(branch)
        hook = root / ".githooks/sprint"
        hook.parent.mkdir()
        hook.write_text(f"#!/bin/sh\necho ran >> {trace}\n")
        hook.chmod(0o755)
    return root, data, tree, branch, identifier, trace


@pytest.mark.parametrize("kind", ["free", "sprint"])
@pytest.mark.parametrize(
    "problem,fix",
    [
        ("missing", "add changes/"),
        ("steps", "Release steps:"),
        ("bump", "Bump:"),
        ("changelog", "CHANGELOG.md"),
        ("version", "b.json"),
        ("valid", ""),
    ],
)
def test_land_policy_and_post_merge(tmp_path, monkeypatch, capsys, kind, problem, fix):
    gh = fake_gh(tmp_path, monkeypatch)
    root, data, tree, branch, identifier, trace = branch_project(
        tmp_path, monkeypatch, kind, problem == "missing"
    )
    files = {f"changes/{branch}.md": NOTE, "package.json": '{"version":"1.1.0", "extra":true}'}
    if problem == "steps":
        files[f"changes/{branch}.md"] = "Bump: patch\nA change\n"
    elif problem == "bump":
        files[f"changes/{branch}.md"] = "A change\nRelease steps: none.\n"
    elif problem == "changelog":
        files["CHANGELOG.md"] = "## 2.0.0\n"
    elif problem == "version":
        files["b.json"] = '{"version":"v1.1.0"}'
    commit(tree, files, "work")
    args = [kind, "land", identifier]
    if problem != "valid":
        with pytest.raises(SystemExit) as exc:
            xp.main(args)
        assert exc.value.code == 2 and fix in capsys.readouterr().err
        assert not trace.exists() and not gh.exists()
        assert not git(root, "ls-remote", "--heads", "origin", branch)
        return
    # A peer's release artifact edits must be compared against the branch's fork.
    if kind == "sprint":
        git(root, "switch", "-q", "main")
    commit(root, {"peer": "peer\n", "b.json": '{"version":"1.1.1"}'}, "peer")
    git(root, "push", "-q", "origin", "main")
    if kind == "sprint":
        git(root, "switch", "-q", branch)
    assert xp.main(args) == 0
    assert trace.read_text() == "ran\n" and gh.exists()
    if kind == "sprint":
        git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", branch, "-m", "PR")
    git(root, "push", "-q", "origin", "main")
    assert xp.main([kind, "post-merge", identifier]) == 0
    assert "next: xp.py release stamp" in capsys.readouterr().out
    assert git(root, "tag", "--list") == "v1.1.0"
    assert not git(root, "branch", "--list", branch)
    if kind == "free":
        assert not tree.exists() and cards.find_card("free-fix").status == "done"
    else:
        record = json.loads((data / "sprints/1/release.json").read_text())
        assert record["version"] == record["tag"] == ""


def pending(root):
    commit(root, {"changes/free-a.md": NOTE, "changes/README.md": "Instructions\n"}, "note")
    git(root, "push", "-q", "origin", "main")


def snapshot(root):
    return (
        git(root, "rev-parse", "HEAD"),
        git(root, "show-ref", "--tags"),
        git(root, "diff", "--cached"),
        git(root, "status", "--porcelain"),
        {
            str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        },
    )


@pytest.mark.parametrize(
    "problem,fix",
    [
        ("branch", "switch main"),
        ("dirty", "commit or discard"),
        ("behind", "fast-forward"),
        ("empty", "add changes/"),
        ("on", "versioning: notes"),
        ("off", "versioning: notes"),
    ],
)
def test_stamp_preconditions_change_nothing(tmp_path, monkeypatch, capsys, problem, fix):
    root, _ = project(tmp_path, monkeypatch)
    if problem != "empty":
        pending(root)
    else:
        commit(root, {"changes/README.md": "Instructions\n"}, "readme only")
        git(root, "push", "-q", "origin", "main")
    if problem == "branch":
        git(root, "switch", "-qc", "other")
    elif problem == "dirty":
        (root / "untracked").touch()
    elif problem == "behind":
        git(root, "reset", "--hard", "HEAD~1")
    elif problem in ("on", "off"):
        commit(root, {".xp/config.yml": CONFIG.replace("notes", problem)}, "mode")
    before = snapshot(root)
    with pytest.raises(SystemExit) as exc:
        xp.main(["release", "stamp"])
    assert exc.value.code == 2 and fix in capsys.readouterr().err
    assert snapshot(root) == before


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "bumps,version,none",
    [
        (("minor", "patch"), "1.2.0", False),
        (("patch", "patch"), "1.1.1", True),
        (("minor", "major"), "2.0.0", False),
    ],
)
def test_stamp_merges_notes_without_conflicts_and_pushes_one_version(
    tmp_path, monkeypatch, reverse, bumps, version, none
):
    root, _ = project(tmp_path, monkeypatch)
    if none:
        git(root, "branch", "-m", "stable")
        commit(
            root,
            {
                ".xp/config.yml": CONFIG.replace("main", "stable").replace(
                    "package.json, b.json", "none"
                )
            },
            "config",
        )
        git(root, "push", "-q", "origin", "stable")
    main = "stable" if none else "main"
    base = git(root, "rev-parse", "HEAD")
    for i, bump in enumerate(bumps):
        git(root, "switch", "-qc", f"change-{i}", base)
        commit(
            root,
            {f"changes/change-{i}.md": f"Bump: {bump}\nChange {i}.\nRelease steps: do {i}.\n"},
            f"note {i}",
            when=1700000000 + i,
        )
        assert not git(root, "diff", base, "--", "package.json", "b.json", "CHANGELOG.md")
    git(root, "switch", "-q", main)
    for i in [1, 0] if reverse else [0, 1]:
        git(root, "merge", "-q", "--no-ff", f"change-{i}", "-m", "PR")
    commit(
        root,
        {"changes/README.md": "Keep me\n", "CHANGELOG.md": "# History\n\n## 1.1.0\nOld\n"},
        "preamble",
    )
    git(root, "push", "-q", "origin", main)
    git(root, "tag", "v99.0.0")
    before = git(root, "rev-parse", "HEAD")
    old = (root / "b.json").read_text()
    log = tmp_path / "push"
    hook = root / ".git/hooks/pre-push"
    hook.write_text(f"#!/bin/sh\ncat >> {log}\necho END >> {log}\n")
    hook.chmod(0o755)
    assert xp.main(["release", "stamp"]) == 0
    sha = git(root, "rev-parse", "HEAD")
    assert git(root, "rev-parse", "HEAD^") == before
    assert git(root, "log", "-1", "--format=%s") == f"release: {version}"
    assert git(root, "cat-file", "-t", f"v{version}") == "tag"
    assert git(root, "rev-parse", f"v{version}^{{commit}}") == sha
    remote = git(root, "ls-remote", "origin", f"refs/heads/{main}", f"refs/tags/v{version}^{{}}")
    assert len(remote.splitlines()) == 2 and all(
        line.startswith(sha) for line in remote.splitlines()
    )
    assert len(log.read_text().splitlines()) == 3 and log.read_text().count("END") == 1
    assert f"refs/heads/{main}" in log.read_text() and f"refs/tags/v{version}" in log.read_text()
    text = (root / "CHANGELOG.md").read_text()
    assert text == (
        f"# History\n\n## {version}\n\nChange 0.\nRelease steps: do 0.\n\n"
        "Change 1.\nRelease steps: do 1.\n\n## 1.1.0\nOld\n"
    )
    assert list((root / "changes").glob("*.md")) == [root / "changes/README.md"]
    assert (root / "b.json").read_text() == (
        old if none else old.replace('"version" : "1.1.0"', f'"version" : "{version}"')
    )
    assert json.loads((root / "package.json").read_text())["version"] == (
        "1.1.0" if none else version
    )
    assert not git(root, "status", "--porcelain")


def race_hook(tmp_path, root, peer_action, extra=""):
    import shlex
    import sys

    peer = tmp_path / "peer"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(peer))
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.com")
    if peer_action == "stamp":
        command = f"{shlex.quote(sys.executable)} {shlex.quote(xp.__file__)} release stamp"
    else:
        command = (
            "mkdir -p changes; printf 'Bump: patch\\nPeer change.\\n"
            "Release steps: none.\\n' > changes/peer.md\n"
            "git add changes/peer.md\ngit commit -qm peer\ngit push -q origin main"
        )
    marker = tmp_path / "once"
    hook = root / ".git/hooks/pre-push"
    hook.write_text(f"""#!/bin/sh
if test ! -f {shlex.quote(str(marker))}; then
  touch {shlex.quote(str(marker))}
  (unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
   cd {shlex.quote(str(peer))}
   {command}
  ) || exit 1
  {extra}
fi
""")
    hook.chmod(0o755)
    return peer


@pytest.mark.parametrize("peer_action", ["stamp", "note"])
def test_stamp_recovers_concurrent_publication(tmp_path, monkeypatch, capsys, peer_action):
    root, _ = project(tmp_path, monkeypatch)
    pending(root)
    race_hook(tmp_path, root, peer_action)
    assert xp.main(["release", "stamp"]) == 0
    if peer_action == "stamp":
        assert "already stamped as v1.2.0" in capsys.readouterr().out
    else:
        text = (root / "CHANGELOG.md").read_text()
        assert "Peer change." in text and "A user change." in text
    assert git(root, "rev-parse", "HEAD") == git(root, "rev-parse", "origin/main")
    assert git(root, "log", "--format=%s", "--grep=release:").splitlines() == ["release: 1.2.0"]
    assert not git(root, "status", "--porcelain")
    tags = git(root, "ls-remote", "--tags", "origin", "refs/tags/v*")
    assert len(tags.splitlines()) == 4


@pytest.mark.parametrize("kind", ["free", "sprint"])
def test_land_uses_fetched_target_mode(tmp_path, monkeypatch, capsys, kind):
    gh = fake_gh(tmp_path, monkeypatch)
    root, data, tree, branch, identifier, trace = branch_project(
        tmp_path, monkeypatch, kind, mode="off"
    )
    if kind == "sprint":
        git(root, "add", ".githooks/sprint")
        git(root, "commit", "-qm", "sprint hook")
    stale = git(root, "rev-parse", "main")
    if kind == "sprint":
        git(root, "switch", "-q", "main")
    commit(root, {".xp/config.yml": CONFIG}, "enable notes on trunk")
    git(root, "push", "-q", "origin", "main")
    if kind == "sprint":
        git(root, "switch", "-q", branch)
        git(root, "branch", "-f", "main", stale)
    else:
        git(root, "reset", "--hard", stale)
    git(root, "update-ref", "refs/remotes/origin/main", stale)
    monkeypatch.chdir(tree)
    note = f"changes/{branch}.md"
    commit(tree, {note: "A change.\nRelease steps: none.\n"}, "invalid note")
    args = [kind, "land", identifier]
    with pytest.raises(SystemExit) as exc:
        xp.main(args)
    err = capsys.readouterr().err
    assert exc.value.code == 2 and note in err and "Bump:" in err
    assert not trace.exists() and not gh.exists()
    assert not git(root, "ls-remote", "--heads", "origin", branch)
    if kind == "free":
        assert cards.find_card("free-fix").status == "in-progress"
        record = data / "stories/free-fix/tested_tree"
    else:
        record = data / "sprints/1/land.json"
    assert not record.exists()
    commit(tree, {note: NOTE}, "correct note")
    assert xp.main(args) == 0
    assert trace.read_text() == "ran\n" and gh.exists() and record.is_file()
    assert git(root, "ls-remote", "--heads", "origin", branch)
