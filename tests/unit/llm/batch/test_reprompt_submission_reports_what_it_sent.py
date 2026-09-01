"""The reprompt submitter must not shrink the set the caller books as in flight.

``check_and_submit_reprompt`` partitions results into graduated, withheld, and
repromptable, and hands the last to ``submit_reprompt_batch``. The partition is
only sound if "handed to the submitter" means "submitted". Two things can shrink
it: a record absent from ``context_map``, and a record preparation discards. The
caller sees a count, so neither is visible to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    RecoveryContext,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.services.processing_recovery import check_and_submit_reprompt
from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.recovery.validation import (
    _VALIDATION_REGISTRY,
    reprompt_validation,
)

ACTION = "label_page"
PARENT = "pages.json"

OK_ID = "rec-ok"
BAD_ID = "rec-bad"
DROPPED_ID = "rec-dropped"
STRANGER_ID = "rec-not-in-context-map"

VALIDATION = "_topic_present"


def _topic_present(response: dict) -> bool:
    return isinstance(response, dict) and bool(response.get("topic"))


@pytest.fixture(autouse=True)
def _registered_validation():
    reprompt_validation("Return a non-empty topic.")(_topic_present)
    yield
    _VALIDATION_REGISTRY.pop(VALIDATION, None)


AGENT_CONFIG = {
    "kind": "llm",
    "action_name": ACTION,
    "json_mode": True,
    "reprompt": {"validation": VALIDATION, "max_attempts": 2},
}

CONTEXT_MAP = {
    OK_ID: {"user_content": "one", "source_guid": OK_ID},
    BAD_ID: {"user_content": "two", "source_guid": BAD_ID},
    DROPPED_ID: {"user_content": "three", "source_guid": DROPPED_ID},
}


def _failing(custom_id: str) -> BatchResult:
    return BatchResult(custom_id=custom_id, content={"topic": ""}, success=True)


def _prepared(included_ids: list[str]) -> MagicMock:
    """A preparation result that admitted only *included_ids*."""
    context_map = {}
    for custom_id in CONTEXT_MAP:
        row = dict(CONTEXT_MAP[custom_id])
        BatchContextMetadata.set_filter_status(
            row, FilterStatus.INCLUDED if custom_id in included_ids else FilterStatus.FILTERED
        )
        context_map[custom_id] = row
    prepared = MagicMock()
    prepared.tasks = [{"custom_id": cid} for cid in included_ids]
    prepared.context_map = context_map
    return prepared


def _preparator_returning(prepared: MagicMock) -> MagicMock:
    cls = MagicMock()
    cls.return_value.prepare_tasks.return_value = prepared
    return cls


# ---------------------------------------------------------------------------
# The corrupt-state branch
# ---------------------------------------------------------------------------


def test_a_record_absent_from_the_context_map_is_not_skipped_quietly():
    """It cannot be rebuilt and cannot be covered downstream — that is corrupt state."""
    provider = MagicMock()
    provider.submit_batch.return_value = ("batch_reprompt_1", BatchStatus.SUBMITTED)

    with (
        patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            _preparator_returning(_prepared([BAD_ID])),
        ),
        pytest.raises(RuntimeError) as excinfo,
    ):
        submit_reprompt_batch(
            action_indices={},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[_failing(BAD_ID), _failing(STRANGER_ID)],
            context_map=CONTEXT_MAP,
            output_directory="/tmp",
            file_name=PARENT,
            agent_config=AGENT_CONFIG,
            attempt=1,
        )

    assert STRANGER_ID in str(excinfo.value)


# ---------------------------------------------------------------------------
# The legitimate-shrinkage branch
# ---------------------------------------------------------------------------


def test_the_submitter_reports_the_ids_it_actually_sent():
    provider = MagicMock()
    provider.submit_batch.return_value = ("batch_reprompt_1", BatchStatus.SUBMITTED)

    with patch(
        "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
        _preparator_returning(_prepared([BAD_ID])),
    ):
        result = submit_reprompt_batch(
            action_indices={},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[_failing(BAD_ID), _failing(DROPPED_ID)],
            context_map=CONTEXT_MAP,
            output_directory="/tmp",
            file_name=PARENT,
            agent_config=AGENT_CONFIG,
            attempt=1,
        )

    assert result is not None
    batch_id, submitted_ids = result
    assert batch_id == "batch_reprompt_1"
    assert set(submitted_ids) == {BAD_ID}, "the caller cannot see which records were dropped"


# ---------------------------------------------------------------------------
# What the caller does with it
# ---------------------------------------------------------------------------


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


def _entry() -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="batch_parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-09-01T09:00:00+00:00",
        provider="ollama_local",
        record_count=3,
        file_name=PARENT,
    )


class _Harness:
    """Real submitter, real state persistence; only the provider is a stand-in."""

    def __init__(self, tmp_path: Path, included_ids: list[str]) -> None:
        self.backend = _MetadataBackend()
        self.finalized: list[BatchResult] = []
        self.included_ids = included_ids

        from agent_actions.llm.batch.services import reprompt_ops

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_reprompt_1", BatchStatus.SUBMITTED)

        service = MagicMock()
        service._storage_backend = self.backend
        service._workflow_name = ACTION
        service._resolve_action_name = lambda override=None: override or ACTION
        service._retry_service.submit_reprompt_batch.side_effect = (
            lambda **kw: reprompt_ops.submit_reprompt_batch(
                action_indices={}, dependency_configs={}, storage_backend=None, **kw
            )
        )
        service._convert_batch_results_to_workflow_format.side_effect = self._capture
        service._determine_output_path.return_value = tmp_path / "out.json"
        self.service = service

        self.context = RecoveryContext(
            service=service,
            manager=MagicMock(),
            provider=provider,
            agent_config=AGENT_CONFIG,
            output_directory=str(tmp_path),
            action_name=ACTION,
            start_time=0.0,
        )

    def _capture(self, batch_results, **_kwargs):
        self.finalized = list(batch_results)
        return ([], MagicMock())

    def submit_pass(self, batch_results: list[BatchResult]) -> bool:
        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            _preparator_returning(_prepared(self.included_ids)),
        ):
            return check_and_submit_reprompt(
                self.context,
                BatchIdentity(batch_id="batch_parent", file_name=PARENT, entry=_entry()),
                batch_results=batch_results,
                context_map=CONTEXT_MAP,
                recovery_state=None,
            )

    def state(self):
        return RecoveryStateManager.load(self.backend, ACTION, PARENT)


def _results() -> list[BatchResult]:
    return [
        BatchResult(custom_id=OK_ID, content={"topic": "models"}, success=True),
        _failing(BAD_ID),
        _failing(DROPPED_ID),
    ]


def test_a_record_preparation_dropped_is_not_booked_as_attempted(tmp_path):
    h = _Harness(tmp_path, included_ids=[BAD_ID])
    h.submit_pass(_results())

    state = h.state()
    assert state is not None
    assert DROPPED_ID not in state.reprompt_attempts_per_record, (
        "an attempt was booked for a record that was never sent"
    )
    assert BAD_ID in state.reprompt_attempts_per_record


def test_a_record_preparation_dropped_is_carried_forward(tmp_path):
    h = _Harness(tmp_path, included_ids=[BAD_ID])
    h.submit_pass(_results())

    state = h.state()
    assert state is not None
    carried = {r["custom_id"] for r in state.unrepromptable_results}
    assert DROPPED_ID in carried, "the dropped record is in no pool and no batch"


# ---------------------------------------------------------------------------
# Round two takes a different code path with the same defect
# ---------------------------------------------------------------------------


def _registry(backend: _MetadataBackend):
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {PARENT: _entry().to_dict()}
    )
    return BatchRegistryManager(backend, ACTION)


def _round_two_state(backend):
    from agent_actions.llm.batch.infrastructure.recovery_state import (
        RecoveryPhase,
        RecoveryState,
    )
    from agent_actions.llm.batch.services.retry_serialization import serialize_results

    state = RecoveryState(
        phase=RecoveryPhase.REPROMPT,
        reprompt_attempt=1,
        reprompt_max_attempts=3,
        validation_name=VALIDATION,
        evaluation_strategy_name=VALIDATION,
        graduated_results=serialize_results([]),
        reprompt_attempts_per_record={BAD_ID: 1, DROPPED_ID: 1},
    )
    RecoveryStateManager.save(backend, ACTION, PARENT, state)
    return RecoveryStateManager.load(backend, ACTION, PARENT)


def _drive_round_two(tmp_path: Path, included_ids: list[str]):
    """handle_reprompt_recovery over a real registry — the round-2 submission path."""
    from agent_actions.llm.batch.services import reprompt_ops
    from agent_actions.llm.batch.services.processing_recovery import handle_reprompt_recovery

    backend = _MetadataBackend()
    manager = _registry(backend)

    provider = MagicMock()
    provider.submit_batch.return_value = ("batch_reprompt_2", BatchStatus.SUBMITTED)

    service = MagicMock()
    service._storage_backend = backend
    service._workflow_name = ACTION
    service._resolve_action_name = lambda override=None: override or ACTION
    service._retry_service.submit_reprompt_batch.side_effect = (
        lambda **kw: reprompt_ops.submit_reprompt_batch(
            action_indices={}, dependency_configs={}, storage_backend=None, **kw
        )
    )
    service._convert_batch_results_to_workflow_format.side_effect = lambda b, **k: ([], MagicMock())
    service._determine_output_path.return_value = tmp_path / "out.json"

    context = RecoveryContext(
        service=service,
        manager=manager,
        provider=provider,
        agent_config=AGENT_CONFIG,
        output_directory=str(tmp_path),
        action_name=ACTION,
        start_time=0.0,
    )
    identity = BatchIdentity(batch_id="batch_reprompt_1", file_name=PARENT, entry=_entry())

    with patch(
        "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
        _preparator_returning(_prepared(included_ids)),
    ):
        handle_reprompt_recovery(
            context,
            identity,
            state=_round_two_state(backend),
            recovery_results=[_failing(BAD_ID), _failing(DROPPED_ID)],
            accumulated=[],
            context_map=CONTEXT_MAP,
        )
    return backend, manager


def test_a_second_reprompt_round_persists_its_registry_entry(tmp_path):
    """The submitted-id set must not reach the registry, which JSON-serialises it."""
    backend, manager = _drive_round_two(tmp_path, included_ids=[BAD_ID, DROPPED_ID])

    entry = manager.get_batch_job_by_id("batch_reprompt_2")
    assert entry is not None, "the round-2 recovery batch was never registered"
    assert entry.record_count == 2


def test_a_second_round_drop_is_not_booked_as_attempted(tmp_path):
    backend, _ = _drive_round_two(tmp_path, included_ids=[BAD_ID])

    state = RecoveryStateManager.load(backend, ACTION, PARENT)
    assert state is not None
    assert state.reprompt_attempts_per_record[BAD_ID] == 2
    assert state.reprompt_attempts_per_record[DROPPED_ID] == 1, (
        "round two booked an attempt for a record it never sent"
    )
    carried = {r["custom_id"] for r in state.unrepromptable_results}
    assert DROPPED_ID in carried, "the round-two drop is in no pool and no batch"


def test_an_unparseable_line_placeholder_is_not_treated_as_a_lost_record():
    """error_line_N is a per-file diagnostic, not a record — it has no context entry.

    The round-two path hands still_failing to the submitter unfiltered, so these
    reach it. Raising on them would abort a run over one unreadable line.
    """
    provider = MagicMock()
    provider.submit_batch.return_value = ("batch_reprompt_1", BatchStatus.SUBMITTED)
    placeholder = BatchResult(
        custom_id="error_line_3", content=None, success=False, error="JSON parsing error"
    )

    with patch(
        "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
        _preparator_returning(_prepared([BAD_ID])),
    ):
        result = submit_reprompt_batch(
            action_indices={},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[_failing(BAD_ID), placeholder],
            context_map=CONTEXT_MAP,
            output_directory="/tmp",
            file_name=PARENT,
            agent_config=AGENT_CONFIG,
            attempt=1,
        )

    assert result is not None
    _, submitted_ids = result
    assert set(submitted_ids) == {BAD_ID}
