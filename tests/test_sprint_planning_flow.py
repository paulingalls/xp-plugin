"""Planning and opening through installed consumers, with real instruction walks."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from test_open_sprint import falsifier, fixture, hook

PLUGIN = Path(__file__).resolve().parents[1] / "plugins/xp-plugin"


def installed(tmp_path):
    target = tmp_path / "cache/xp-plugin/fixture"
    shutil.copytree(
        Path(os.environ.get("XP_PLANNING_MUTANT", str(PLUGIN))),
        target,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return target


def command(plugin, repo, env, script, *args):
    return subprocess.run(
        [sys.executable, str(plugin / "scripts" / script), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def slate_fixture(tmp_path, harness="claude", legacy=False):
    repo, env, g, branch = fixture(tmp_path)
    plugin = installed(tmp_path)
    root = Path(env["XP_DATA"])
    cards = "".join(
        f"#### story-{n:03} — utility {n}   [planned]\n"
        f"Context: independent utility {n}.\nFiles: utility_{n}.py (new)\n"
        f"AC:\n- Given input {n}, When invoked, Then return {n}.\nVerify: true\n\n"
        for n in range(1, 8)
    )
    (root / "plan.md").write_text(
        "# Roadmap\n## Milestone 1 — utilities   [planned]\n"
        "Goal: useful utilities\nDone when: seven utilities work\n### Sprint 2\n" + cards
    )
    config = repo / ".xp/config.yml"
    role = "reviewer" if legacy else "slate-reviewer"
    config.write_text(
        f"sprint_cap: 6\ndebt_budget: 0.2\nroles:\n  {role}: {harness}/fixture\n"
        "tests:\n  full: true\n"
    )
    env |= {"CLAUDE_PLUGIN_ROOT": str(plugin), "XP_ROLE": "lead"}
    return repo, env, g, branch, plugin


def stub(tmp_path, harness):
    binary = tmp_path / "bin" / harness
    launches = tmp_path / "launches.jsonl"
    binary.write_text(
        "#!/usr/bin/env python3\nimport json, re, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        " print(json.dumps({'installed':[{'pluginId':'xp-plugin@xp-plugin',"
        "'version':'fixture'}]}"
        f" if {harness!r} == 'codex' else [{{'id':'xp-plugin@xp-plugin',"
        "'version':'fixture','scope':'user'}])); sys.exit()\n"
        "prompt = sys.stdin.read()\n"
        "fields = {key: re.search('^'+key+': (.+)$', prompt, re.M) "
        "for key in ('Goal', 'Done when')}\n"
        "received = {key: value.group(1) if value else None for key,value in fields.items()}\n"
        f"with open({str(launches)!r}, 'a') as f: f.write(json.dumps(received)+'\\n')\n"
        "path = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M).group(1)\n"
        "ids = re.findall(r'^#### (story-\\d+)', prompt, re.M)\n"
        "open(path,'w').write(''.join('## '+i+' — GREEN\\n' for i in ids)"
        "+'## Slate — GREEN\\n## Unresolved\\n')\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message',"
        "'text':'review complete'}}"
        f" if {harness!r} == 'codex' else {{'type':'result','result':'review complete'}}))\n"
    )
    binary.chmod(0o755)
    return launches


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("legacy", [False, True])
def test_over_guidance_slate_reviews_and_opens(tmp_path, harness, legacy):
    repo, env, _g, branch, plugin = slate_fixture(tmp_path, harness, legacy)
    launches = stub(tmp_path, harness)
    reviewed = command(plugin, repo, env, "slate_review.py", "2")
    assert reviewed.returncode == 0, reviewed.stderr
    assert json.loads(launches.read_text()) == {
        "Goal": "useful utilities",
        "Done when": "seven utilities work",
    }
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text().replace("useful utilities", "seven useful utilities"))
    opened = command(plugin, repo, env, "open_sprint.py", "2")
    assert opened.returncode == 0, opened.stderr
    assert len(launches.read_text().splitlines()) == 1
    assert branch.read_text() == "sprint-002\n"
    assert plan.read_text().count("#### story-") == 7
    assert "[in-progress]" in plan.read_text()
    assert sorted(p.name for p in Path(env["XP_DATA"]).iterdir()) == [
        "locks",
        "logs",
        "markers",
        "plan.md",
        "slate-reviews",
        "sprint_branch",
        "timing.jsonl",
        "timing.jsonl.lock",
    ]


def test_reviewed_open_runs_only_open_lifecycle(tmp_path):
    repo, env, g, branch, plugin = slate_fixture(tmp_path)
    launches = stub(tmp_path, "claude")
    event = hook(repo, tmp_path)
    batch = falsifier(tmp_path)
    close = tmp_path / "close-event"
    sentinel = tmp_path / "close.py"
    sentinel.write_text(f"from pathlib import Path; Path({str(close)!r}).write_text('ran')\n")
    config = repo / ".xp/config.yml"
    config.write_text(
        config.read_text().replace(
            "full: true", f"full: {shlex.join([sys.executable, str(sentinel)])}"
        )
        + f"preflight: {shlex.join([sys.executable, str(sentinel)])}\n"
    )
    g("add", "-A")
    g("commit", "-qm", "instrument lifecycle and close")
    reviewed = command(plugin, repo, env, "slate_review.py", "2")
    assert reviewed.returncode == 0, reviewed.stderr
    findings = next((Path(env["XP_DATA"]) / "slate-reviews").glob("*.md"))
    before = findings.read_bytes()
    result = command(plugin, repo, env, "open_sprint.py", "2")
    assert result.returncode == 0, result.stderr
    assert event.read_text() == "sprint-open 2"
    assert not batch.exists() and not close.exists()
    assert "retro" not in result.stdout and "triage" not in result.stdout
    assert len(launches.read_text().splitlines()) == 1
    assert findings.read_bytes() == before
    assert "[in-progress]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
    assert branch.read_text() == "sprint-002\n"
    repeated = command(plugin, repo, env, "open_sprint.py", "2")
    assert repeated.returncode == 2 and "already open" in repeated.stderr
    assert event.read_text() == "sprint-open 2"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong",
        "trunk",
        "detached",
        "missing-plan",
        "absent-members",
        "empty-members",
        "conflict",
        "empty-record",
        "unreadable-record",
        "done",
        "retired",
        "already-open",
        "nonlead",
        "live-review",
    ],
)
def test_invalid_open_dispatch_has_no_effects(tmp_path, defect):
    repo, env, g, branch = fixture(tmp_path)
    plugin = installed(tmp_path)
    output = hook(repo, tmp_path)
    root = Path(env["XP_DATA"])
    plan = root / "plan.md"
    if defect == "wrong":
        g("branch", "-m", "sprint-wrong")
    elif defect == "trunk":
        g("checkout", "-q", "main")
    elif defect == "detached":
        g("checkout", "-q", "--detach")
    elif defect == "missing-plan":
        plan.unlink()
    elif defect == "absent-members":
        plan.write_text("# Roadmap\n### Sprint 3\n")
    elif defect == "empty-members":
        plan.write_text("# Roadmap\n### Sprint 2\n")
    elif defect in {"conflict", "empty-record", "already-open"}:
        branch.write_text(
            {"conflict": "sprint-003\n", "empty-record": "", "already-open": "sprint-002\n"}[defect]
        )
    elif defect == "unreadable-record":
        branch.mkdir()
    elif defect in {"done", "retired"}:
        plan.write_text(plan.read_text().replace("[ready]", f"[{defect}]"))
    elif defect == "nonlead":
        env["XP_ROLE"] = "executor"
    elif defect == "live-review":
        marker = root / "markers/2.slate-review-incomplete"
        marker.parent.mkdir()
        marker.write_text(json.dumps({"pid": os.getpid()}))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    head = g("rev-parse", "HEAD").stdout
    result = command(plugin, repo, env, "open_sprint.py", "2")
    assert result.returncode == 2, result.stdout + result.stderr
    messages = {
        "wrong": "from sprint-002",
        "trunk": "not trunk",
        "detached": "not trunk",
        "missing-plan": "plan",
        "absent-members": "no `### Sprint 2`",
        "empty-members": "no `### Sprint 2`",
        "conflict": "records sprint-003",
        "empty-record": "is empty",
        "unreadable-record": "not readable",
        "done": "nothing to open",
        "retired": "nothing to open",
        "already-open": "already open",
        "nonlead": "only the lead",
        "live-review": "slate review running",
    }
    assert messages[defect] in result.stderr
    assert not output.exists()
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert g("rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("post_hook", [False, True])
def test_failed_lifecycle_does_not_commit_opening(tmp_path, post_hook):
    repo, env, _g, branch = fixture(tmp_path)
    plugin = installed(tmp_path)
    root = Path(env["XP_DATA"])
    script = tmp_path / "lifecycle.py"
    marker = root / "markers/2.slate-review-incomplete"
    script.write_text(
        f"import json, os\nfrom pathlib import Path\np=Path({str(marker)!r})\n"
        "p.parent.mkdir(exist_ok=True)\n"
        f"p.write_text(json.dumps({{'pid':{os.getpid()}}}))\n"
        if post_hook
        else "raise SystemExit(7)\n"
    )
    config = repo / ".xp/config.yml"
    config.write_text(f"lifecycle_command: {shlex.join([sys.executable, str(script)])}\n")
    before = (root / "plan.md").read_bytes()
    result = command(plugin, repo, env, "open_sprint.py", "2")
    assert result.returncode == 2, result.stderr
    assert not branch.exists()
    assert (root / "plan.md").read_bytes() == before


@pytest.mark.slow
@pytest.mark.parametrize("harness,model", [("claude", "sonnet"), ("codex", "gpt-6.1-sol")])
def test_planning_instructions_walk_actual_harness(tmp_path, harness, model):
    binary = shutil.which(harness)
    assert binary, f"Install {harness}: the actual planning instruction walk is required"
    repo, env, _g, branch, plugin = slate_fixture(tmp_path, harness)
    env = os.environ | env | {"HOME": os.environ["HOME"], "PATH": os.environ["PATH"]}
    config = repo / ".xp/config.yml"
    config.write_text(config.read_text().replace(f"{harness}/fixture", f"{harness}/{model}"))
    root = Path(env["XP_DATA"])
    artifact = Path(tempfile.mkdtemp(prefix=f"story-177-walk-{harness}-"))
    prompt = f"""You are the lead in this isolated consuming repo: {repo}.
Read {plugin}/skills/create-sprint/SKILL.md, {plugin}/templates/plan.md and
{plugin}/PROCESS.md. Walk those instructions using this candidate installed plugin.
XP_DATA={root}; CLAUDE_PLUGIN_ROOT={plugin}. Only edit this disposable consumer.
Human decision: author seven independent useful Python text utilities, one per card,
for sprint 2, even though sprint_cap is 6. Choose distinct new files, meaningful
observable acceptance, and Verify commands that will discriminate the implementation.
Keep milestone 1 planned until opening. Do not implement the utilities.
Run the instructed independent slate_review.py 2 through the configured actual
{harness} harness, judge every native finding, apply authorized scoped corrections,
and save your disposition at {artifact}/lead-disposition.md. Open using the printed
open_sprint.py command on sprint-002. Opening must produce only sprint-open lifecycle.
Then construct sprint 3 with a real unresolved human decision: the utility must send
customer text to an external destination but the human has not chosen/authorized one.
Run its independent slate review, surface that blocker, and escalate without opening 3.
Lastly attempt opening 3 from sprint-002 and observe refusal without effects.
Save executed argv/exits and your observations at {artifact}/execution.md.
Do not fabricate review findings. Missing/broken harness is an unmet AC: report it.
"""
    event = hook(repo, tmp_path)
    (artifact / "prompt.md").write_text(prompt)
    argv = (
        [
            binary,
            "-p",
            "--plugin-dir",
            str(plugin),
            "--dangerously-skip-permissions",
            "--output-format",
            "json",
            "--model",
            model,
        ]
        if harness == "claude"
        else [binary, "exec", "--json", "--sandbox", "danger-full-access", "-m", model, "-"]
    )
    (artifact / "argv.json").write_text(json.dumps(argv))
    try:
        result = subprocess.run(
            argv, input=prompt, cwd=repo, env=env, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired as exc:
        (artifact / "timeout.txt").write_text(str(exc))
        pytest.fail(f"{harness} instruction walk timed out; evidence: {artifact}")
    (artifact / "stdout.jsonl").write_text(result.stdout)
    (artifact / "stderr.txt").write_text(result.stderr)
    (artifact / "exit.txt").write_text(str(result.returncode))
    shutil.copytree(root, artifact / "data", dirs_exist_ok=True)
    assert result.returncode == 0, f"Actual {harness} walk failed: {artifact}: {result.stderr}"
    assert branch.is_file(), f"Actual {harness} did not open: inspect {artifact}"
    assert branch.read_text() == "sprint-002\n"
    assert event.read_text() == "sprint-open 2"
    plan = (root / "plan.md").read_text()
    assert plan.split("### Sprint 3")[0].count("#### story-") == 7
    assert "[in-progress]" in plan
    reviews = root / "slate-reviews"
    assert len(list(reviews.glob("sprint-2.round-*.md"))) == 1
    blocker = list(reviews.glob("sprint-3.round-*.md"))
    assert len(blocker) == 1
    assert "## Slate — RED" in blocker[0].read_text(), f"Missing blocker judgment: {artifact}"
    assert (artifact / "lead-disposition.md").is_file()
    assert (artifact / "execution.md").is_file()


GUARD_MUTATIONS = {
    "wrong": (
        "if branch != (expected := env.sprint_branch_name(sprint_id)):",
        "if (expected := env.sprint_branch_name(sprint_id)) and False:",
    ),
    "trunk": ("if not branch or branch == default_branch():", "if False:"),
    "detached": ("if not branch or branch == default_branch():", "if False:"),
    "missing-plan": ("if not plan.exists():", "if False:"),
    "absent-members": ("if not members:", "if False:"),
    "empty-members": ("if not members:", "if False:"),
    "conflict": ("if recorded:", "if False:"),
    "done": ("if terminal:", "if False:"),
    "retired": ("if terminal:", "if False:"),
    "already-open": ("if recorded == branch:", "if False:"),
    "nonlead": ('if role != "lead":', "if False:"),
    "live-review": ("if running := _running_slate_refusal(sprint_id):", 'if (running := ""):'),
}


@pytest.mark.meta
@pytest.mark.parametrize("defect", [*GUARD_MUTATIONS, "empty-record", "unreadable-record"])
def test_open_refusal_mutants(tmp_path, defect):
    plugin = installed(tmp_path)
    path = plugin / "scripts/open_sprint.py"
    if defect in {"empty-record", "unreadable-record"}:
        path = plugin / "scripts/env.py"
        old = "def sprint_branch() -> str:\n"
        new = old + '    return ""\n'
    else:
        old, new = GUARD_MUTATIONS[defect]
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    node = f"test_invalid_open_dispatch_has_no_effects[{defect}]"
    assert_mutant_red(plugin, node)


def assert_mutant_red(plugin, node):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"{__file__}::{node}"],
        env=os.environ | {"XP_PLANNING_MUTANT": str(plugin)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert node in result.stdout and "FAILED" in result.stdout, result.stdout
    assert "ERROR collecting" not in result.stdout


@pytest.mark.meta
@pytest.mark.parametrize(
    "defect", ["preflight", "batch", "full", "review", "branch", "milestone", "cap", "goal"]
)
def test_open_separation_mutants(tmp_path, defect):
    plugin = installed(tmp_path)
    path = plugin / "scripts/open_sprint.py"
    text = path.read_text()
    if defect == "goal":
        path = plugin / "scripts/slate_review.py"
        text = path.read_text().replace(
            'return "\\n".join([owner.heading.rstrip(), *fields, cards])', "return cards"
        )
    elif defect == "branch":
        text = text.replace("    env.record_sprint_branch(branch)\n", "", 1)
    elif defect == "milestone":
        text = text.replace("        move(sprint_id)", "        pass")
    else:
        injected = {
            "preflight": '    import preflight; preflight.check(config_flat("preflight"))\n',
            "batch": "    from falsifier_batch import execute_batch, grouped_batch\n"
            "    from work import data_root\n"
            "    execute_batch(grouped_batch(data_root())[0])\n",
            "full": "    import subprocess, shlex\n"
            "    from work import config_block_value\n"
            '    subprocess.run(shlex.split(config_block_value("tests")["full"]))\n',
            "review": "    from slate_review import cmd_review\n    cmd_review(sprint_id, False)\n",
            "cap": '    if len(members) > int(config_flat("sprint_cap")):\n'
            '        return fail("capacity exceeded")\n',
        }[defect]
        text = text.replace("    if dry_run:\n", injected + "    if dry_run:\n", 1)
    path.write_text(text)
    node = (
        "test_over_guidance_slate_reviews_and_opens[False-claude]"
        if defect in {"cap", "goal"}
        else "test_reviewed_open_runs_only_open_lifecycle"
    )
    assert_mutant_red(plugin, node)


@pytest.mark.meta
@pytest.mark.parametrize("post_hook", [False, True])
def test_lifecycle_boundary_mutants(tmp_path, post_hook):
    plugin = installed(tmp_path)
    path = plugin / "scripts/open_sprint.py"
    text = path.read_text()
    if post_hook:
        old = "    if running := _running_slate_refusal(sprint_id):\n        return fail(running)\n"
        first, separator, rest = text.partition(old)
        assert separator and old in rest
        text = first + separator + rest.replace(old, "", 1)
    else:
        text = text.replace(
            'if red := lc.run(config_flat(lc.KEY), "sprint-open", sprint_id):', 'if (red := ""):'
        )
    path.write_text(text)
    assert_mutant_red(plugin, f"test_failed_lifecycle_does_not_commit_opening[{post_hook}]")


def test_milestone_without_slate_refuses_review(tmp_path):
    repo, env, _g, _branch, plugin = slate_fixture(tmp_path)
    launch = stub(tmp_path, "claude")
    (Path(env["XP_DATA"]) / "plan.md").write_text(
        "## Milestone 1   [planned]\nGoal: utilities\nDone when: true\n### Sprint 2\n"
    )
    result = command(plugin, repo, env, "slate_review.py", "2")
    assert result.returncode == 2 and "no Sprint 2 slate" in result.stderr
    assert not launch.exists()


@pytest.mark.meta
def test_milestone_is_not_sprint_membership_mutant(tmp_path):
    plugin = installed(tmp_path)
    path = plugin / "scripts/slate_review.py"
    text = path.read_text()
    old = "if cards and (owner := find(text, sprint_id)):"
    assert old in text
    path.write_text(text.replace(old, "if (owner := find(text, sprint_id)):"))
    assert_mutant_red(plugin, "test_milestone_without_slate_refuses_review")
