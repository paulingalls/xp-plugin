"""The canonical log survives both rotation and overlapping writers."""

import gzip
import io
import os
import subprocess
import sys
import time
from pathlib import Path

from log_rotate import open_log, tail


def test_four_rotations_keep_three_archives(tmp_path):
    path = tmp_path / "logs" / "agent.log"
    for number in range(5):
        writer, lease = open_log(path)
        writer.write(f"run {number}\n")
        writer.close()
        lease.close()
    assert path.read_text() == "run 4\n"
    for number in range(1, 4):
        with gzip.open(f"{path}.{number}.gz", "rt") as stream:
            assert stream.read() == f"run {4 - number}\n"
    assert not Path(f"{path}.4.gz").exists()


def test_live_writer_keeps_canonical_inode(tmp_path):
    path = tmp_path / "agent.log"
    writer, lease = open_log(path)
    writer.write("first\n")
    writer.flush()
    script = (
        "import sys; from pathlib import Path; from log_rotate import open_log; "
        "w,l=open_log(Path(sys.argv[1])); w.write('second\\n'); w.close(); l.close()"
    )
    env = os.environ | {
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "plugins/xp-plugin/scripts")
    }
    child = subprocess.run(
        [sys.executable, "-c", script, str(path)], env=env, capture_output=True, text=True
    )
    assert child.returncode == 0, child.stderr
    writer.close()
    lease.close()
    assert path.read_text() == "first\nsecond\n"
    assert not Path(f"{path}.1.gz").exists()


def test_two_child_runs_share_one_live_log_and_paths_stay_valid(tmp_path):
    path = tmp_path / "shared.log"
    release = tmp_path / "release"
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from log_rotate import open_log\n"
        "p,ready,release,name=map(Path,sys.argv[1:])\n"
        "w,l=open_log(p)\n"
        "w.write(f'{name} start\\n'); w.flush()\n"
        "print(f'live log: {p}',flush=True)\n"
        "ready.touch()\n"
        "while not release.exists(): time.sleep(.01)\n"
        "w.write(f'{name} end\\n'); w.close(); l.close()\n"
    )
    env = os.environ | {
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "plugins/xp-plugin/scripts")
    }
    children = []
    try:
        for name in ("one", "two"):
            ready = tmp_path / f"{name}.ready"
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(path), str(ready), str(release), name],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append((child, ready))
        deadline = time.monotonic() + 5
        while not all(ready.exists() for _, ready in children) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert all(ready.exists() for _, ready in children)
        assert path.is_file()
    finally:
        release.touch()
        for child, _ in children:
            stdout, stderr = child.communicate(timeout=5)
            assert child.returncode == 0, stderr
            assert f"live log: {path}" in stdout and path.is_file()
    assert all(f"{name} start\n" in path.read_text() for name in ("one", "two"))
    assert all(f"{name} end\n" in path.read_text() for name in ("one", "two"))
    assert not Path(f"{path}.1.gz").exists()


def test_tail_bounds_bytes_and_keeps_last_characters(tmp_path, monkeypatch):
    read = []

    class Counted(io.FileIO):
        def read(self, size=-1):
            data = super().read(size)
            read.append(len(data))
            return data

    path = tmp_path / "large.log"
    path.write_text("x" * 2_000_001 + "é" + "z" * 2000)
    split = tmp_path / "split.log"
    # 3-byte characters, then one ASCII byte: the seek lands mid-character.
    split.write_text("€" * 5000 + "a")
    monkeypatch.setattr(type(path), "open", lambda self, mode="r", **_: Counted(self, mode))
    assert tail(path) == "z" * 2000
    assert tail(path, 2001) == "é" + "z" * 2000
    assert max(read) < 10_000
    assert tail(split) == "€" * 1999 + "a"


def test_detached_review_continues_when_log_cannot_open(tmp_path, monkeypatch, capsys):
    import review_runner

    monkeypatch.setattr(review_runner, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        review_runner, "review_marker", lambda identifier, kind: tmp_path / "marker.json"
    )

    def fail_open(_path):
        raise OSError("full")

    monkeypatch.setattr(review_runner, "open_log", fail_open)
    script = tmp_path / "child.py"
    script.write_text("print('child ran')\n")
    _pid, child = review_runner._detach("story-148", "plan", tmp_path / "out", [str(script)])
    assert child.wait(timeout=5) == 0
    assert "log open failed (full)" in capsys.readouterr().err
