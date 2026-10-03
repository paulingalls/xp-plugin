"""Preserve unrecorded review artifacts across review retries."""

import glob
import re
from pathlib import Path

from work import data_root

ROUND = re.compile(r"\.round-(\d+)(?=\.)")


def shifted(path: Path, delta: int) -> Path:
    match = ROUND.search(path.name)
    if not match:
        raise ValueError(f"review artifact has no round segment: {path}")
    round_n = int(match.group(1)) + delta
    name = path.name[: match.start(1)] + str(round_n) + path.name[match.end(1) :]
    return path.with_name(name)


def _rotate(path: Path, moves: list[tuple[Path, Path]]) -> None:
    if not path.exists():
        return
    destination = shifted(path, 1)
    _rotate(destination, moves)
    path.rename(destination)
    moves.append((path, destination))


def rotate(paths: list[Path]) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    for path in paths:
        _rotate(path, moves)
    return moves


def covered_destination(sidecar: Path) -> Path:
    story, round_name = sidecar.name.split(".round-", 1)
    return data_root() / "reports" / f"{story}.COVERED-round-{round_name}"


def archive_covered(sidecar: Path) -> Path:
    destination = covered_destination(sidecar)
    if destination.exists():
        raise FileExistsError(f"covered review archive already exists: {destination}")
    sidecar.rename(destination)
    return destination


def notice(moves: list[tuple[Path, Path]], salvage: str) -> str:
    if not moves:
        return ""
    shown = ", ".join(f"{source} -> {destination}" for source, destination in moves)
    return f"set aside {shown} so review can proceed without destroying `{salvage}` input"


def story_sidecars(story_id: str) -> list[Path]:
    root = data_root() / "markers"
    return sorted(root.glob(f"{glob.escape(story_id)}.round-*.launch"))


def _restore(paths: list[Path], current_round: int) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    ordered = sorted(paths, key=lambda path: int(ROUND.search(path.name).group(1)))
    for path in ordered:
        match = ROUND.search(path.name)
        if not match or int(match.group(1)) <= current_round:
            continue
        destination = shifted(path, -1)
        if destination.exists():
            raise FileExistsError(destination)
        path.rename(destination)
        moves.append((path, destination))
    return moves


def sprint_paths(sprint_id: str, round_n: int) -> list[Path]:
    root = data_root() / "reports" / "sprint"
    return sorted(root.glob(f"{glob.escape(sprint_id)}.*.round-{round_n}.*"))


def restore_sprint_queue(sprint_id: str, current_round: int) -> list[tuple[Path, Path]]:
    root = data_root() / "reports" / "sprint"
    # ANY suffix, not just .json: a lone patch left at this round is what a shift
    # down would collide with, and _restore answers a collision by refusing.
    if sprint_paths(sprint_id, current_round):
        return []
    queued = list(root.glob(f"{glob.escape(sprint_id)}.*.round-*.*"))
    return _restore(queued, current_round)
