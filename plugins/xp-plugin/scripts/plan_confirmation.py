"""Immutable plan artifacts and accepted-round bindings."""

import hashlib
import json
from pathlib import Path

from plan_acceptance import receipt_path
from work import data_root


def preserve(story_id, plan_file):
    """Copy before any writer; identical retries reuse immutable snapshots."""
    parent = data_root() / "plans"
    paths = {Path(plan_file)} | {
        p for p in parent.glob(f"{story_id}.*") if p.is_file() and p.suffix != ".part"
    }
    entries, contents = [], {}
    for path in sorted(paths):
        if not path.exists():
            entries.append({"source": str(path), "state": "missing"})
            continue
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        entries.append({"source": str(path), "identity": digest, "state": "preserved"})
        contents[digest] = body
    key = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    target = parent / f"{story_id}.predecessors" / key
    target.mkdir(parents=True, exist_ok=True)
    for digest, body in contents.items():
        path = target / digest
        if path.exists():
            if path.read_bytes() != body:
                raise ValueError(f"predecessor snapshot changed: restore {path}")
        else:
            with path.open("xb") as handle:
                handle.write(body)
    manifest = target / "manifest.json"
    for entry in entries:
        if entry["state"] == "preserved":
            entry["snapshot"] = str(target / entry["identity"])
    if manifest.exists():
        if json.loads(manifest.read_text()) != entries:
            raise ValueError(f"predecessor manifest changed: restore {manifest}")
    else:
        manifest.write_text(json.dumps(entries))
    from handoff import _write, handoff_state

    state = handoff_state(data_root(), story_id) or {}
    state["predecessors"] = list(dict.fromkeys([*state.get("predecessors", []), str(manifest)]))
    _write(data_root(), story_id, state)
    return manifest


def prior_binding(record, plan_file):
    if Path(record["plan"]).resolve() != Path(plan_file).resolve():
        raise ValueError("accepted draft path binding changed")
    if json.loads(receipt_path(Path(record["findings"])).read_text()) != record:
        raise ValueError("acceptance receipt binding changed")
    if Path(record["candidate"]).read_text() != record["after"]:
        raise ValueError("reviewed card candidate binding changed")
