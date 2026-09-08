"""Project-declared tier containment suppresses only checked duplicate work."""

import shlex

import pytest
from sprint_helpers import make_repo, sprint, work


def command(path, succeeds=True):
    return f"printf x >> {shlex.quote(str(path))}; {'true' if succeeds else 'false'}"


def config(tests, coverage=(), pins=()):
    lines = ["release: sprint", "roles:", "  reviewer: claude/opus", "tests:"]
    lines += [f"  {name}: {value}" for name, value in tests]
    if coverage:
        lines += ["tier_coverage:", *(f"  {name}: {value}" for name, value in coverage)]
    if pins:
        lines += ["tier_coverage_pins:", *(f"  {name}: {value}" for name, value in pins)]
    return "\n".join(lines) + "\n"


def covered_debt(repo, env, falsifier, tier):
    result = work(
        repo,
        env,
        "debt",
        "--claim",
        "covered claim",
        "--falsifier",
        falsifier,
        "--files",
        "a.py",
        "--covered-by",
        tier,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("same", (True, False))
def test_equal_tier_commands_defer_without_a_declaration(tmp_path, same):
    falsifier, tier = tmp_path / "falsifier", tmp_path / "tier"
    tagged = command(falsifier)
    full = tagged if same else command(tier)
    repo, env, _g = make_repo(tmp_path, config=config((("story", tagged), ("full", full))))
    ref = covered_debt(repo, env, tagged, "story")
    before = falsifier.read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 0 and falsifier.read_text() == before + "x"
    assert (f"trusted {ref}" in result.stdout) is same
    if not same:
        assert tier.read_text() == "x"


def test_transitive_declared_coverage_defers_the_honest_cheaper_tag(tmp_path):
    fast, story, full = (command(tmp_path / name) for name in ("fast", "story", "full"))
    cfg = config(
        (("fast", fast), ("story", story), ("full", full)),
        (("fast", "story"), ("story", "full")),
        (("fast", fast), ("story", story), ("full", full)),
    )
    repo, env, _g = make_repo(tmp_path, config=cfg)
    ref = covered_debt(repo, env, fast, "fast")
    before = (tmp_path / "fast").read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 0 and (tmp_path / "fast").read_text() == before
    assert (tmp_path / "full").read_text() == "x"
    assert f"trusted {ref}" in result.stdout and "via tier fast" in result.stdout


def test_a_red_covering_tier_runs_the_deferred_command_with_attribution(tmp_path):
    flag = tmp_path / "flag"
    flag.write_text("green")
    fast = command(tmp_path / "fast").replace("true", f"test -f {shlex.quote(str(flag))}")
    story = command(tmp_path / "story")
    full = command(tmp_path / "full", False)
    cfg = config(
        (("fast", fast), ("story", story), ("full", full)),
        (("fast", "story"), ("story", "full")),
        (("fast", fast), ("story", story), ("full", full)),
    )
    repo, env, _g = make_repo(tmp_path, config=cfg)
    ref = covered_debt(repo, env, fast, "fast")
    before = (tmp_path / "fast").read_text()
    flag.unlink()

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and (tmp_path / "fast").read_text() == before + "x"
    assert ref in result.stderr and "trusted" not in result.stdout


def test_a_changed_tier_command_refuses_before_any_execution(tmp_path):
    old_fast = command(tmp_path / "falsifier")
    current_fast = old_fast + "; true"
    full = command(tmp_path / "full")
    cfg = config(
        (("fast", current_fast), ("full", full)),
        (("fast", "full"),),
        (("fast", old_fast), ("full", full)),
    )
    repo, env, _g = make_repo(tmp_path, config=cfg)
    root = tmp_path / "data"
    root.joinpath("work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: covered\n"
        f"Falsifier: `{old_fast}`\nCovered by: fast\nFiles: a.py\n\n"
    )

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and "stale" in result.stderr and "fast" in result.stderr
    assert "tier_coverage_pins" in result.stderr and "current" in result.stderr
    assert not (tmp_path / "falsifier").exists() and not (tmp_path / "full").exists()


@pytest.mark.parametrize(
    ("coverage", "needle", "rival"),
    (
        ((("fast", "ghost"),), "absent tier(s): ghost", "cycle"),
        ((("fast", "story"), ("story", "fast")), "cycle", "absent"),
    ),
)
def test_invalid_coverage_graph_states_refuse_distinctly(tmp_path, coverage, needle, rival):
    tiers = (("fast", "true"), ("story", "true"), ("full", "true"))
    repo, env, _g = make_repo(tmp_path, config=config(tiers, coverage, tiers))

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and needle in result.stderr.lower()
    assert rival not in result.stderr.lower()


@pytest.mark.parametrize(
    ("tests", "reason"),
    (((), "absent"), ((("fast", ""),), "empty"), ((("fast", "EDIT-ME"),), "EDIT-ME")),
)
def test_unconfigured_tiers_do_not_claim_or_hide_coverage(tmp_path, tests, reason):
    falsifier = command(tmp_path / "falsifier")
    repo, env, _g = make_repo(tmp_path, config=config(tests))
    (tmp_path / "data/work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: historical\n"
        f"Falsifier: `{falsifier}`\nCovered by: fast\nFiles: a.py\n\n"
        "## debt 2026-01-02T00:00:00Z\nClaim: disposed\n"
        "Falsifier: `true`\nCovered by: fast\nFiles: a.py\n\n"
    )
    # An archived record left the batch, so a notice about IT is unpayable advice
    # repeated every close — the ratchet in miniature that this card exists to cut.
    dropped = work(repo, env, "list").stdout.splitlines()[1].split()[0]
    assert work(repo, env, "archive", "--ref", dropped, "--disposition", "d").returncode == 0
    filed = work(repo, env, "bug", "--claim", "fixed", "--falsifier", "false", "--files", "a.py")
    honest = work(
        repo,
        env,
        "resolve",
        "--ref",
        filed.stdout.strip(),
        "--falsifier",
        "true",
        "--covered-by",
        "none",
    )

    result = sprint(repo, env, "start")

    assert honest.returncode == result.returncode == 0
    assert (tmp_path / "falsifier").read_text() == "x"
    assert "coverage" in result.stdout.lower() and str(reason).lower() in result.stdout.lower()
    assert result.stdout.count("coverage unavailable for") == 1 and dropped not in result.stdout


def test_missing_and_explicit_none_coverage_are_distinct(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    refs = []
    for name in ("legacy", "explicit"):
        filed = work(repo, env, "bug", "--claim", name, "--falsifier", "false", "--files", "a.py")
        refs.append(filed.stdout.strip())
    root = tmp_path / "data"
    with root.joinpath("work.md").open("a") as ledger:
        ledger.write(
            f"## resolved 2026-01-01T00:00:00Z\nResolves: {refs[0]}\nFalsifier: `true`\n\n"
        )
    explicit = work(
        repo,
        env,
        "resolve",
        "--ref",
        refs[1],
        "--falsifier",
        "true",
        "--covered-by",
        "none",
    )
    assert explicit.returncode == 0

    result = sprint(repo, env, "start")

    assert result.returncode == 0 and "coverage not recorded (legacy)" in result.stdout
    assert "no tier runs this" in result.stdout


@pytest.mark.parametrize(
    ("tests", "pins", "needle"),
    (
        (
            (("fast", "true"), ("full", "true")),
            (("fast", "true"),),
            "tier_coverage_pins missing tier(s): full",
        ),
        (
            (("fast", ""), ("full", "true")),
            (("fast", ""), ("full", "true")),
            "unavailable tier(s): fast",
        ),
    ),
)
def test_an_undeclarable_graph_refuses_before_any_execution(tmp_path, tests, pins, needle):
    """An unpinned participant and an empty one are the two ways a declaration
    cannot be checked at all. Both must refuse: a graph accepted unpinned makes
    the pin optional, which is the whole of constraint 2's objection."""
    falsifier = command(tmp_path / "falsifier")
    repo, env, _g = make_repo(tmp_path, config=config(tests, (("fast", "full"),), pins))
    (tmp_path / "data/work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: covered\n"
        f"Falsifier: `{falsifier}`\nCovered by: fast\nFiles: a.py\n\n"
    )

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and needle in result.stderr
    assert not (tmp_path / "falsifier").exists()
