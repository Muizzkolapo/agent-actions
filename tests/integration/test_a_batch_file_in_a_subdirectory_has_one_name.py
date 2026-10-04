"""A batch input file in a subdirectory is sent, keyed and stored under one name.

The name is the file's path under the action's input root, which is what online stores it
under. The code before keyed such a file by its basename alone, so a store it wrote holds
the file under that name, and every action below joins its rows by it: such a file keeps
the name until ``--fresh``, or until a file at the top level needs it.

Driven through the real pipeline, store, registry and collect pass; only the provider is
fake.
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any

import pytest

from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    _FirstStageBatch,
    _Online,
    rec,
)

A_PAGE = [rec("a1", keep=True), rec("a2", keep=True)]
ANSWERED_IN_BATCH_1 = ["processed:a1@batch-1", "processed:a2@batch-1"]
NAMES = f"batch_file_names:{ACTION}"


def _registry(action: _Action) -> list[str]:
    return sorted(BatchRegistryManager(action.backend, ACTION).get_all_jobs())


def _each_record_held_once(action: _Action) -> bool:
    return set(action.backend.target_rows_per_source_guid(ACTION).values()) == {1}


def _as_stored_before(
    action: _Action, name: str, inputs: list[dict[str, Any]], *, collect: bool = True
) -> None:
    """Store *name* as the code before stored a file in a subdirectory.

    It keyed the file by its basename alone -- registry entry, context map, recorded
    inputs and output -- which is the key a top-level file of that name has now. So the
    file is submitted from the top level, while the action above holds it under its own
    path as it did then.
    """
    action.upstream_holds({name: inputs})
    action.process(PurePosixPath(name).name, inputs)
    if collect:
        action.collect()


# A store written by this code.


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


def test_a_first_stage_file_in_a_subdirectory_keeps_one_name_when_nothing_is_sent(tmp_path):
    guard = {"guard": {"clause": "source.keep == true", "behavior": "skip"}}
    batch = _FirstStageBatch(tmp_path, "sub/page.json")
    first = batch.run(1, STAGED, guard)

    again = batch.run(2, [*STAGED, {"item": "f1", "keep": False}], guard)

    assert batch.sent == [["a1", "a2"], []]
    assert [row for row in again if row.startswith("processed:")] == first
    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]


# A store written by the code before, which keyed the file by its basename.


def test_a_file_stored_under_its_basename_before_keeps_that_name(tmp_path):
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)

    action.run({"sub/page.json": A_PAGE})

    assert len(action.provider.batches) == 1
    assert action.files() == {"page.json": ANSWERED_IN_BATCH_1}


def test_a_run_that_sends_nothing_writes_a_file_kept_on_its_basename_there(tmp_path):
    """Written under its path instead, the answers and the tombstone were two files."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)

    action.run({"sub/page.json": [*A_PAGE, rec("f1", keep=False)]})

    assert action.files() == {"page.json": ["guard_skipped:f1", *ANSWERED_IN_BATCH_1]}
    assert _each_record_held_once(action)


def test_a_batch_out_for_a_file_stored_under_its_basename_is_collected_there(tmp_path):
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE, collect=False)

    action.run({"sub/page.json": A_PAGE})

    assert len(action.provider.batches) == 1
    assert action.files() == {"page.json": ANSWERED_IN_BATCH_1}


def test_a_file_kept_on_its_basename_stays_there_when_a_reset_replaces_its_inputs(tmp_path):
    """Its new inputs share nothing with the rows stored there, and the name holds."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)
    action.run({"sub/page.json": A_PAGE})

    action.reset()
    action.run({"sub/page.json": [rec("n1", keep=True), rec("n2", keep=True)]})

    assert action.files() == {"page.json": ["processed:n1@batch-2", "processed:n2@batch-2"]}


def test_a_file_kept_on_its_basename_gives_it_up_to_a_top_level_file_of_that_name(tmp_path):
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)
    action.run({"sub/page.json": A_PAGE})

    action.run({"page.json": [rec("t1", keep=True)], "sub/page.json": A_PAGE})

    assert action.files() == {
        "page.json": ["processed:t1@batch-2"],
        "sub/page.json": ["processed:a1@batch-3", "processed:a2@batch-3"],
    }


def test_of_two_files_that_shared_a_basename_before_the_first_walked_keeps_it(tmp_path):
    """The other one is sent under its own name, rather than over the first one's rows."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub1/page.json", [rec("a1", keep=True)])

    action.run({"sub1/page.json": [rec("a1", keep=True)], "sub2/page.json": [rec("b1", keep=True)]})

    assert action.files() == {
        "page.json": ["processed:a1@batch-1"],
        "sub2/page.json": ["processed:b1@batch-2"],
    }


def test_a_file_that_took_its_own_name_keeps_it_when_the_basename_falls_free(tmp_path):
    """The top-level file leaves, but the rows it was answered with stay in the store."""
    action = _Action(tmp_path)
    action.run({"page.json": [rec("t1", keep=True)], "sub/page.json": [rec("s1", keep=True)]})

    action.reset()
    action.run({"sub/page.json": [rec("s2", keep=True)]})

    assert action.backend.list_target_files(ACTION) == ["page.json", "sub/page.json"]
    assert action.held("sub/page.json") == ["processed:s2@batch-3"]


def test_fresh_moves_a_file_kept_on_its_basename_to_its_own_name(tmp_path):
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)
    action.run({"sub/page.json": A_PAGE})

    action.fresh()
    action.run({"sub/page.json": A_PAGE})

    assert action.files() == {"sub/page.json": ["processed:a1@batch-2", "processed:a2@batch-2"]}


def _names(action: _Action) -> dict[str, str]:
    return json.loads(action.backend.load_metadata(NAMES) or "{}")


def test_a_repair_names_a_file_as_a_full_run_would_and_records_it(tmp_path):
    """The name rests on what the store holds, not on which records a run answers."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", [rec("a1", keep=True), rec("a2", keep=False)])

    action.run({"sub/page.json": A_PAGE}, retry=["a2"])

    assert _names(action) == {"sub/page.json": "page.json"}
    assert action.files() == {"page.json": ["processed:a1@batch-1", "processed:a2@batch-2"]}


def test_two_files_of_one_basename_cannot_both_claim_it_in_a_repair(tmp_path):
    """Unrecorded, the second file claimed the name too, and wrote its answers over it."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub1/page.json", [rec("a1", keep=True)])
    twins = {"sub1/page.json": [rec("a1", keep=True)], "sub2/page.json": [rec("b1", keep=True)]}

    action.run(twins, retry=["b1"])

    assert _names(action) == {"sub1/page.json": "page.json", "sub2/page.json": "sub2/page.json"}
    assert action.files() == {
        "page.json": ["processed:a1@batch-1"],
        "sub2/page.json": ["processed:b1@batch-2"],
    }


def test_a_first_stage_repair_names_a_file_as_a_full_run_would_and_records_it(tmp_path):
    batch = _FirstStageBatch(tmp_path, "page.json")
    batch.run(1, STAGED, {})
    (batch.staging / "page.json").unlink()
    batch.file = "sub/page.json"
    batch.backend = _reopened(batch.backend)

    batch.run(2, STAGED, {}, retried=frozenset({"a-record-of-no-file"}))

    assert batch.sent[1] == []
    assert json.loads(batch.backend.load_metadata(NAMES) or "{}") == {"sub/page.json": "page.json"}


def test_a_file_kept_on_its_basename_is_reported_once(tmp_path, caplog):
    action = _Action(tmp_path)
    _as_stored_before(action, "sub/page.json", A_PAGE)

    with caplog.at_level(logging.INFO, logger="agent_actions"):
        action.run({"sub/page.json": A_PAGE})
        action.run({"sub/page.json": A_PAGE})

    assert [r.getMessage() for r in caplog.records if "keeps the name" in r.getMessage()] == [
        f"{ACTION}: sub/page.json keeps the name page.json, under which this store already "
        "holds it; --fresh moves it to sub/page.json"
    ]


def test_a_file_given_its_own_name_over_a_name_the_store_holds_is_reported_once(tmp_path, caplog):
    """It is sent again under its own name, and the log says why."""
    action = _Action(tmp_path)
    _as_stored_before(action, "sub1/page.json", [rec("a1", keep=True)])
    twins = {"sub1/page.json": [rec("a1", keep=True)], "sub2/page.json": [rec("b1", keep=True)]}

    with caplog.at_level(logging.INFO, logger="agent_actions"):
        action.run(twins)
        action.run(twins)

    assert [r.getMessage() for r in caplog.records if "since page.json" in r.getMessage()] == [
        f"{ACTION}: sub2/page.json is stored as sub2/page.json, since page.json, which this "
        "store already holds, belongs to sub1/page.json; any of its records held there are "
        "sent again"
    ]


def _reopened(backend: SQLiteBackend) -> SQLiteBackend:
    """The same store as a new process opens it, with nothing the last run kept in memory."""
    backend.close()
    again = SQLiteBackend(backend.db_path, workflow_name="w")
    again.initialize()
    return again


def _first_stage_kept_on_its_basename(tmp_path) -> _FirstStageBatch:
    """staging/sub/page.json, stored as a store from before stores it: as page.json."""
    batch = _FirstStageBatch(tmp_path, "page.json")
    batch.run(1, STAGED, {})
    (batch.staging / "page.json").unlink()
    batch.file = "sub/page.json"
    batch.backend = _reopened(batch.backend)

    batch.run(2, STAGED, {})

    assert batch.sent[1] == []
    assert batch.backend.list_target_files(ACTION) == ["page.json"]
    batch.backend = _reopened(batch.backend)
    return batch


def test_a_first_stage_file_kept_on_its_basename_gives_it_up_to_a_staged_file_of_it(tmp_path):
    batch = _first_stage_kept_on_its_basename(tmp_path)
    (batch.staging / "page.json").write_text(json.dumps([{"item": "t1", "keep": True}]))

    held = batch.run(3, STAGED, {})

    assert batch.sent[2] == ["a1", "a2"]
    assert held == ["processed:a1:0@run3", "processed:a2:0@run3"]
    assert batch.backend.list_target_files(ACTION) == ["page.json", "sub/page.json"]


def test_a_staged_file_of_that_stem_and_another_suffix_takes_the_basename(tmp_path):
    """`page.csv` is stored as `page.json` too."""
    batch = _first_stage_kept_on_its_basename(tmp_path)
    (batch.staging / "page.csv").write_text("item,keep\nt1,True\n")

    batch.run(3, STAGED, {})

    assert batch.sent[2] == ["a1", "a2"]


def test_a_staged_directory_named_like_the_file_takes_nothing(tmp_path):
    batch = _first_stage_kept_on_its_basename(tmp_path)
    (batch.staging / "page").mkdir()
    (batch.staging / "page" / "other.json").write_text("[]")

    batch.run(3, STAGED, {})

    assert batch.sent[2] == []
    assert batch.backend.list_target_files(ACTION) == ["page.json"]


def test_a_staged_file_the_walk_leaves_out_takes_nothing(tmp_path):
    """The start node reads only `.json`, so a top-level `page.csv` is no input of it."""
    batch = _first_stage_kept_on_its_basename(tmp_path)
    batch.file_type_filter = {"json"}
    (batch.staging / "page.csv").write_text("item,keep\nt1,True\n")

    batch.run(3, STAGED, {})

    assert batch.sent[2] == []
    assert batch.backend.list_target_files(ACTION) == ["page.json"]
