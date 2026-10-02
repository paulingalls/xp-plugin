"""Permissive installed-source faults must violate the same constructed guarantee."""

import json

import pytest
from plan_confirmation_support import events
from plan_review_install import installed_launch
from spawn_helpers import spawn
from test_plan_confirmation import assert_confirmed, damage, stopped_amended


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_confirmation_measures_submodule_contents(tmp_path, harness):
    from plan_confirmation_support import amend, submodule_consumer

    def guarantee(root, mutation=None):
        root.mkdir()
        launch = installed_launch(root, mutation, "scripts/plan_confirmation.py")
        repo, env, seen = submodule_consumer(root, harness)
        stopped = launch(repo, env, "story-042")
        assert "Which lease value" in stopped.stderr
        amend(root, repo, env, launch)
        tree = root / "data/worktrees/story-042"
        (tree / "vendor/runtime.cfg").write_text("changed dependency behavior")
        resumed = launch(repo, env, "resume", "story-042")
        assert "Which lease value" in resumed.stderr
        assert [e["role"] for e in events(seen)][2:4] == ["planner", "plan-reviewer"]

    guarantee(tmp_path / "normal")
    mutation = ("value = json.dumps(", 'value = b"unmeasured"; ignored = json.dumps(')
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault", mutation)
    assert any(e.get("kind") == "confirmation" for e in events(tmp_path / "fault/seen.jsonl"))


FAULTS = {
    "receipt": (
        "scripts/plan_confirmation.py",
        'if json.loads(receipt_path(Path(record["findings"])).read_text()) != record:',
        "if False:",
    ),
    "candidate": (
        "scripts/plan_confirmation.py",
        'if Path(record["candidate"]).read_text() != record["after"]:',
        "if False:",
    ),
    "evidence-hash": (
        "scripts/plan_confirmation.py",
        'if prior.get("plan_review_evidence_identity") != identity(evidence_file):',
        "if False:",
    ),
    "cap": (
        "scripts/plan_confirmation.py",
        "manifest = preserve(story_id, plan_file)",
        'if plan_review.review_is_capped(story_id, "plan"): return 2, "failed"\n'
        "    manifest = preserve(story_id, plan_file)",
    ),
    "artifact": (
        "scripts/plan_confirmation.py",
        'if identity(Path(record["findings"])) != record["findings_identity"]:',
        "if False:",
    ),
    "handoff": (
        "scripts/plan_confirmation.py",
        'if (\n            prior.get("plan_review_identity")',
        'if False and (\n            prior.get("plan_review_identity")',
    ),
    "chain": (
        "scripts/plan_confirmation.py",
        'if card_digest(amendment["card"]) != card_digest(current):',
        "if False:",
    ),
    "hidden": (
        "scripts/plan_confirmation.py",
        'for name in sorted(set(tracked + untracked) - {b""}):',
        "for name in []:",
    ),
    "head": ("scripts/plan_confirmation.py", 'git("rev-parse", "HEAD").hex()', '"ignored"'),
    "evidence": (
        "scripts/plan_confirmation.py",
        'if evidence["version"] != 1 or evidence["acceptance"] != record:',
        "if False:",
    ),
    "decision-absent": (
        "scripts/plan_confirmation.py",
        'if decision not in ("confirm", "replan"):',
        "if False:",
    ),
    "explanation-type": (
        "scripts/plan_confirmation.py",
        'if decision == "replan" and (not isinstance(summary, str) or not summary.strip()):',
        "if False:",
    ),
    "decision": (
        "scripts/plan_confirmation.py",
        'if decision not in ("confirm", "replan"):',
        "if False:",
    ),
    "explanation": (
        "scripts/plan_confirmation.py",
        'if decision == "replan" and (not isinstance(summary, str) or not summary.strip()):',
        "if False:",
    ),
    "question": (
        "scripts/plan_disposition.py",
        "if question is not None:",
        'if question is not None and "decision" not in report:',
    ),
    "reason": (
        "scripts/plan_disposition.py",
        'if not reasons or not all(f" {normalized_words(r)} " in plan for r in reasons):',
        "if False:",
    ),
    "motion": (
        "scripts/plan_confirmation.py",
        'if identity(Path(record["findings"])) != record["findings_identity"]:',
        "if False:",
    ),
    "predecessor": (
        "scripts/plan_confirmation.py",
        "handle.write(body)",
        'handle.write(b"lost predecessor")',
    ),
    "snapshot-failure": (
        "scripts/spawn/execution.py",
        "return stop(\n                    "
        'f"cannot preserve predecessor before planner: {error}; restore and resume", 0\n'
        "                )",
        "pass",
    ),
    "current-findings": (
        "scripts/spawn/handoff.py",
        'state["plan_review_findings"] = accepted["findings"]',
        'state["plan_review_findings"] = str(_findings(root, story_id)[0][1].resolve())',
    ),
    "retry": (
        "scripts/plan_confirmation.py",
        'while any(parent.glob(f"{story_id}.confirmation-{number}.*")):',
        "while False:",
    ),
    "force-planner": (
        "scripts/plan_confirmation.py",
        'return "confirm", bundle, ""',
        'return "fallback", None, "forced replacement"',
    ),
    "replan-review": (
        "scripts/spawn/execution.py",
        'if planned and not confirmed and (replan or prior_stages.get("plan-reviewer") != "ran"):',
        "if planned and not confirmed and False:",
    ),
}


def probe(tmp_path, fault, launch=spawn):
    if fault == "cap":
        from test_plan_confirmation import test_amended_confirmation_survives_full_review_cap

        return test_amended_confirmation_survives_full_review_cap(tmp_path, launch=launch)
    if fault in ("predecessor", "current-findings", "force-planner"):
        return assert_confirmed(tmp_path, launch)
    if fault == "retry":
        repo, env, seen, _ = stopped_amended(tmp_path, launch, question="More ruling?")
        assert launch(repo, env, "resume", "story-042").returncode != 0
        path = tmp_path / "data/plans/story-042.confirmation-1.md"
        original = path.read_bytes()
        card = tmp_path / "data/plan.md"
        card.write_text(
            card.read_text().replace("lease = 17.", "lease = 17. More ruling answered.")
        )
        assert launch(repo, env, "amend", "story-042", "--reason", "new ruling").returncode == 0
        binary = tmp_path / "bin/claude"
        binary.write_text(
            binary.read_text().replace("'human_question': 'More ruling?'", "'human_question': None")
        )
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode == 0, result.stderr
        assert path.read_bytes() == original
        return
    kwargs = {"question": "New reserved choice?"} if fault == "question" else {}
    if fault in ("decision", "decision-absent"):
        kwargs["decision"] = None if fault == "decision" else "missing"
    if fault in ("explanation", "explanation-type", "replan-review"):
        kwargs["decision"] = "replan"
    repo, env, seen, _ = stopped_amended(tmp_path, launch, **kwargs)
    if fault in ("receipt", "candidate", "evidence-hash"):
        suffix = {
            "receipt": "acceptance.json",
            "candidate": "card.md",
            "evidence-hash": "evidence.json",
        }[fault]
        path = tmp_path / f"data/plans/story-042.round-1.{suffix}"
        if fault == "receipt":
            value = json.loads(path.read_text())
            value["digest"] = "wrong"
            path.write_text(json.dumps(value))
        else:
            path.write_text(
                path.read_text() + ("changed candidate" if fault == "candidate" else " ")
            )
        (tmp_path / "replace").touch()
    elif fault in ("artifact", "motion"):
        path = tmp_path / "data/plans/story-042.round-1.md"
        if fault == "artifact":
            report = json.loads(path.read_text())
            report["summary"] = "changed authoritative finding"
            path.write_text(json.dumps(report))
        else:
            binary = tmp_path / "bin/claude"
            report = json.loads(path.read_text())
            report["summary"] = "concurrent change"
            binary.write_text(
                binary.read_text().replace(
                    " if confirming:\n",
                    f' if confirming:\n  open({str(path)!r}, "w").write({json.dumps(report)!r})\n',
                )
            )
    elif fault in ("handoff", "chain", "head", "hidden", "evidence"):
        damage(
            tmp_path,
            {
                "handoff": "handoff-identity",
                "chain": "chain-gap",
                "head": "head",
                "hidden": "assume-unchanged",
                "evidence": "version",
            }[fault],
            env,
        )
        if fault == "evidence":
            import hashlib

            path = tmp_path / "data/plans/story-042.handoff.json"
            value = json.loads(path.read_text())
            evidence = tmp_path / "data/plans/story-042.round-1.evidence.json"
            value["plan_review_evidence_identity"] = hashlib.sha256(
                evidence.read_bytes()
            ).hexdigest()
            path.write_text(json.dumps(value))
        (tmp_path / "replace").touch()
    elif fault == "snapshot-failure":
        damage(tmp_path, "missing-evidence", env)
        (tmp_path / "data/plans/story-042.predecessors").write_text("cannot create snapshots")
        (tmp_path / "replace").touch()
    elif fault == "decision-absent":
        binary = tmp_path / "bin/claude"
        binary.write_text(binary.read_text().replace(", 'decision': 'missing'", ""))
    elif fault in ("reason", "explanation", "explanation-type"):
        binary = tmp_path / "bin/claude"
        text = binary.read_text()
        if fault == "reason":
            text = text.replace(
                "'reasons': ['Courage applies the authorized lease value.']", "'reasons': []"
            )
        else:
            text = text.replace(
                "'summary': 'Old plan cannot serve amended behavior.'",
                "'summary': []" if fault == "explanation-type" else "'summary': ''",
            )
        binary.write_text(text)
    if fault in ("explanation", "explanation-type", "replan-review"):
        (tmp_path / "replace").touch()
    result = launch(repo, env, "resume", "story-042")
    observed = events(seen)
    if fault in ("handoff", "chain", "head", "hidden", "evidence", "evidence-hash"):
        assert result.returncode == 0, result.stderr
        assert all(e.get("kind") != "confirmation" for e in observed)
    elif fault == "replan-review":
        assert result.returncode == 0, result.stderr
        assert [e["role"] for e in observed][2:5] == ["plan-reviewer", "planner", "plan-reviewer"]
    else:
        assert result.returncode != 0
        assert all(e["role"] != "teammate" for e in observed)
        if fault in ("artifact", "snapshot-failure", "receipt", "candidate"):
            assert len(observed) == 2


@pytest.mark.parametrize("fault", FAULTS)
def test_confirmation_guard_detects_its_fault(tmp_path, fault):
    normal = tmp_path / "normal"
    normal.mkdir()
    probe(normal, fault)
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    relative, old, new = FAULTS[fault]
    launch = installed_launch(damaged, (old, new), relative)
    with pytest.raises(AssertionError):
        probe(damaged, fault, launch)


@pytest.mark.parametrize(
    "target", ["findings", "lost-findings", "tree", "evidence", "card", "credential"]
)
def test_launch_guard_detects_motion_after_prompt_composition(tmp_path, target):
    from plan_confirmation_support import late_launch

    def guarantee(root, mutation=None):
        root.mkdir()
        launch = late_launch(root, target, mutation)
        repo, env, seen, _ = stopped_amended(root, launch)
        binary = root / "bin/claude"
        binary.write_text(
            binary.read_text().replace(
                "elif role == 'teammate':",
                "elif role == 'teammate':\n"
                " with open(seen, 'a') as f:\n"
                "  f.write(json.dumps({'role':'teammate','started':True}) + '\\n')",
            )
        )
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode != 0
        assert all(e["role"] != "teammate" for e in events(seen))
        return events(seen)

    guarantee(tmp_path / "normal")
    mutation = (
        "for attempt in range(2):\n        if accepted:",
        "for attempt in range(2):\n        if False:",
    )
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault", mutation)
    assert len(events(tmp_path / "fault/seen.jsonl")) > 2


def test_publication_guard_detects_motion_inside_card_application(tmp_path):
    from plan_confirmation_support import late_launch

    def guarantee(root, launch):
        repo, env, _seen, _ = stopped_amended(root, launch)
        marker = root / "data/markers/story-042.ready.json"
        count = len(json.loads(marker.read_text())["review_acceptances"])
        assert launch(repo, env, "resume", "story-042").returncode != 0
        assert len(json.loads(marker.read_text())["review_acceptances"]) == count

    normal = tmp_path / "normal"
    normal.mkdir()
    guarantee(normal, late_launch(normal, "tree", publication=True))
    fault = tmp_path / "fault"
    fault.mkdir()
    scripts = fault / "cache/xp-plugin/fixture"
    launch = late_launch(fault, "tree", publication=True)
    path = scripts / "scripts/plan_acceptance.py"
    path.write_text(
        path.read_text().replace("if problem := publication_problem(record):", "if False:")
    )
    with pytest.raises(AssertionError):
        guarantee(fault, launch)


def lost_evidence_recovery(tmp_path, launch=spawn):
    from plan_confirmation_support import consumer

    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    assert launch(repo, env, "story-042").returncode != 0
    evidence = tmp_path / "data/plans/story-042.round-1.evidence.json"
    evidence.unlink()
    assert launch(repo, env, "amend", "story-042", "--reason", "evidence ruling").returncode == 0
    (tmp_path / "replace").touch()
    (tmp_path / "executor-stop").unlink()
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert [e["role"] for e in events(seen)][2:4] == ["planner", "plan-reviewer"]


def ignored_content_recovery(tmp_path, launch=spawn):
    import subprocess

    from plan_confirmation_support import consumer
    from spawn_helpers import set_system_md

    repo, env, seen = consumer(tmp_path)
    (repo / ".git/info/exclude").write_text("runtime.cfg\n")
    set_system_md(repo, "- Worktree bootstrap: `printf 'original' > runtime.cfg`")
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    assert launch(repo, env, "story-042").returncode != 0
    from plan_confirmation_support import amend

    amend(tmp_path, repo, env, launch)
    (tmp_path / "data/worktrees/story-042/runtime.cfg").write_text("changed runtime behavior")
    (tmp_path / "replace").touch()
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert [e["role"] for e in events(seen)][2:4] == ["planner", "plan-reviewer"]


@pytest.mark.parametrize("kind", ["amendment-count", "ignored-runtime"])
def test_amendment_evidence_guard_detects_its_fault(tmp_path, kind):
    guarantee = lost_evidence_recovery if kind == "amendment-count" else ignored_content_recovery
    normal = tmp_path / "normal"
    normal.mkdir()
    guarantee(normal)
    fault = tmp_path / "fault"
    fault.mkdir()
    mutation = (
        ('return len(minted.get("amendments", [])) > count', "return False")
        if kind == "amendment-count"
        else (
            'git("ls-files", "--others", "-z", "--", *paths)',
            'git("ls-files", "--others", "--exclude-standard", "-z", "--", *paths)',
        )
    )
    launch = installed_launch(fault, mutation, "scripts/plan_confirmation.py")
    with pytest.raises(AssertionError):
        guarantee(fault, launch)
    assert any(e["role"] == "teammate" for e in events(fault / "seen.jsonl"))


@pytest.mark.parametrize("kind", ["draft", "card"])
def test_prelaunch_binding_survives_motion_after_eligibility(tmp_path, kind):
    def guarantee(root, ignore_guard=False):
        root.mkdir()
        motion = (
            'Path(plan_file).write_text(Path(plan_file).read_text() + "unreviewed change\\n")'
            if kind == "draft"
            else "from work import plan_path; p = plan_path(); "
            'p.write_text(p.read_text() + "\\nAC: unreviewed card motion\\n")'
        )
        launch = installed_launch(
            root,
            ('return "confirm", bundle, ""', motion + '\n    return "confirm", bundle, ""'),
            "scripts/plan_confirmation.py",
        )
        if ignore_guard:
            filename = "plan_review.py" if kind == "draft" else "plan_confirmation.py"
            path = root / "cache/xp-plugin/fixture/scripts" / filename
            source = path.read_text()
            before = (
                "if confirmation:\n            recheck(story_id, plan_file, confirmation)"
                if kind == "draft"
                else 'if card_for(story_id) != context["current_card"]:'
            )
            assert before in source
            path.write_text(
                source.replace(
                    before,
                    before.replace("if confirmation:", "if False:")
                    if kind == "draft"
                    else "if False:",
                    1,
                )
            )
        repo, env, seen, _ = stopped_amended(root, launch)
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode != 0
        assert len(events(seen)) == 2

    guarantee(tmp_path / "normal")
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault", True)
    assert len(events(tmp_path / "fault/seen.jsonl")) > 2


def test_publication_rejects_substituting_an_identical_repository(tmp_path):
    import subprocess
    import sys

    def guarantee(root, mutation=None):
        root.mkdir()
        launch = installed_launch(root, mutation, "scripts/plan_confirmation.py")
        repo, env, _seen, _ = stopped_amended(root, launch)
        receipt = root / "data/plans/story-042.round-1.acceptance.json"
        path = receipt.with_suffix(".json").with_name("story-042.round-1.evidence.json")
        evidence = json.loads(path.read_text())
        clone = root / "other-repository"
        subprocess.run(
            ["git", "clone", "-q", evidence["repository"]["repository"], str(clone)],
            env=env,
            check=True,
        )
        code = (
            f"import sys,json;from pathlib import Path;sys.path.insert(0,"
            f"{str(root / 'cache/xp-plugin/fixture/scripts')!r});"
            "from plan_confirmation import publication_problem;"
            f"problem=publication_problem(json.loads(Path({str(receipt)!r}).read_text()));"
            "print(problem);raise SystemExit(2 if problem else 0)"
        )

        def replay():
            return subprocess.run(
                [sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True
            )

        assert replay().returncode == 0
        evidence["repository"]["repository"] = str(clone.resolve())
        path.write_text(json.dumps(evidence))
        assert replay().returncode == 2

    guarantee(tmp_path / "normal")
    with pytest.raises(AssertionError):
        guarantee(
            tmp_path / "fault",
            (
                'json.dumps({"repository": str(root), **measured}, sort_keys=True)',
                "json.dumps(measured, sort_keys=True)",
            ),
        )
