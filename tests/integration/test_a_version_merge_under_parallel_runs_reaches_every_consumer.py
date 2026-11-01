"""Every consumer of a version merge holds every record, run after run in parallel (1605).

The report: with ``versions`` and ``version_consumption: merge``, consumers were now and
then stranded, holding fewer rows or merges short of a version. Five versions over three
staged files run in parallel several times, and each run must leave every merge holding
all five votes, every fan-in both branches, and the same row counts as the run before.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
VERSIONS = 5
RUNS = 3
ITEMS = [
    {"item_id": f"{name}{n}", "text": " ".join(f"w{i}" for i in range(n % 4 + 1))}
    for name in ("a", "b", "c")
    for n in range(4)
]


def _project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    workflow = root / "agent_workflow" / WORKFLOW
    config = workflow / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    assert text.count("range: [1, 2]") == 2, "the example no longer versions two actions"
    config.write_text(text.replace("range: [1, 2]", f"range: [1, {VERSIONS}]"))
    staging = workflow / "agent_io" / "staging"
    for path in staging.iterdir():
        path.unlink()
    for index in range(3):
        (staging / f"items_{index}.json").write_text(json.dumps(ITEMS[index::3]))
    return root


def _rows(root, action):
    backend = get_storage_backend(
        workflow_path=str(root / "agent_workflow" / WORKFLOW), workflow_name=WORKFLOW
    )
    backend.initialize()
    try:
        return [
            row["content"][action]
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _check(root):
    """Row counts per consumer, after asserting each holds what every version answered."""
    for merge in ("merge_votes", "merge_direct"):
        rows = _rows(root, merge)
        assert rows, merge
        assert {row["n_votes"] for row in rows} == {VERSIONS}, merge
    for fanin in ("fanin_consumer", "fanin_asymmetric"):
        rows = _rows(root, fanin)
        assert rows and all(row["both_branches"] for row in rows), fanin
    assert all(row["all_merged"] for row in _rows(root, "reduce_summary"))
    consumers = ("merge_votes", "merge_direct", "fanin_consumer", "fanin_asymmetric")
    return {action: len(_rows(root, action)) for action in consumers}


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_every_parallel_run_leaves_every_consumer_whole(tmp_path):
    root = _project(tmp_path)
    counts = []
    for _ in range(RUNS):
        result = run_agac(
            root,
            "run",
            "-a",
            WORKFLOW,
            "--fresh",
            "--execution-mode",
            "parallel",
            env={"OPENAI_API_KEY": "sk-not-used", "GEMINI_API_KEY": "not-used"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        counts.append(_check(root))

    assert counts == [counts[0]] * RUNS
