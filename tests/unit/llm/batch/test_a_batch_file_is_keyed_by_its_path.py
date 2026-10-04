"""Every key a batch keeps for an input file is the file's path under the input root.

Keyed by its basename, a file in a subdirectory shares its registry entry, context map,
recorded inputs and recovery state with every other file of that name, and its output
with a top-level one. A top-level file's keys are what they always were, so a store
written before reads the same.
"""

from __future__ import annotations

import json
import logging

import pytest

from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    batch_file_identity,
    batch_output_name,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

KEYS = {
    "context map": (BatchContextManager._metadata_key, "batch_context"),
    "recorded inputs": (BatchContextManager._inputs_key, "batch_inputs"),
    "recovery state": (RecoveryStateManager._metadata_key, "recovery_state"),
}
EACH_KEY = pytest.mark.parametrize("key", KEYS.values(), ids=KEYS.keys())


@pytest.mark.parametrize(
    ("name", "stored"),
    [
        ("page.json", "page.json"),
        ("page.csv", "page.json"),
        ("sub/page.csv", "sub/page.json"),
        ("sub/page.json", "sub/page.json"),
        ("a/b/c.tar.gz", "a/b/c.tar.json"),
        ("noext", "noext.json"),
        (".hidden", ".hidden.json"),
    ],
)
def test_a_batch_output_is_stored_under_its_input_path_as_json(name, stored):
    assert batch_output_name(name) == stored


@EACH_KEY
@pytest.mark.parametrize("name", ["page.json", "page.csv", "noext"])
def test_a_top_level_file_is_keyed_as_it_was(key, name):
    build, prefix = key
    assert build("act", name) == f"{prefix}:act:{name}"


@EACH_KEY
def test_a_file_in_a_subdirectory_keeps_its_directory_in_the_key(key):
    build, prefix = key
    assert build("act", "sub/page.json") == f"{prefix}:act:sub/page.json"


@EACH_KEY
@pytest.mark.parametrize("name", ["v1..2/page.json", "notes..v2.json"])
def test_two_dots_inside_a_name_are_part_of_the_name(key, name):
    """The store refuses only a `..` that is a whole part; online writes these files."""
    build, prefix = key
    assert build("act", name) == f"{prefix}:act:{name}"


@EACH_KEY
@pytest.mark.parametrize("name", ["../x.json", "a/../b.json", "/abs/x.json"])
def test_a_name_that_leaves_the_input_root_is_refused(key, name):
    build, _prefix = key
    with pytest.raises(ValueError):
        build("act", name)


def test_a_reset_keeps_the_names_its_files_were_given_and_fresh_forgets_them(tmp_path):
    """The name follows the stored rows: a reset keeps them, `--fresh` deletes them."""
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    backend.save_metadata("batch_file_names:act", '{"sub/page.json": "page.json"}')
    backend.save_metadata("batch_file_names:other", '{"sub/page.json": "sub/page.json"}')

    backend.clear_batch_state("act")

    assert backend.load_metadata("batch_file_names:act") is not None

    backend.delete_target("act")

    assert backend.load_metadata("batch_file_names:act") is None
    assert backend.load_metadata("batch_file_names:other") is not None


def _holding_page_json(tmp_path) -> SQLiteBackend:
    """A store whose action `act` holds `page.json`, as one from before holds a nested file."""
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    backend.write_target("act", "page.json", [{"source_guid": "a1", "content": {}}])
    return backend


def _named(backend: SQLiteBackend, path: str) -> str:
    return batch_file_identity(
        path,
        "act",
        backend,
        base_owner=lambda legacy: False,
        registry=lambda action: BatchRegistryManager(backend, action),
    )


def test_a_name_claimed_by_one_file_is_not_claimed_by_another_stored_under_it(tmp_path):
    """`page.csv` and `page.json` are two basenames, and one stored name."""
    backend = _holding_page_json(tmp_path)

    assert [_named(backend, "sub1/page.csv"), _named(backend, "sub2/page.json")] == [
        "page.csv",
        "sub2/page.json",
    ]


@pytest.mark.parametrize("recorded", ["not json", "[1, 2]"], ids=["not-json", "not-a-mapping"])
def test_an_unreadable_record_of_names_is_decided_again_with_a_warning(tmp_path, caplog, recorded):
    """Raising would stop every batch of the action over a name the store can decide again."""
    backend = _holding_page_json(tmp_path)
    backend.save_metadata("batch_file_names:act", recorded)

    with caplog.at_level(logging.WARNING, logger="agent_actions"):
        name = _named(backend, "sub/page.json")

    assert name == "page.json"
    assert "Unreadable batch_file_names:act" in caplog.text
    assert json.loads(backend.load_metadata("batch_file_names:act") or "{}") == {
        "sub/page.json": "page.json"
    }
