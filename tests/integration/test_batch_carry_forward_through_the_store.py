"""Batch carry-forward resolves a replaced row through a real store.

The unit tests hand ``_merge_carry_forward`` a mocked backend, so they pin the
rule and not the thing it rests on: that ``producer_source_guids`` survives
``write_target`` → ``read_target_for_rewrite``. It is declared in the envelope's
per-stage set — the fields deliberately not carried to the next action — so a
change to how that set is applied could strip it at the write and leave every
mocked test green while the batch path silently went back to resurrecting rows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_sentinel = object()
if sys.modules.get("agent_actions.workflow.pipeline_file_mode", _sentinel) is _sentinel:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "expand_action"
RELATIVE = "data.json"


def _row(source_guid: str, producer: str, generation: str) -> dict:
    return {
        "source_guid": source_guid,
        "producer_source_guids": [producer],
        "generation": generation,
        # An expansion's rows are stored whole; lifecycle state is what
        # `read_target_for_rewrite` validates on the way back out.
        "_delta_mode": "full",
        "_state": "processed",
        "_state_schema_version": 1,
    }


@pytest.fixture
def backend(tmp_path: Path):
    store = SQLiteBackend(str(tmp_path / "store.db"), "wf")
    store.initialize()
    yield store
    store.close()


@pytest.fixture
def service(backend):
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        workflow_name=ACTION,
        storage_backend=backend,
    )


def test_the_producers_a_row_names_survive_the_store(backend):
    backend.write_target(ACTION, RELATIVE, [_row("m0", "i0", "first")], is_first_action=True)

    stored = backend.read_target_for_rewrite(ACTION, RELATIVE)

    assert [r["producer_source_guids"] for r in stored] == [["i0"]]


def test_a_re_run_replaces_its_rows_and_keeps_the_rest(backend, service):
    backend.write_target(
        ACTION,
        RELATIVE,
        [_row("m0", "i0", "first"), _row("m1", "i0", "first"), _row("k0", "i9", "first")],
        is_first_action=True,
    )

    # i0 resubmitted with its dispositions cleared, i9 never touched. The rows
    # minted for i0 this run carry new identities, as uuid4 always will.
    merged = service._merge_carry_forward(
        ACTION,
        [_row("n0", "i0", "second"), _row("n1", "i0", "second")],
        RELATIVE,
    )

    assert [r["source_guid"] for r in merged] == ["n0", "n1", "k0"]
    assert [r["generation"] for r in merged] == ["second", "second", "first"]


def test_an_input_the_batch_carried_keeps_its_row_through_the_store(backend, service):
    """The guard that stops the producer rule deleting content, against a real store.

    `producer_source_guids` is the consumed set minus the row's own guid, so this row
    does not name `in0` — the input whose content it holds. A row naming several inputs
    is therefore never inferred away: its identity is an input's rather than a mint's,
    and nothing distinguishes the two.
    """
    collapsed = _row("in0", "in1", "first")
    collapsed["producer_source_guids"] = ["in1", "in2"]
    backend.write_target(ACTION, RELATIVE, [collapsed], is_first_action=True)

    merged = service._merge_carry_forward(
        ACTION,
        [_row("in1", "up", "second"), _row("in2", "up", "second")],
        RELATIVE,
    )

    assert [r["source_guid"] for r in merged] == ["in1", "in2", "in0"]
    assert merged[2]["generation"] == "first", "the row's own content was deleted"
