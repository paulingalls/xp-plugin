#!/usr/bin/env python3
"""Carried read cost of xp agent runs in this machine's Codex rollouts.

A tool output is re-sent, at the cached rate, on every later model call of its run, so its
cost is its tokens times the calls after it. This sums that, in millions of token-calls per
run, for three kinds of read: a bundled source re-read (.xp/constraints.md, .xp/system.md,
plan.md, plan-review.md), a whole-file cat over 8K tokens, and everything.

Usage: python3 tests/scripts/read_cost.py [--since YYYY-MM-DD] [--until YYYY-MM-DD]
(default: the last 14 days). Claude-harness seats are not counted.
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BUNDLED = re.compile(r"\.xp/constraints\.md|\.xp/system\.md|plan(-review)?\.md")
CAT = re.compile(r"(^|[;&|]\s*)cat\s")
ROLE = re.compile(r"===== Your charter: ([\w-]+) =====")


def calls(path: Path):
    """(role, [(cmd, output tokens, model-call index)], model calls) for one xp agent run."""
    role, reads, model_calls, pending = "", [], 0, {}
    for line in path.open():
        evt = json.loads(line)
        kind, body = evt.get("type"), evt.get("payload") or {}
        if kind == "token_usage_record":
            model_calls += 1
        elif kind == "response_item":
            item = body.get("type")
            if item == "message" and not role:
                text = json.dumps(body.get("content"))
                role = (ROLE.search(text) or [None, ""])[1]
            elif item in ("custom_tool_call", "function_call"):
                pending[body.get("call_id")] = str(body.get("input") or body.get("arguments"))
            elif item in ("custom_tool_call_output", "function_call_output"):
                text = json.dumps(body.get("output"))
                tokens = sum(map(int, re.findall(r"original_token_count\D{1,6}(\d+)", text)))
                tokens = tokens or len(text) // 4
                reads.append((pending.pop(body.get("call_id"), ""), tokens, model_calls))
    return role, reads, model_calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=str(date.today() - timedelta(days=14)))
    parser.add_argument("--until", default="9999-12-31")
    args = parser.parse_args()
    root = Path.home() / ".codex" / "sessions"
    runs, cost = defaultdict(int), defaultdict(lambda: defaultdict(float))
    for path in sorted(root.rglob("rollout-*.jsonl")):
        day = path.name[8:18]
        if not args.since <= day <= args.until:
            continue
        role, reads, total = calls(path)
        if not role:
            continue
        runs[role] += 1
        for cmd, tokens, at in reads:
            carried = tokens * max(total - at, 0) / 1e6
            cost[role]["all"] += carried
            if BUNDLED.search(cmd):
                cost[role]["bundled"] += carried
            elif CAT.search(cmd) and tokens > 8000:
                cost[role]["whole"] += carried
    print(f"Codex xp agent runs {args.since}..{args.until}; Mtok-calls carried per run")
    print(f"{'role':16}{'runs':>6}{'bundled':>10}{'whole>8K':>10}{'all':>10}")
    for role in sorted(runs):
        n, c = runs[role], cost[role]
        cells = "".join(f"{c[k] / n:>10.2f}" for k in ("bundled", "whole", "all"))
        print(f"{role:16}{n:>6}{cells}")
    total = sum(runs.values())
    share = sum(c["bundled"] + c["whole"] for c in cost.values())
    every = sum(c["all"] for c in cost.values()) or 1
    print(f"waste={share / every:.1%} of carried reads over {total} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
