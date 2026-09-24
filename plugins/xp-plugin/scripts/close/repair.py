"""Record a completed review after a bounded lead repair passes Verify."""

import json

import close
import overlap
import review
from review_artifacts import story_sidecars
from review_scope import declared_files


def land_red_path(story_id: str):
    return close.marker_path(story_id).with_name(f"{story_id}.land-red.json")


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
        land_red = land_red_path(story_id)
        if land_red.exists():
            return repair_land_red(story_id, card, land_red, noun, rereview)
        recorded = close.marker_path(story_id).exists()
        state = (
            "a recorded round consumed its launch marker; only a review-time"
            " Verify red or land-time Verify/tier red can be repaired"
            if recorded
            else "no round has been recorded yet"
        )
        return close.fail(
            f"refused: no launch marker at {launch}; {state}; nothing to repair — run {rereview}"
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
    if not paths:
        return close.fail(
            f"refused: HEAD's tree equals verify_head {verified[:8]}; a green rerun of"
            f" the reviewed tree is a flake, not a repair — run {rereview}"
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
    print(
        f"recorded round {review.round_number(path)}; land prints the repair"
        f" {verified[:8]}..{head[:8]} as unreviewed — next: `close.py {noun} land`"
    )
    return 0


def repair_land_red(story_id: str, card: str, land_red, noun: str, rereview: str) -> int:
    try:
        at = json.loads(land_red.read_text())
        if not isinstance(at, dict):
            raise ValueError("expected a JSON object")
    except (OSError, UnicodeError, ValueError) as exc:
        return close.fail(
            f"refused: unreadable land-red record {land_red} ({exc}) — run {rereview}"
        )
    if queued := story_sidecars(story_id):
        return close.fail(
            f"refused: queued review sidecar(s) {', '.join(map(str, queued))} — run {rereview}"
        )
    if at.get("card") != card:
        return close.fail(f"refused: card changed since land red — run {rereview}")
    marker = close.marker_path(story_id)
    try:
        state = json.loads(marker.read_text())
        rounds = state["rounds"]
        if not isinstance(rounds, list):
            raise ValueError("rounds must be a list")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return close.fail(f"refused: unreadable close marker {marker} ({exc}) — run {rereview}")
    position = at.get("round_index")
    if (
        not isinstance(position, int)
        or isinstance(position, bool)
        or position != len(rounds)
        or not rounds
        or review.marker_digest(marker) != at.get("digest")
    ):
        return close.fail(f"refused: close ledger changed since land red — run {rereview}")
    round_ = rounds[-1]
    if not isinstance(round_, dict) or round_.get("blocking") or round_.get("incomplete"):
        return close.fail(f"refused: latest review round is unusable or blocking — run {rereview}")
    round_file = round_.get("round_file", position)
    if not isinstance(round_file, int) or isinstance(round_file, bool) or round_file < 1:
        return close.fail(f"refused: latest review round is unusable — run {rereview}")
    report, err = review.read_report(review.report_path(story_id, round_file))
    if err or report.get("blocking"):
        return close.fail(f"refused: review report is unusable or blocking — run {rereview}")
    red_head = at.get("head")
    head = close.git("rev-parse", "HEAD").stdout.strip()
    if (
        not isinstance(red_head, str)
        or not red_head
        or at.get("kind") not in ("Verify", "test tier")
        or not isinstance(at.get("red"), str)
        or not at["red"]
        or close.git("merge-base", "--is-ancestor", red_head, head, check=False).returncode
    ):
        return close.fail(f"refused: HEAD does not contain the recorded red head — run {rereview}")
    base, shown = round_.get("review_base"), round_.get("shown_sha")
    if not isinstance(base, str) or not isinstance(shown, str) or not base or not shown:
        return close.fail(f"refused: latest round lacks reviewed scope — run {rereview}")
    if close.git("merge-base", "--is-ancestor", base, shown, check=False).returncode:
        return close.fail(f"refused: latest round has invalid reviewed scope — run {rereview}")
    paths = sorted(overlap._files(f"{red_head}..{head}"))
    if not paths:
        return close.fail(
            f"refused: HEAD's tree equals the red head; no repair delta — run {rereview}"
        )
    bad = sorted(set(paths) - (overlap._files(f"{base}..{shown}") | declared_files(card)))
    gates = sorted(set(paths) & set(overlap.GATE_FILES))
    if bad or gates:
        listed = ", ".join(sorted(set(bad + gates)))
        return close.fail(
            f"refused: repair changed out-of-bound or gate paths: {listed} — run {rereview}"
        )
    repair = {"range": f"{red_head}..{head}", "paths": paths, "gate": at["kind"], "red": at["red"]}
    if "repair" in round_:
        round_.setdefault("repairs", []).append(repair)
    else:
        round_["repair"] = repair
    try:
        marker.write_text(json.dumps(state))
        land_red.unlink()
    except OSError as exc:
        return close.fail(
            f"refused: could not record repair ({exc}) — run `close.py {noun} repair` again"
        )
    print(f"recorded land-red repair {repair['range']}; next: `close.py {noun} land`")
    return 0
