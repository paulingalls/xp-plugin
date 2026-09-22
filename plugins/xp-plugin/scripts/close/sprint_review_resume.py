"""Resume an incomplete first sprint-review round from validated reports."""

import shlex
import subprocess
from pathlib import Path


def resumable(rounds: list[dict]) -> dict | None:
    if len(rounds) != 1:
        return None
    round_ = rounds[0]
    return round_ if round_.get("incomplete") and round_.get("stages") else None


def reviewed_head(round_: dict, head: str, patch: Path, git, reviewer_name: str) -> tuple[str, str]:
    shown = round_.get("shown_sha", "")
    reviewed = round_.get("reviewed_head", "")
    if not reviewed:
        if round_.get("stages", [])[-1:] != ["fix"]:
            return "", "the incomplete round predates resume provenance"
        parent = git("rev-parse", f"{head}^", check=False).stdout.strip()
        author = git("show", "-s", "--format=%an", head).stdout.strip()
        saved = patch.read_text() if patch.is_file() else ""

        def patch_id(text: str) -> list[str]:
            return subprocess.run(
                ["git", "patch-id", "--stable"], input=text, capture_output=True, text=True
            ).stdout.split()

        saved_id = patch_id(saved)[:1]
        exact = bool(saved_id) and saved_id == patch_id(git("diff", f"{parent}..{head}").stdout)[:1]
        if author != reviewer_name or not parent or not exact:
            return "", (
                "the incomplete round predates resume provenance and its fixer commit"
                " cannot be derived from the saved patch"
            )
        return parent, ""
    if head == shown:
        return reviewed, ""
    if git("merge-base", "--is-ancestor", reviewed, head, check=False).returncode:
        return "", f"HEAD {head[:8]} is not a descendant of reviewed head {reviewed[:8]}"
    if round_.get("stages", [])[-1:] != ["fix"]:
        return "", f"HEAD moved since the incomplete round stopped at {shown[:8]}"
    names = git("diff", "--name-only", "--no-renames", f"{reviewed}..{head}").stdout
    changed = set(names.splitlines())
    covered = patch_paths(patch)
    if outside := sorted(changed - covered):
        commits = git("log", "--oneline", f"{shown}..{head}").stdout.strip()
        return "", (
            f"HEAD moved through commits not covered by the saved fixer patch ({commits});"
            f" unaccounted paths: {', '.join(outside)}. Reset to {reviewed[:8]} to resume"
            " this round"
        )
    return reviewed, ""


def patch_paths(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    touched = set()
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("diff --git "):
            continue
        try:
            names = shlex.split(line)[2:4]
        except ValueError:
            return set()
        touched.update(name[2:] for name in names if name.startswith(("a/", "b/")))
    return touched


def state(rounds: list[dict], head: str, sprint_id: str, review, git):
    complete = max(
        (n for n, round_ in enumerate(rounds, 1) if not round_.get("incomplete")), default=0
    )
    if complete or not (stopped := resumable(rounds)):
        return complete, head, None, "", ""
    saved = review.sprint_report_path(sprint_id, "fix", 1)
    reviewed, why = reviewed_head(
        stopped, head, review.patch_path(saved), git, review.REVIEWER_NAME
    )
    if not why:
        return complete, reviewed, stopped, "", ""
    hard = (
        bool(stopped.get("reviewed_head"))
        and stopped.get("stages", [])[-1:] == ["fix"]
        and head != stopped.get("shown_sha")
    )
    return complete, head, None, "" if hard else why, why if hard else ""


def dirty_fixer(rounds: list[dict], head: str, sprint_id: str, review) -> str:
    round_ = resumable(rounds)
    if not round_ or round_.get("stages", [])[-1:] != ["fix"]:
        return ""
    if round_.get("reviewed_head") != head or round_.get("shown_sha") != head:
        return ""
    report = review.sprint_report_path(sprint_id, "fix", 1)
    patch = review.patch_path(report)
    return (
        "the staged fixer work from incomplete round 1 still needs the lead."
        " Repair the commit gate and finish/commit that staged work, or discard it before"
        f" rerunning the fixer. The saved report is {report}; the patch is {patch}"
    )


def inputs(complete: int, cards: str, stages):
    if complete:
        altitude, error = stages.altitude()
        return [], 0, {}, altitude, error
    found, error = stages.angles()
    if error:
        return [], 0, {}, "", error
    cap, error = stages.batch_cap()
    if error:
        return [], 0, {}, "", error
    charters, error = stages.charters()
    if not error:
        stages.check_roles(cards)
    return found, cap, charters, "", error


class Prefix:
    def __init__(self, round_: dict, read_report, report_path, sprint_id: str, number: int):
        self.expected = round_["stages"]
        self.read_report = read_report
        self.report_path = report_path
        self.sprint_id = sprint_id
        self.number = number
        self.index = 0
        self.open = True
        self.reused = []

    def close(self, why: str) -> str:
        self.open = False
        return why

    def match_verifiers(self, keys: list[str]) -> str:
        if not self.open:
            return ""
        recorded = [key for key in self.expected[self.index :] if key.startswith("verify-")]
        return (
            ""
            if recorded == keys
            else self.close(
                f"recorded verifier stages {recorded} do not match the required stages {keys}"
            )
        )

    def take(self, key: str, role: str) -> tuple[dict | None, str]:
        if not self.open:
            return None, ""
        if self.expected[self.index : self.index + 1] != [key]:
            return None, self.close(f"the recorded stage prefix stops before {key}")
        path = self.report_path(self.sprint_id, key, self.number)
        report, error = self.read_report(path, stage=role)
        if error:
            return None, self.close(error)
        self.index += 1
        self.reused.append(key)
        return report, ""


def record(reports, keys, error, reviewed, shown, report_keys, reused=None, ran=None) -> dict:
    seen = {
        key: dict.fromkeys(item for report in reports for item in report[key])
        for key in report_keys
    }
    result = {key: list(value) for key, value in seen.items()}
    result.update(incomplete=error, stages=keys, reviewed_head=reviewed, shown_sha=shown)
    if reused is not None:
        result.update(reused=reused, ran=ran)
    return result


def take(prefix, role, key, reports, number):
    if not prefix:
        return None, ""
    report, error = prefix.take(key, role)
    if report is not None:
        reports.append(report)
        print(f"round {number}: reused {key}")
    elif error:
        print(f"round {number}: cannot reuse {key}: {error}")
    return report, error


# BY ROUND NUMBER: the marker is re-read under its lock, where salvage may have
# appended a different round while a stage ran. `round_` of None is a resume that
# re-derived NOTHING — overwriting the round there forfeits the findings it already
# holds and leaves it with no stages, which `resumable` never takes again.
def keep_incomplete(marker: Path, number: int, round_: dict | None, error: str, edit) -> list[str]:
    kept: list[str] = []

    def keep(current: dict) -> None:
        if round_ is None:
            current["rounds"][number - 1]["incomplete"] = error
        else:
            current["rounds"][number - 1] = round_
        kept.extend(current["rounds"][number - 1].get("stages", []))

    edit(marker, keep)
    return kept


def stop(
    resume,
    dry_run,
    marker,
    number,
    error,
    reports,
    prefix,
    ran,
    reviewed,
    shown,
    state,
    review,
    edit,
):
    reused = prefix.reused if prefix else None
    recorded = f"Round {number} IS recorded, incomplete."

    def make_record(error):
        return record(
            reports,
            [*(reused or []), *ran],
            error,
            reviewed,
            shown(),
            review.REPORT_KEYS,
            reused,
            ran,
        )

    if resume:
        if dry_run:
            return error, ""
        error = error.replace(review.NO_ROUND, recorded)
        round_ = make_record(error) if reused or ran else None
        kept = keep_incomplete(marker, number, round_, error, edit)
        return error, f"round {number} remains incomplete after {', '.join(kept)}"
    if not reports:
        return error, ""
    error = error.replace(review.NO_ROUND, recorded)
    round_ = make_record(error)
    review.write_round(
        marker,
        state,
        round_,
        edit=edit,
        reviewed_head=round_["reviewed_head"],
        shown_sha=round_["shown_sha"],
    )
    return error, f"round {number} recorded incomplete after {', '.join(round_['stages'])}"


def complete(
    marker: Path,
    number: int,
    round_: dict,
    reviewed: str,
    shown: str,
    prefix: Prefix,
    ran: list[str],
    edit,
) -> None:
    coverage = {"reviewed_head": reviewed, "shown_sha": shown}

    def finish(current: dict) -> None:
        current["rounds"][number - 1] = round_ | coverage | {"reused": prefix.reused, "ran": ran}
        current.update(coverage)

    edit(marker, finish)


def finish(resume, marker, state, number, round_, reviewed, shown, prefix, ran, review, edit):
    if resume:
        complete(marker, number, round_, reviewed, shown, prefix, ran, edit)
    else:
        review.write_round(
            marker, state, round_, edit=edit, reviewed_head=reviewed, shown_sha=shown
        )
