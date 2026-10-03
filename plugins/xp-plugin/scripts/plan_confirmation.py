"""Content measurement and immutable evidence for plan-review publication."""

import contextlib
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from plan_acceptance import atomic_json, receipt_path
from work import data_root, ready_marker_path


def evidence_path(out):
    return Path(out).with_suffix(".evidence.json")


def content_identity(path):
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        value = os.fsencode(os.readlink(path))
    elif stat.S_ISREG(mode):
        value = path.read_bytes()
    elif stat.S_ISDIR(mode):
        # Git exposes a submodule or embedded repository as one directory entry.
        # Its administrative .git file/directory is not reviewed source evidence.
        value = json.dumps(
            [
                (os.fsencode(p.name).hex(), content_identity(p))
                for p in sorted(path.iterdir())
                if p.name != ".git"
            ]
        ).encode()
    else:
        raise OSError(f"cannot measure file kind at {path}; inspect before replanning")
    return mode, hashlib.sha256(value).hexdigest()


def repository_fingerprint(plan_file, tier_owned=False):
    root = Path.cwd().resolve()
    excluded = Path(plan_file).resolve()
    relative = str(excluded.relative_to(root)) if excluded.is_relative_to(root) else None
    paths = [".", f":(exclude,literal){relative}"] if relative else ["."]

    def git(*args):
        result = subprocess.run(
            ["git", "-c", "diff.autoRefreshIndex=false", *args], capture_output=True
        )
        if result.returncode:
            raise OSError(result.stderr.decode(errors="replace"))
        return result.stdout

    work_paths = [*paths, ":(exclude,literal).xp/config.yml"] if tier_owned else paths
    measured = {
        "head": git("rev-parse", "HEAD").hex(),
        "index": git("ls-files", "--stage", "-z", "--", *paths).hex(),
        "staged": git(
            "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "--", *paths
        ).hex(),
        "worktree": git(
            "diff", "--binary", "--no-ext-diff", "--no-textconv", "--", *work_paths
        ).hex(),
    }
    tracked = git("ls-files", "-z", "--", *paths).split(b"\0")
    untracked = git("ls-files", "--others", "-z", "--", *paths).split(b"\0")
    contents = []
    for name in sorted(set(tracked + untracked) - {b""}):
        path = root / os.fsdecode(name)
        try:
            mode, digest = content_identity(path)
            if tier_owned and name == b".xp/config.yml":
                active, lines = False, []
                for line in path.read_text().splitlines():
                    if line and not line[0].isspace() and not line.startswith("#"):
                        active = line.startswith("tests:")
                    if not (active and line.lstrip().startswith("story:")):
                        lines.append(line)
                digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        except FileNotFoundError:
            contents.append([name.hex(), "absent"])
            continue
        contents.append([name.hex(), mode, digest])
    measured["contents"] = contents
    return {
        "repository": str(root),
        "components": measured,
        "identity": hashlib.sha256(
            json.dumps({"repository": str(root), **measured}, sort_keys=True).encode()
        ).hexdigest(),
    }


def record_evidence(record, fingerprint):
    from ready import credential

    minted = credential(ready_marker_path(record["story_id"]))
    if not minted or minted["digest"] not in (record["digest"], record["prior_digest"]):
        raise ValueError("credential moved before evidence publication")
    atomic_json(
        evidence_path(record["findings"]),
        {
            "version": 1,
            "acceptance": record,
            "repository": fingerprint,
            "amendment_count": record["amendment_count"],
            "credential_digest": record["digest"],
        },
    )


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


def publication_problem(record):
    if "repository_identity" not in record:
        return ""
    try:
        evidence = json.loads(evidence_path(record["findings"]).read_text())
        if evidence["acceptance"] != record:
            raise ValueError("measured acceptance binding changed")
        with contextlib.chdir(evidence["repository"]["repository"]):
            fingerprint = repository_fingerprint(Path(record["plan"]))
        if (
            fingerprint["identity"] != record["repository_identity"]
            or fingerprint != evidence["repository"]
        ):
            raise ValueError("repository moved since measured plan review")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f"cannot publish measured plan review: {error}; restore the measured tree/artifacts"
    return ""
