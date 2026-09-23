"""Stable log leases, bounded archives, and bounded refusal tails."""

import fcntl
import gzip
import os
import tempfile
from pathlib import Path


def _archive(path: Path) -> None:
    if not path.exists():
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            with path.open("rb") as source, gzip.GzipFile(fileobj=target, mode="wb") as zipped:
                while chunk := source.read(65536):
                    zipped.write(chunk)
        for n in (3, 2):
            older = Path(f"{path}.{n}.gz")
            newer = Path(f"{path}.{n - 1}.gz")
            if newer.exists():
                newer.replace(older)
        temporary.replace(Path(f"{path}.1.gz"))
        path.unlink()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def open_log(path: Path):
    """Return (writer, lease). The caller holds the lease through the whole run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    gate = open(f"{path}.rotate.lock", "a+")  # noqa: SIM115 — held through conversion
    lease = None
    try:
        fcntl.flock(gate, fcntl.LOCK_EX)
        lease = open(f"{path}.lock", "a+")  # noqa: SIM115 — returned to caller
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fcntl.flock(lease, fcntl.LOCK_SH)
            mode = "a"
        else:
            try:
                _archive(path)
            except OSError:
                lease.close()
                raise
            mode = "a"
        writer = open(path, mode)  # noqa: SIM115 — returned to caller
        fcntl.flock(lease, fcntl.LOCK_SH)
        return writer, lease
    except BaseException:
        if lease is not None:
            lease.close()
        raise
    finally:
        gate.close()


def tail(path: Path, characters: int = 2000) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - characters * 4 - 4))
        raw = stream.read(characters * 4 + 4)
    return raw.decode("utf-8", errors="replace")[-characters:]
