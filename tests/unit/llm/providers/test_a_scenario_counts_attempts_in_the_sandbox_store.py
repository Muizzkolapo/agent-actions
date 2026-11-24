"""A sandbox scenario counts each record's attempts at an action in the sandbox store.

A repair round, a retry, a later ``--wait`` pass and ``agac retry`` run in other calls or
other processes, so the count lives in the store's metadata, where one transaction that
holds the write lock adds one, in SQL that every SQLite reads.
Each action and record counts on its own. With no store the count is the scenario's own;
with no scenario the mock counts per run, in memory, and writes nothing.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from agent_actions.config import sandbox
from agent_actions.llm.providers.agac import scenario as sc
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.constants import RECORD_GUID_KEY

ACTIONS = {"extract": None, "classify": None}
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _store(path: Path) -> SQLiteBackend:
    store = SQLiteBackend.create(db_path=str(path), workflow_name="wf")
    store.initialize()
    return store


def _attached(tmp_path: Path) -> sc.Scenario:
    scenario = sc.load("happy", tmp_path, ACTIONS)
    scenario.attach(_store(tmp_path / "wf.sandbox.db"))
    return scenario


def test_a_later_process_continues_the_count_of_each_action_and_record(tmp_path):
    first = _attached(tmp_path)
    counted = [first.next_attempt("extract", "r1"), first.next_attempt("extract", "r1")]
    # What a later process sees: a new scenario over a new connection to the same store.
    later = _attached(tmp_path)

    assert counted == [1, 2]
    assert later.next_attempt("extract", "r1") == 3
    assert later.next_attempt("extract", "r2") == 1
    assert later.next_attempt("classify", "r1") == 1


def _count_in_another_process(path: str, times: int, ready, start, out) -> None:
    store = SQLiteBackend.create(db_path=path, workflow_name="wf")
    store.initialize()
    ready.release()
    start.wait(timeout=120)
    try:
        out.put([store.increment_metadata("sandbox_attempts:extract:r1") for _ in range(times)])
    except Exception as error:
        out.put([repr(error)])


def test_two_processes_counting_one_record_never_read_the_same_count(tmp_path):
    path = str(tmp_path / "wf.sandbox.db")
    _store(Path(path))
    context = multiprocessing.get_context("spawn")
    out, ready, start = context.Queue(), context.Semaphore(0), context.Event()
    workers = [
        context.Process(target=_count_in_another_process, args=(path, 300, ready, start, out))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    # Both count at the same time: neither starts before the other has opened the store.
    for _ in workers:
        assert ready.acquire(timeout=120)
    start.set()
    seen = out.get(timeout=120) + out.get(timeout=120)
    for worker in workers:
        worker.join(timeout=120)

    assert all(isinstance(count, int) for count in seen), [c for c in seen if isinstance(c, str)]
    assert sorted(seen) == list(range(1, 601))


def test_the_count_is_added_in_sql_that_an_old_sqlite_reads(tmp_path):
    store = _store(tmp_path / "wf.sandbox.db")
    statements: list[str] = []
    store.connection.set_trace_callback(statements.append)

    counted = [store.increment_metadata("sandbox_attempts:extract:r1") for _ in range(3)]

    assert counted == [1, 2, 3]
    assert store.load_metadata("sandbox_attempts:extract:r1") == "3"
    # RETURNING needs SQLite 3.35 and an upsert 3.24; RHEL 9 and Debian 11 ship 3.34.
    sql = " ".join(statements).upper()
    assert "RETURNING" not in sql and "ON CONFLICT" not in sql, statements
    # The write lock is taken before the count is read.
    assert statements[0] == "BEGIN IMMEDIATE", statements
    assert not store.connection.in_transaction


def test_a_count_that_fails_leaves_no_transaction_open(tmp_path):
    store = _store(tmp_path / "wf.sandbox.db")
    store._save_metadata_raw("sandbox_attempts:extract:r1", "not a number")
    store.connection.execute(
        "CREATE TRIGGER refuse BEFORE UPDATE ON workflow_metadata "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )

    with pytest.raises(Exception, match="refused"):
        store.increment_metadata("sandbox_attempts:extract:r1")

    assert not store.connection.in_transaction
    assert store.load_metadata("sandbox_attempts:extract:r1") == "not a number"


def test_with_no_store_the_scenario_counts_in_memory(tmp_path):
    scenario = sc.load("happy", tmp_path, ACTIONS)

    assert [scenario.next_attempt("extract", "r1") for _ in range(3)] == [1, 2, 3]
    assert sc.load("happy", tmp_path, ACTIONS).next_attempt("extract", "r1") == 1


def test_forgetting_one_action_keeps_the_others_and_forgetting_all_keeps_none(tmp_path):
    store = _store(tmp_path / "wf.sandbox.db")
    for key in ("extract:r1", "extract_2:r1", "classify:r1"):
        store.increment_metadata(f"{sc.ATTEMPTS_KEY_PREFIX}{key}")

    with sandbox.sandbox_mode(True):
        sandbox.forget_attempts(store, "extract")
        left = store.list_metadata_prefix(sc.ATTEMPTS_KEY_PREFIX)
        sandbox.forget_attempts(store)

    assert left == [
        f"{sc.ATTEMPTS_KEY_PREFIX}classify:r1",
        f"{sc.ATTEMPTS_KEY_PREFIX}extract_2:r1",
    ]
    assert store.list_metadata_prefix(sc.ATTEMPTS_KEY_PREFIX) == []


def test_forgetting_some_records_of_an_action_keeps_its_other_records(tmp_path):
    store = _store(tmp_path / "wf.sandbox.db")
    for key in ("extract:r1", "extract:r2", "extract:r3", "classify:r1"):
        store.increment_metadata(f"{sc.ATTEMPTS_KEY_PREFIX}{key}")

    with sandbox.sandbox_mode(True):
        sandbox.forget_attempts(store, "extract", records={"r1", "r3", "never-counted"})

    assert store.list_metadata_prefix(sc.ATTEMPTS_KEY_PREFIX) == [
        f"{sc.ATTEMPTS_KEY_PREFIX}classify:r1",
        f"{sc.ATTEMPTS_KEY_PREFIX}extract:r2",
    ]


def test_a_real_run_forgets_nothing(tmp_path):
    store = _store(tmp_path / "wf.db")
    store.increment_metadata(f"{sc.ATTEMPTS_KEY_PREFIX}extract:r1")

    sandbox.forget_attempts(store)

    assert store.list_metadata_prefix(sc.ATTEMPTS_KEY_PREFIX) != []


@pytest.fixture
def project(tmp_path):
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=tmp_path))
    yield tmp_path
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    path_utils._global_path_manager = previous


def _rows(record_ids: list[str]) -> list[dict]:
    return [
        {
            "target_id": rid,
            "content": {"source": {"text": rid}},
            "prompt": "Sum up.",
            RECORD_GUID_KEY: f"g-{rid}",
        }
        for rid in record_ids
    ]


def _submit(project: Path, action: str, record_ids: list[str]) -> str:
    client = AgacBatchClient()
    config = {"name": action, "model_name": "agac-model", "json_mode": True}
    tasks = client.prepare_tasks(_rows(record_ids), {**config, "compiled_schema": SCHEMA})
    path = project / "input.jsonl"
    path.write_text("\n".join(json.dumps(task) for task in tasks))
    batch_id, _ = client._submit_to_provider_api(path, "input")
    return batch_id


def _attempts(batch_id: str) -> dict[str, int | None]:
    return {t["custom_id"]: t.get("attempt") for t in AgacBatchClient._tasks_by_batch[batch_id]}


def test_each_batch_submission_is_the_record_s_next_attempt_in_the_store(project):
    with sandbox.sandbox_mode(True), sandbox.scenario_choice("happy"):
        sandbox.load_scenario(project, ACTIONS)
        sandbox.attach_store(_store(project / "wf.sandbox.db"))
        first = _attempts(_submit(project, "extract", ["r1", "r2"]))
        # A later pass: a new load of the scenario over the same store.
        sandbox.load_scenario(project, ACTIONS)
        sandbox.attach_store(_store(project / "wf.sandbox.db"))
        again = _attempts(_submit(project, "extract", ["r2"]))
        other_action = _attempts(_submit(project, "classify", ["r2"]))

    assert first == {"r1": 1, "r2": 1}
    assert again == {"r2": 2}
    assert other_action == {"r2": 1}


def test_with_no_scenario_a_batch_counts_in_memory_and_writes_no_count(project):
    batch_id = _submit(project, "extract", ["r1"])

    assert _attempts(batch_id) == {"r1": None}
    assert not (project / ".agac" / "batch_attempts.json").exists()
    assert "record" not in AgacBatchClient._tasks_by_batch[batch_id][0]


def test_a_task_names_its_record_and_holds_its_input_and_no_request_carries_either(project):
    with sandbox.sandbox_mode(True), sandbox.scenario_choice("happy"):
        sandbox.load_scenario(project, ACTIONS)
        batch_id = _submit(project, "extract", ["r1"])

    [task] = AgacBatchClient._tasks_by_batch[batch_id]
    assert task["record"] == "g-r1"
    assert task["input"] == {"source": {"text": "r1"}}
    assert RECORD_GUID_KEY not in json.dumps(task)
