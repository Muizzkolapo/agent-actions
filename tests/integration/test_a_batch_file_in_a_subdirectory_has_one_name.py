"""A batch input file in a subdirectory is sent, keyed and stored under one name.

The name is the file's path under the action's input root, stored with a `.json` suffix.

Later-stage tests drive the real pipeline, store, registry and collect pass, and only the
provider is fake. First-stage tests drive ``process_initial_stage`` and finalize through
the harness's ``_collect``, past the collect pass. The retry test runs an action with no
dependencies through the later-stage pipeline: a retry of one with dependencies is never
sent at all.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.batch.infrastructure.context import batch_output_name
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    SKIP,
    _Batch,
    _FirstStageBatch,
    _Online,
    rec,
)

A_PAGE = [rec("a1", keep=True), rec("a2", keep=True)]
ANSWERED_IN_BATCH_1 = ["processed:a1@batch-1", "processed:a2@batch-1"]


def _registry(action: _Action) -> list[str]:
    return sorted(BatchRegistryManager(action.backend, ACTION).get_all_jobs())


def _each_record_held_once(action: _Action) -> bool:
    return set(action.backend.target_rows_per_source_guid(ACTION).values()) == {1}


def test_a_file_in_a_subdirectory_is_stored_under_the_name_online_gives_it(tmp_path):
    """Answered, then a run that sends nothing writes the same file, not a second one."""
    action = _Action(tmp_path)
    action.run({"sub/page.json": A_PAGE})

    action.run({"sub/page.json": [*A_PAGE, rec("f1", keep=False)]})

    online = _Online(tmp_path, "sub/page.json")
    online.run(1, A_PAGE)
    assert action.files() == {"sub/page.json": ["guard_skipped:f1", *ANSWERED_IN_BATCH_1]}
    assert online.backend.list_target_files(ACTION) == ["sub/page.json"]
    assert _each_record_held_once(action)


def test_two_files_of_one_name_in_two_directories_are_two_batches(tmp_path):
    """Keyed by basename, the second found the first's batch out and was never sent."""
    action = _Action(tmp_path)
    twins = {"sub1/page.json": [rec("a1", keep=True)], "sub2/page.json": [rec("b1", keep=True)]}
    action.run(twins)
    held = {"sub1/page.json": ["processed:a1@batch-1"], "sub2/page.json": ["processed:b1@batch-2"]}

    assert len(action.provider.batches) == 2
    assert _registry(action) == ["sub1/page.json", "sub2/page.json"]
    assert action.files() == held

    action.run(twins)

    assert len(action.provider.batches) == 2
    assert action.files() == held


def test_a_top_level_file_and_one_of_its_name_in_a_subdirectory_keep_their_own_rows(tmp_path):
    action = _Action(tmp_path)
    first = {"page.json": [rec("t1", keep=True)], "sub/page.json": [rec("s1", keep=True)]}
    grown = {
        "page.json": [rec("t1", keep=True), rec("t2", keep=True)],
        "sub/page.json": [rec("s1", keep=True), rec("s2", keep=True)],
    }

    action.run(first)
    action.run(grown)
    action.run(grown)

    assert len(action.provider.batches) == 4
    assert action.files() == {
        "page.json": ["processed:t1@batch-1", "processed:t2@batch-3"],
        "sub/page.json": ["processed:s1@batch-2", "processed:s2@batch-4"],
    }


def test_a_retry_for_a_file_in_a_subdirectory_is_its_own_and_writes_its_file(tmp_path):
    """Two files of one name lose a record each: two retries, and each finds its file."""
    # Reading no other action: a retry's preparation is given no action indices, so one
    # with dependencies cannot send a retry at all.
    no_upstream = {"dependencies": [], "context_scope": {"observe": ["source.*"]}, "guard": None}
    action = _Action(tmp_path, {**no_upstream, "retry": {"enabled": True, "max_attempts": 3}})
    action.provider.withheld = {"a2", "b2"}
    twins = {
        "sub1/page.json": [rec("a1", keep=True), rec("a2", keep=True)],
        "sub2/page.json": [rec("b1", keep=True), rec("b2", keep=True)],
    }
    action.run(twins)

    assert _registry(action) == [
        "sub1/page.json",
        "sub1/page.json_retry_1",
        "sub2/page.json",
        "sub2/page.json_retry_1",
    ]
    assert action.backend.list_metadata_prefix(f"recovery_state:{ACTION}:") == [
        f"recovery_state:{ACTION}:sub1/page.json",
        f"recovery_state:{ACTION}:sub2/page.json",
    ]

    action.collect()

    assert action.files() == {
        "sub1/page.json": ["processed:a1@batch-1", "processed:a2@batch-3"],
        "sub2/page.json": ["processed:b1@batch-2", "processed:b2@batch-4"],
    }


STAGED = [{"item": "a1", "keep": True}, {"item": "a2", "keep": True}]


@pytest.mark.parametrize("file", ["sub/page.json", "sub/page.csv"])
def test_a_first_stage_file_in_a_subdirectory_is_keyed_by_its_path(tmp_path, file):
    batch = _FirstStageBatch(tmp_path, file)

    held = batch.run(1, STAGED, {})

    assert held == ["processed:a1:0@run1", "processed:a2:0@run1"]
    assert sorted(BatchRegistryManager(batch.backend, ACTION).get_all_jobs()) == [file]
    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]


SKIPS_F1 = {"guard": {"clause": "source.item != 'f1'", "behavior": "skip"}}


@pytest.mark.parametrize("file", ["sub/page.json", "sub/page.csv"])
def test_a_first_stage_file_in_a_subdirectory_keeps_one_name_when_nothing_is_sent(tmp_path, file):
    """The write lands on the file's stored name, `.json` whatever the staged suffix."""
    batch = _FirstStageBatch(tmp_path, file)
    first = batch.run(1, STAGED, SKIPS_F1)

    again = batch.run(2, [*STAGED, {"item": "f1", "keep": False}], SKIPS_F1)

    assert batch.sent == [["a1", "a2"], []]
    assert [row for row in again if row.startswith("processed:")] == first
    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]


@pytest.mark.parametrize("file", ["page.txt", "sub/page.txt"])
def test_a_run_that_sends_nothing_writes_the_file_holding_the_answers(tmp_path, file):
    """An input not named `.json` is answered into its `.json` name, and so is that write."""
    batch = _Batch(tmp_path, file)
    batch.run(1, A_PAGE, extra=SKIP)

    batch.run(2, [*A_PAGE, rec("f1", keep=False)], extra=SKIP)

    assert batch.sent == [["a1", "a2"], []]
    assert batch.backend.list_target_files(ACTION) == [batch_output_name(file)]


def test_a_nested_file_keeps_its_name_when_a_top_level_file_of_that_name_leaves(tmp_path):
    """The top-level file leaves, but the rows it was answered with stay in the store."""
    action = _Action(tmp_path)
    action.run({"page.json": [rec("t1", keep=True)], "sub/page.json": [rec("s1", keep=True)]})

    action.reset()
    action.run({"sub/page.json": [rec("s2", keep=True)]})

    assert action.backend.list_target_files(ACTION) == ["page.json", "sub/page.json"]
    assert action.held("sub/page.json") == ["processed:s2@batch-3"]


def test_a_nested_file_first_seen_after_a_top_level_file_of_that_name_left_takes_its_path(
    tmp_path,
):
    """The rows stored under the top-level name stay, and are not the nested file's."""
    action = _Action(tmp_path)
    action.run({"page.json": [rec("t1", keep=True)]})

    action.reset()
    action.run({"sub/page.json": [rec("s1", keep=True)]})

    assert _registry(action) == ["sub/page.json"]
    assert action.files() == {
        "page.json": ["processed:t1@batch-1"],
        "sub/page.json": ["processed:s1@batch-2"],
    }


def _reopened(backend: SQLiteBackend) -> SQLiteBackend:
    """The same store as a new process opens it, with nothing the last run kept in memory."""
    backend.close()
    again = SQLiteBackend(backend.db_path, workflow_name="w")
    again.initialize()
    return again


def test_two_files_of_one_name_are_collected_apart_after_a_restart(tmp_path):
    """The collect runs in a new process, with only what the store holds."""
    action = _Action(tmp_path)
    twins = {"sub1/page.json": [rec("a1", keep=True)], "sub2/page.json": [rec("b1", keep=True)]}
    action.upstream_holds(twins)
    for name, inputs in twins.items():
        action.process(name, inputs)

    action.backend = _reopened(action.backend)
    action.collect()

    assert _registry(action) == ["sub1/page.json", "sub2/page.json"]
    assert action.files() == {
        "sub1/page.json": ["processed:a1@batch-1"],
        "sub2/page.json": ["processed:b1@batch-2"],
    }
    assert _each_record_held_once(action)
