"""A still-failing record excluded from the reprompt must still reach finalization.

``check_and_submit_reprompt`` splits results three ways — graduated, repromptable,
and still-failing-with-no-content — but only the first two survive the pause: one
is persisted to the recovery state, the other comes back in the reprompt batch.
The third is in neither, so the record the provider *did* answer (with an error)
is reported at finalization as one the batch never returned.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    RecoveryContext,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing_recovery import (
    check_and_submit_reprompt,
    handle_reprompt_recovery,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.recovery.validation import reprompt_validation
from agent_actions.processing.types import ProcessingStatus

ACTION = "label_page"
PARENT = "pages.json"

OK_ID = "rec-ok"
BAD_ID = "rec-bad"
DEAD_ID = "rec-dead"

PROVIDER_ERROR = "provider rejected the request"


@reprompt_validation("Return a non-empty topic.")
def _topic_present(response: dict) -> bool:
    return isinstance(response, dict) and bool(response.get("topic"))


AGENT_CONFIG = {
    "kind": "llm",
    "action_name": ACTION,
    "json_mode": True,
    "reprompt": {"validation": "_topic_present", "max_attempts": 2},
}

CONTEXT_MAP = {
    OK_ID: {"user_content": "one", "source_guid": OK_ID},
    BAD_ID: {"user_content": "two", "source_guid": BAD_ID},
    DEAD_ID: {"user_content": "three", "source_guid": DEAD_ID},
}


class _MetadataBackend:
    """The metadata slice of StorageBackend that recovery-state persistence uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


def _entry(recovery_type: str | None = None, attempt: int = 0) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="batch_parent" if recovery_type is None else f"batch_{recovery_type}_{attempt}",
        status=BatchStatus.COMPLETED,
        timestamp="2026-08-30T09:00:00+00:00",
        provider="ollama_local",
        record_count=3,
        file_name=PARENT if recovery_type is None else f"{PARENT}_{recovery_type}_{attempt}",
        parent_file_name=None if recovery_type is None else PARENT,
        recovery_type=recovery_type,
        recovery_attempt=attempt,
    )


class _Harness:
    """Real evaluation loop and real recovery-state persistence across the pause.

    Only the provider submission and the output writer are stand-ins: the split,
    the state round-trip, and the set handed to finalization are the real thing.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.backend = _MetadataBackend()
        self.finalized: list[BatchResult] = []

        service = MagicMock()
        service._storage_backend = self.backend
        service._workflow_name = ACTION
        service._resolve_action_name = lambda override=None: override or ACTION
        service._retry_service.submit_reprompt_batch.return_value = ("batch_reprompt_1", 1)
        service._convert_batch_results_to_workflow_format.side_effect = self._capture
        service._determine_output_path.return_value = tmp_path / "out.json"
        self.service = service

        self.context = RecoveryContext(
            service=service,
            manager=MagicMock(),
            provider=MagicMock(),
            agent_config=AGENT_CONFIG,
            output_directory=str(tmp_path),
            action_name=ACTION,
            start_time=0.0,
        )

    def _capture(self, batch_results, **_kwargs):
        self.finalized = list(batch_results)
        return ([], MagicMock())

    def submit_pass(self, batch_results: list[BatchResult]) -> bool:
        return check_and_submit_reprompt(
            self.context,
            BatchIdentity(batch_id="batch_parent", file_name=PARENT, entry=_entry()),
            batch_results=batch_results,
            context_map=CONTEXT_MAP,
            recovery_state=None,
        )

    def reprompt_pass(self, recovery_results: list[BatchResult]) -> None:
        state = RecoveryStateManager.load(self.backend, ACTION, PARENT)
        assert state is not None, "reprompt submission must have persisted recovery state"
        handle_reprompt_recovery(
            self.context,
            BatchIdentity(
                batch_id="batch_reprompt_1",
                file_name=PARENT,
                entry=_entry("reprompt", 1),
            ),
            state=state,
            recovery_results=recovery_results,
            accumulated=[],
            context_map=CONTEXT_MAP,
        )


def _initial_results() -> list[BatchResult]:
    return [
        BatchResult(custom_id=OK_ID, content={"topic": "models"}, success=True),
        BatchResult(custom_id=BAD_ID, content={"topic": ""}, success=True),
        BatchResult(custom_id=DEAD_ID, content=None, success=False, error=PROVIDER_ERROR),
    ]


def _run_both_passes(tmp_path: Path) -> _Harness:
    harness = _Harness(tmp_path)

    assert harness.submit_pass(_initial_results()) is False, (
        "the repromptable record should have paused processing for a reprompt batch"
    )
    harness.reprompt_pass(
        [BatchResult(custom_id=BAD_ID, content={"topic": "repaired"}, success=True)]
    )
    return harness


def test_no_content_record_reaches_finalization(tmp_path):
    harness = _run_both_passes(tmp_path)

    finalized = {r.custom_id: r for r in harness.finalized}
    assert DEAD_ID in finalized, (
        f"record excluded from the reprompt never reached finalization: {sorted(finalized)}"
    )
    assert finalized[DEAD_ID].error == PROVIDER_ERROR
    assert finalized[BAD_ID].content == {"topic": "repaired"}
    assert finalized[OK_ID].content == {"topic": "models"}


def test_no_content_record_is_failed_not_reported_as_never_returned(tmp_path):
    harness = _run_both_passes(tmp_path)

    processed = BatchResultStrategy().process(
        harness.finalized,
        context_map=CONTEXT_MAP,
        agent_config=AGENT_CONFIG,
    )
    dead = next(r for r in processed if r.source_guid == DEAD_ID)

    assert dead.status is ProcessingStatus.FAILED, (
        f"expected a terminal failure, got {dead.status} (skip_reason={dead.skip_reason})"
    )
    assert dead.data and dead.data[0]["error"] == PROVIDER_ERROR
