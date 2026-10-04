"""Readable predecessor copies and accepted-round bindings."""

import json
from pathlib import Path

from plan_acceptance import receipt_path
from work import data_root


def preserve(story_id, plan_file):
    import shutil

    parent = data_root() / "plans"
    paths = {Path(plan_file)} | {
        p for p in parent.glob(f"{story_id}.*") if p.is_file() and p.suffix != ".part"
    }
    names = {}
    for path in sorted(paths):
        name = path.name
        if name in names:
            name = "draft-" + name
        if name in names:
            raise ValueError(
                "predecessor filenames collide; give the external draft a distinct name"
            )
        names[name] = path
    archive = parent / f"{story_id}.predecessors"
    archive.mkdir(parents=True, exist_ok=True)
    number = 1
    while (archive / f"attempt-{number}").exists() or (
        archive / f"attempt-{number}.copying"
    ).exists():
        number += 1
    target = archive / f"attempt-{number}.copying"
    target.mkdir()
    for name, path in names.items():
        try:
            with path.open("rb") as source, (target / name).open("xb") as destination:
                shutil.copyfileobj(source, destination)
        except FileNotFoundError:
            if path.exists():
                raise
    completed = archive / f"attempt-{number}"
    target.rename(completed)
    from handoff import _write, handoff_state

    state = handoff_state(data_root(), story_id)
    if state is None:
        raise ValueError("unreadable handoff; restore its preserved bytes")
    state = state or {}
    state["predecessors"] = [*state.get("predecessors", []), str(completed)]
    _write(data_root(), story_id, state)
    return completed


def prior_binding(record, plan_file):
    if Path(record["plan"]).resolve() != Path(plan_file).resolve():
        raise ValueError("accepted draft path binding changed")
    if json.loads(receipt_path(Path(record["findings"])).read_text()) != record:
        raise ValueError("acceptance receipt binding changed")
    if Path(record["candidate"]).read_text() != record["after"]:
        raise ValueError("reviewed card candidate binding changed")
