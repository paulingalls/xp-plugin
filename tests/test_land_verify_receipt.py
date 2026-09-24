import json

import pytest
from close_helpers import FIX_PATCH, close, make_repo, mint_ready, stub_reviewer


def counted_repo(tmp_path, declaration=None):
    calls = tmp_path / "verify-calls"
    repo, env, git = make_repo(tmp_path, verify=f"sh -c 'echo call >> {calls}'")
    if declaration is not None:
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Verify: ", f"Verify reads: {declaration}\nVerify: ")
        )
        mint_ready(repo, env)
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    assert calls.read_text().splitlines() == ["call"]
    return repo, env, git, calls


def trunk_change(repo, git, path):
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert git("checkout", "main").returncode == 0
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("trunk change\n")
    assert git("add", path).returncode == 0
    assert git("commit", "-qm", "trunk moved").returncode == 0
    assert git("checkout", branch).returncode == 0


def test_exact_review_tree_reuses_verify(tmp_path):
    verify_calls = tmp_path / "verify-calls"
    tier_calls = tmp_path / "tier-calls"
    repo, env, git = make_repo(
        tmp_path,
        verify=f"sh -c 'echo call >> {verify_calls}'",
        files="src/thing.py, .xp/config.yml",
    )
    config = repo / ".xp" / "config.yml"
    config.write_text(
        config.read_text().replace("story: true", f"story: sh -c 'echo call >> {tier_calls}'")
    )
    git("add", ".xp/config.yml")
    git("commit", "-qm", "configure tier")
    assert close(repo, env, "review").returncode == 0
    assert verify_calls.read_text().splitlines() == ["call"]
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert verify_calls.read_text().splitlines() == ["call"]
    assert tier_calls.read_text().splitlines() == ["call"]
    assert "skipped on exact tree" in landed.stdout


@pytest.mark.parametrize(
    ("declaration", "path", "skips"),
    [
        (None, "docs/x.md", False),
        ("src/app/", "docs/x.md", True),
        ("src/app/", "src/app/y.py", False),
    ],
)
def test_merge_inputs_control_reuse(tmp_path, declaration, path, skips):
    repo, env, git, calls = counted_repo(tmp_path, declaration)
    trunk_change(repo, git, path)
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == (1 if skips else 2)
    if skips:
        assert "skipped on declared inputs" in landed.stdout
        assert declaration in landed.stdout and path in landed.stdout
    else:
        assert "Verify ran:" in landed.stdout


@pytest.mark.parametrize("declaration", [None, "src/app/"])
def test_story_commit_after_review_runs_verify(tmp_path, declaration):
    repo, env, git, calls = counted_repo(tmp_path, declaration)
    (repo / "src" / "thing.py").write_text("A = 3\n")
    git("add", "src/thing.py")
    git("commit", "-qm", "later story work")
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert "Verify ran:" in landed.stdout


@pytest.mark.parametrize("condition", ["missing", "unreadable"])
def test_receipt_failure_runs_verify_and_names_state(tmp_path, condition):
    repo, env, _git, calls = counted_repo(tmp_path)
    receipt = tmp_path / "data" / "markers" / "story-042.verify.json"
    if condition == "missing":
        receipt.unlink()
    else:
        receipt.write_text("{bad json")
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert f"Verify ran: Verify receipt {condition}" in landed.stdout


def test_receipt_records_reviewed_tree_and_commands(tmp_path):
    _repo, _env, git, _calls = counted_repo(tmp_path)
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["tree"] == git("write-tree").stdout.strip()
    assert receipt["head"] == git("rev-parse", "HEAD").stdout.strip()
    assert receipt["raw"] and receipt["verify"]
    assert receipt["reads"] is None


def test_reviewer_patch_tree_is_the_receipted_tree(tmp_path):
    repo, env, git = make_repo(tmp_path)
    stub_reviewer(tmp_path, patch=FIX_PATCH)
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["tree"] == git("write-tree").stdout.strip()
    assert receipt["head"] == git("rev-parse", "HEAD").stdout.strip()
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert "skipped on exact tree" in landed.stdout


def test_interrupted_review_verify_leaves_no_receipt(tmp_path):
    stopper = tmp_path / "stopper"
    stopper.write_text("#!/bin/sh\nkill -TERM $$\n")
    stopper.chmod(0o755)
    repo, env, _git = make_repo(tmp_path, verify=str(stopper))
    result = close(repo, env, "review")
    assert result.returncode != 0
    assert not (tmp_path / "data/markers/story-042.verify.json").exists()


def test_verify_reads_is_not_files_scope():
    from review_scope import declared_files

    assert declared_files("Files: src/thing.py\nVerify reads: src/app/\nVerify: true") == {
        "src/thing.py"
    }


@pytest.mark.parametrize("field", ["Verify", "Verify reads"])
def test_amended_card_field_runs_verify(tmp_path, field):
    repo, env, _git, calls = counted_repo(tmp_path, "src/app/")
    plan = tmp_path / "data/plan.md"
    if field == "Verify reads":
        plan.write_text(plan.read_text().replace("Verify reads: src/app/", "Verify reads: docs/"))
    else:
        plan.write_text(plan.read_text().replace("Verify: sh -c", "Verify: env sh -c"))
    mint_ready(repo, env)
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert f"Verify ran: {field}" in landed.stdout


def test_red_review_leaves_no_receipt(tmp_path):
    repo, env, _git, calls = counted_repo(tmp_path)
    receipt = tmp_path / "data/markers/story-042.verify.json"
    assert receipt.exists()
    plan = tmp_path / "data/plan.md"
    plan.write_text(plan.read_text().replace("Verify: sh -c", "Verify: false && sh -c"))
    mint_ready(repo, env)
    red = close(repo, env, "review")
    assert red.returncode != 0
    assert not receipt.exists()
    assert calls.read_text().splitlines() == ["call"]


def test_slate_bundle_uses_shipped_card_template(tmp_path):
    from slate_review_helpers import slate_repo, slate_review, stub_slate_reviewer

    repo, env = slate_repo(tmp_path)
    launch = stub_slate_reviewer(tmp_path)
    assert "Verify reads:" not in (tmp_path / "data/plan.md").read_text()
    result = slate_review(repo, env)
    assert result.returncode == 0, result.stderr
    prompt = json.loads(launch.read_text())["prompt"]
    assert "## Shipped card template" in prompt
    assert "Verify reads:" in prompt
