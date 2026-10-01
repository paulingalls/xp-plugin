import json
import shlex

from work_helpers import run


def write_report(tmp_path, data):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data))
    return path


def report(**fields):
    return {"schema": 2, "fixed": [], "blocking": [], "dropped": [], "debt": []} | fields


def debt(data):
    data.mkdir(parents=True, exist_ok=True)
    guard = data / "debt-guard.json"
    guard.write_text(json.dumps({"records": ["load-bearing"]}))
    code = f"import json; assert json.load(open({str(guard)!r}))['records'] == ['load-bearing']"
    falsifier = "python3 -c " + shlex.quote(code)
    result = run(
        [
            "debt",
            "--claim",
            "silent loss",
            "--falsifier",
            falsifier,
            "--files",
            "src.py",
            "--too-big",
            "needs a separate design ruling",
            "--too-important",
            "silently corrupts the release record",
        ],
        data,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
