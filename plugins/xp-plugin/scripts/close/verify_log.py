"""Lossless per-invocation Verify evidence; only finalized success is green."""

import codecs
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from close import git
from work import data_root

LOCATOR = "Verify evidence: "
DISPLAY_TAIL = 600
ACTIVE = {"prepared", "running"}
TERMINAL = {"passed", "failed", "launch_error", "interrupted", "evidence_error", "empty"}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(directory, manifest):
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(manifest, output, indent=2)
            output.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(directory / "run.json")
    finally:
        temporary.unlink(missing_ok=True)


def prefix(identity):
    return hashlib.sha256(identity.encode()).hexdigest()[:16] + "-"


def recover(root, identity):
    problems = []
    for directory in sorted(root.glob(prefix(identity) + "*")):
        try:
            record = json.loads((directory / "run.json").read_text())
            if (
                not isinstance(record, dict)
                or record.get("identity") != identity
                or record.get("status") not in ACTIVE | TERMINAL
                or not isinstance(record.get("commands"), list)
            ):
                raise ValueError("invalid manifest")
            for entry in record["commands"]:
                for stream in ("stdout", "stderr"):
                    name = entry[stream]
                    if not isinstance(name, str) or Path(name).name != name:
                        raise ValueError("invalid stream path")
                    with (directory / name).open("rb") as output:
                        output.read(1)
        except FileNotFoundError as exc:
            problems.append(f"missing evidence ({exc.filename}): {directory}")
        except OSError as exc:
            problems.append(f"unreadable evidence ({str(exc)[:300]}): {directory}")
        except (ValueError, KeyError, TypeError, UnicodeError):
            problems.append(f"malformed evidence: {directory}")
        else:
            if record["status"] in ACTIVE:
                print(
                    f"unfinished Verify ({record['status']}); {LOCATOR}{directory}", file=sys.stderr
                )
    return problems


def retain(output, chunk):
    if output.write(chunk) != len(chunk):
        raise OSError("short evidence write")
    output.flush()


def forward(stream, text):
    stream.write(text)
    stream.flush()


def drain(pipe, output, stream, errors):
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        while chunk := pipe.read1(8192):
            retain(output, chunk)
            forward(stream, decoder.decode(chunk))
        forward(stream, decoder.decode(b"", final=True))
        output.flush()
    except BaseException as exc:
        errors.append(exc)
    finally:
        pipe.close()


def stop(child):
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
    elif child.poll() is None:
        child.kill()
    child.wait()


def execute(directory, entry, persist):
    child = None
    threads = []
    errors = []
    begin = time.monotonic()
    try:
        with (
            (directory / entry["stdout"]).open("wb", buffering=0) as stdout,
            (directory / entry["stderr"]).open("wb", buffering=0) as stderr,
        ):
            persist()
            try:
                child = subprocess.Popen(
                    entry["argv"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                entry.update(status="launch_error", error=str(exc))
            else:
                entry.update(status="running", pid=child.pid)
                persist()
                for pipe, output, stream in (
                    (child.stdout, stdout, sys.stdout),
                    (child.stderr, stderr, sys.stderr),
                ):
                    thread = threading.Thread(target=drain, args=(pipe, output, stream, errors))
                    thread.start()
                    threads.append(thread)
                while child.poll() is None:
                    if errors:
                        raise OSError(str(errors[0]))
                    time.sleep(0.01)
                for thread in threads:
                    thread.join()
                if errors:
                    raise OSError(str(errors[0]))
                rc = child.returncode
                if rc < 0:
                    entry.update(status="interrupted", signal=-rc)
                else:
                    entry.update(status="failed" if rc else "passed", exit_result=rc)
    except KeyboardInterrupt:
        entry.update(status="interrupted", error="parent interrupted")
        entry.pop("exit_result", None)
    except (OSError, ValueError, RuntimeError) as exc:
        entry.update(status="evidence_error", error=str(exc))
        entry.pop("exit_result", None)
    finally:
        if child is not None:
            stop(child)
        for thread in threads:
            thread.join()
        entry.update(ended_at=now(), duration_seconds=time.monotonic() - begin)


def tail(path):
    try:
        with path.open("rb") as output:
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - DISPLAY_TAIL))
            return output.read(DISPLAY_TAIL).decode("utf-8", "replace")
    except OSError as exc:
        return f"unreadable stream: {str(exc)[:200]}"


def refusal(directory, manifest, where):
    status = manifest["status"]
    entries = manifest["commands"]
    entry = entries[-1] if entries else {}
    result = f"exit {entry['exit_result']}" if "exit_result" in entry else status
    if "signal" in entry:
        result = f"signal {entry['signal']}"
    label = (
        "red" if status == "failed" else "could not be RUN" if status == "launch_error" else status
    )
    shown = shlex.join(entry.get("argv", []))[:400]
    detail = str(manifest.get("error", entry.get("error", "")))[:400]
    text = (
        f"refused: Verify {label}{where}; command {entry.get('index', '?')} "
        f"({result}): {shown}\n{detail}"
    )
    for stream in ("stdout", "stderr"):
        if stream in entry:
            text += f"\n{stream} tail:\n{tail(directory / entry[stream])}"
    return text + f"\n{LOCATOR}{directory}\n"


def run(identity, phase, commands, where=""):
    directory = None
    manifest = {
        "identity": identity,
        "phase": phase,
        "started_at": now(),
        "status": "prepared",
        "commands": [],
    }
    begin = time.monotonic()
    try:
        root = data_root() / "logs" / "verify"
        root.mkdir(parents=True, exist_ok=True)
        problems = recover(root, identity)
        directory = Path(tempfile.mkdtemp(prefix=prefix(identity), dir=root)).resolve()
        save(directory, manifest)
        if problems:
            raise OSError("; ".join(problems))
        for name, args in (("head", ("rev-parse", "HEAD")), ("tree", ("write-tree",))):
            measured = git(*args, check=False)
            if measured.returncode or not measured.stdout.strip():
                raise OSError(f"could not measure {name}: {measured.stderr.strip()}")
            manifest[name] = measured.stdout.strip()
        for index, argv in enumerate(commands, 1):
            entry = {
                "index": index,
                "argv": argv,
                "status": "prepared",
                "started_at": now(),
                "stdout": f"{index}.stdout",
                "stderr": f"{index}.stderr",
            }
            manifest["commands"].append(entry)
            manifest["status"] = "running"
            execute(directory, entry, lambda: save(directory, manifest))
            save(directory, manifest)
            if entry["status"] != "passed":
                manifest["status"] = entry["status"]
                break
        else:
            manifest["status"] = "passed" if commands else "empty"
        manifest.update(ended_at=now(), duration_seconds=time.monotonic() - begin)
        save(directory, manifest)
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        manifest.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "evidence_error",
            error=str(exc),
            ended_at=now(),
            duration_seconds=time.monotonic() - begin,
        )
        if directory is None:
            return f"refused: Verify evidence logging failed: {str(exc)[:400]}"
        with suppress(OSError):
            save(directory, manifest)
    if manifest["status"] != "passed":
        return refusal(directory, manifest, where)
    print(f"{LOCATOR}{directory}", file=sys.stderr)
    return ""
