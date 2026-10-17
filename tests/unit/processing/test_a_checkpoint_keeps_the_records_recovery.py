"""A record carried from its checkpoint is stored with the `_recovery` it earned.

The checkpoint kept only the record's rows. Carried on the next run, the record was
enriched without its recovery metadata, so one that needed a retry before it was
answered was stored with `_recovery: null`, unlike the same record in an uninterrupted
run (1320).
"""

import pytest

from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "tag"
PATH = "pages.json"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _retried_once() -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="network_error")
    )


def _checkpoint(backend, recovery: RecoveryMetadata | None) -> list[dict]:
    context = ProcessingContext(
        agent_config={"name": ACTION},
        agent_name=ACTION,
        storage_backend=backend,
        target_relative_path=PATH,
    )
    result = ProcessingResult.success(
        data=[{"source_guid": "sg-1", "content": {ACTION: {"tag": "alpha"}}}],
        source_guid="sg-1",
    )
    result.recovery_metadata = recovery
    OnlineLLMStrategy._checkpoint_record(result, context)
    return backend.read_checkpoint_records(ACTION, PATH)


def test_the_carried_record_keeps_its_retry(backend):
    rows = _checkpoint(backend, _retried_once())

    carried = UnifiedProcessor._answered_from_checkpoint(rows[0])

    assert carried.recovery_metadata is not None
    assert carried.recovery_metadata.to_dict() == _retried_once().to_dict()
    assert set(carried.data[0]) == {"source_guid", "content"}


def test_a_record_that_needed_no_recovery_carries_none(backend):
    rows = _checkpoint(backend, None)

    carried = UnifiedProcessor._answered_from_checkpoint(rows[0])

    assert carried.recovery_metadata is None
    assert set(carried.data[0]) == {"source_guid", "content"}
