"""Record a completed review after a bounded lead repair passes Verify."""

import json

import close
import overlap
import review
from review_artifacts import story_sidecars
from review_scope import declared_files


def cmd_repair(story_id: str) -> int:
    noun = close.leg(story_id)[0]
    retry = f"`close.py {noun} repair`"
    rereview = f"`close.py {noun} review`"
    if close.git("status", "--porcelain").stdout.strip():
        return close.fail(f"refused: working tree is dirty — fix it, then run {retry} again")
    card, _trunk, err = close._preflight(story_id, "repair")
    if err:
        return close.fail(err)
    launch = review.launch_marker(story_id)
    if not launch.exists():
        return close.fail(
            f"refused: no launch marker at {launch}; nothing to repair — run {rereview}"
        )
    try:
        at = json.loads(launch.read_text())
        if not isinstance(at, dict):
            raise ValueError("expected a JSON object")
    except (OSError, UnicodeError, ValueError) as exc:
        return close.fail(
            f"refused: unreadable launch marker {launch} ({exc}) — fix the file,"
            f" then run {rereview}"
        )
    if not at.get("verify_red"):
        return close.fail(
            f"refused: {launch} has no verify_red; no completed red Verify to repair"
            f" — run {rereview}"
        )
    if (
        not isinstance(at.get("head"), str)
        or not isinstance(at.get("base"), str)
        or not isinstance(at.get("round_index"), int)
        or at["round_index"] < 0
        or not isinstance(at.get("digest"), str)
    ):
        return close.fail(f"refused: launch marker {launch} lacks round identity — run {rereview}")
    if queued := story_sidecars(story_id):
        return close.fail(
            f"refused: queued review sidecar(s) {', '.join(map(str, queued))} —"
            f" run `close.py {noun} salvage` before repair"
        )
    if at.get("card") != card:
        return close.fail(f"refused: card changed since review launch — run {rereview}")
    marker = close.marker_path(story_id)
    try:
        state = json.loads(marker.read_text()) if marker.exists() else {}
        if not isinstance(state, dict) or not isinstance(state.get("rounds", []), list):
            raise ValueError("expected a JSON object with rounds list")
    except (OSError, UnicodeError, ValueError) as exc:
        return close.fail(
            f"refused: unreadable close marker {marker} ({exc}) — fix it, then run {rereview}"
        )
    if len(state.get("rounds", [])) != at.get("round_index") or review.marker_digest(
        marker
    ) != at.get("checkpoint_digest", at.get("digest")):
        return close.fail(f"refused: close ledger changed since review launch — run {rereview}")
    verified = at.get("verify_head", "")
    head = close.git("rev-parse", "HEAD").stdout.strip()
    if (
        not isinstance(verified, str)
        or not verified
        or close.git("merge-base", "--is-ancestor", verified, head, check=False).returncode
    ):
        return close.fail(
            f"refused: HEAD does not contain verify_head {verified!s} — run {rereview}"
        )
    if close.git("merge-base", "--is-ancestor", at["base"], verified, check=False).returncode:
        return close.fail(
            f"refused: launch review base does not precede verify_head — run {rereview}"
        )
    paths = sorted(overlap._files(f"{verified}..{head}"))
    seen = overlap._files(f"{at['base']}..{verified}")
    bad = sorted(set(paths) - (seen | declared_files(card)))
    gates = sorted(set(paths) & set(overlap.GATE_FILES))
    if bad or gates:
        listed = ", ".join(sorted(set(bad + gates)))
        return close.fail(
            f"refused: repair changed out-of-bound or gate paths: {listed} — run {rereview}"
        )
    verify = close.verify_commands(story_id, card)[1]
    if red := overlap.run_checks(verify, None):
        return close.fail(f"{red} — fix it, then run {retry} again")
    if head == verified:
        return close.fail(
            f"refused: HEAD equals verify_head {verified[:8]}; green rerun is a flake,"
            f" not a repair — run {rereview}"
        )
    position = at.get("round_index")
    path = review.report_path(story_id, position + 1)
    report, err = review.read_report(path)
    if err or report.get("blocking"):
        return close.fail(
            f"refused: review report {path} is unusable or blocking:"
            f" {err or report['blocking']} — run {rereview}"
        )
    reviewed = at.get("head", "")
    if (
        not reviewed
        or close.git("merge-base", "--is-ancestor", reviewed, verified, check=False).returncode
    ):
        return close.fail(f"refused: reviewed head does not precede verify_head — run {rereview}")
    summary = review.reviewer_range(reviewed, verified)
    if summary:
        diff = review.diff_path(path)
        try:
            diff.write_text(summary + "\n" + close.git("diff", f"{reviewed}..{verified}").stdout)
        except OSError as exc:
            return close.fail(
                f"refused: could not write reviewer handoff {diff} ({exc}) — fix it,"
                f" then run {retry} again"
            )
    repair = {"range": f"{verified}..{head}", "paths": paths, "verify": verify, "result": "green"}
    review.write_round(
        marker,
        state,
        report | {"repair": repair},
        round_file=review.round_number(path),
        reviewed_head=reviewed,
        shown_sha=verified,
        review_base=at["base"],
        branch=close.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
    )
    raw = json.loads(path.read_text())
    raw.pop("refused", None)
    raw["repaired"] = repair["range"]
    path.write_text(json.dumps(raw, indent=2))
    launch.unlink()
    return 0
