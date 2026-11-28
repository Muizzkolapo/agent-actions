"""Split the suite into shards of whole test files, balanced by how long each file takes.

``pytest --shard 2/4`` runs the second of four shards. Files are dealt out longest first,
each to the shard with the least time so far, from the seconds `SHARD_DURATIONS` holds
per file; a file it does not list counts as the median. A file stays whole, so a
module-scoped fixture is built once. Every file lands in exactly one shard.

``pytest --store-shard-durations`` rewrites `SHARD_DURATIONS` from the run: the time of
each test's setup, call and teardown, summed per file.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

SHARD_DURATIONS = Path(__file__).resolve().parents[1] / "shard_durations.json"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("sharding")
    group.addoption(
        "--shard",
        default=None,
        metavar="N/M",
        help="Run shard N of M: whole test files, balanced by tests/shard_durations.json",
    )
    group.addoption(
        "--store-shard-durations",
        action="store_true",
        default=False,
        help="Write the seconds each test file took to tests/shard_durations.json",
    )


def shard_of(spec: str) -> tuple[int, int]:
    """``N/M`` as (N, M), refusing anything that names no shard of M."""
    try:
        index, count = (int(part) for part in spec.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard takes N/M, such as 2/4, not {spec!r}") from None
    if count < 1 or not 1 <= index <= count:
        raise pytest.UsageError(f"--shard {spec}: N must be from 1 to M")
    return index, count


def assign(files: list[str], durations: dict[str, float], count: int) -> list[list[str]]:
    """*files* dealt into *count* shards, longest first, each to the least loaded shard."""
    known = [durations[f] for f in files if f in durations]
    default = statistics.median(known) if known else 1.0
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [0.0] * count
    for name in sorted(files, key=lambda f: (-durations.get(f, default), f)):
        least = min(range(count), key=lambda i: (loads[i], i))
        shards[least].append(name)
        loads[least] += durations.get(name, default)
    return shards


def _file_of(item: pytest.Item) -> str:
    return item.nodeid.split("::", 1)[0]


def _durations() -> dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(SHARD_DURATIONS.read_text()).items()}
    except (OSError, ValueError):
        return {}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    spec = config.getoption("--shard")
    if not spec:
        return
    index, count = shard_of(spec)
    files = sorted({_file_of(item) for item in items})
    kept = set(assign(files, _durations(), count)[index - 1])
    chosen = [item for item in items if _file_of(item) in kept]
    config.hook.pytest_deselected(items=[item for item in items if _file_of(item) not in kept])
    items[:] = chosen


_seconds: dict[str, float] = defaultdict(float)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _seconds[report.nodeid.split("::", 1)[0]] += report.duration


def pytest_sessionfinish(session: pytest.Session) -> None:
    config = session.config
    # Under xdist the controller sees every report; a worker writes nothing.
    if not config.getoption("--store-shard-durations") or hasattr(config, "workerinput"):
        return
    rounded = {name: round(seconds, 2) for name, seconds in sorted(_seconds.items())}
    SHARD_DURATIONS.write_text(json.dumps(rounded, indent=0) + "\n")
