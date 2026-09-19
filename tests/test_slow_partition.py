"""tests/slow_tests.json decides which tests run at push instead of at commit, and a
stale id fails safe SILENTLY — the test just runs in the fast tier. These pin the two
ways the partition can lie about itself without ever going red on its own.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
PARTITION = json.loads((ROOT / "tests" / "slow_tests.json").read_text())


def _regen():
    path = ROOT / "tests" / "scripts" / "regen_slow_tests.py"
    spec = importlib.util.spec_from_file_location("regen_slow_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_parametrized_node_id_survives_the_census_parse():
    """conftest matches ids EXACTLY, so a truncated key marks nothing — and it also
    sums its siblings into one threshold decision, marking on a cost no test paid."""
    census = (
        "0.60s call     tests/test_a.py::test_one[printf x | true-shell syntax]\n"
        "0.60s call     tests/test_a.py::test_one[true & wait-shell syntax]\n"
        "0.10s setup    tests/test_a.py::test_one[printf x | true-shell syntax]\n"
    )

    assert _regen().totals(census) == {
        "tests/test_a.py::test_one[printf x | true-shell syntax]": 0.7,
        "tests/test_a.py::test_one[true & wait-shell syntax]": 0.6,
    }


def test_every_partition_id_is_a_whole_node_id():
    broken = [i for i in PARTITION["ids"] if i.count("[") != i.count("]")]
    absent = [i for i in PARTITION["ids"] if not (ROOT / i.split("::")[0]).exists()]

    assert (broken, absent) == ([], [])
