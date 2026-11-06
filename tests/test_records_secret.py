import subprocess

from test_records import PY, filing, refused, repo, state  # noqa: F401


def test_secret_never_reaches_gh(repo, monkeypatch, capsys):  # noqa: F811
    root = repo / "r"
    key = "xp_canary_" + "0123456789abcdef0123456789abcdef"
    (root / ".gitleaks.toml").write_text(
        '[[rules]]\nid = "record-canary"\ndescription = "record canary"\n'
        'regex = "xp_canary_[a-f0-9]{32}"\n'
    )
    detector = subprocess.run(
        ["gitleaks", "stdin", "--no-banner", "--redact"],
        input=key,
        text=True,
        cwd=root,
        capture_output=True,
    )
    assert detector.returncode == 1
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    command = f'''{PY} -c 'print("{key}"); raise SystemExit(3)' '''
    assert "gitleaks" in refused(capsys, filing(falsifier=command))
    assert not state(repo)["calls"]
    assert not (repo / "data" / "work.md").exists()
