"""A record the provider failed is stored under batch as online stores it: the record's own
content with the failed action's namespace null (1363).

A FILE tool or HITL action below reads its `context_scope` before the cascade filter looks at a
record's state, so a row without the record's content left it nothing to read.
"""

from typing import Any

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import (
    ExpectationsMetadata,
    ProcessingStatus,
    RecoveryMetadata,
)

ACTION = "summarize"
UPSTREAM = {"summary": "kept"}


def _record() -> dict[str, Any]:
    return {
        "source_guid": "sg-1",
        "target_id": "t-1",
        "content": {"source": {"page_content": "Page alpha."}, "intake": UPSTREAM},
        "lineage": ["node-0"],
    }


def _config() -> dict[str, Any]:
    return {"name": ACTION, "action_name": ACTION, "json_mode": True}


def _failed(batch_result: BatchResult):
    results = BatchResultStrategy().process(
        [batch_result],
        context_map={"t-1": _record()},
        output_directory="/tmp/x",
        agent_config=_config(),
    )
    (result,) = results
    return result


def test_a_provider_error_row_keeps_the_records_content():
    result = _failed(BatchResult(custom_id="t-1", content=None, success=False, error="HTTP 500"))

    assert result.status == ProcessingStatus.FAILED
    row = result.data[0]
    assert row["content"]["source"] == {"page_content": "Page alpha."}
    assert row["content"]["intake"] == UPSTREAM
    assert row["content"][ACTION] is None


def test_the_row_still_names_the_record_and_what_the_provider_said():
    result = _failed(BatchResult(custom_id="t-1", content=None, success=False, error="HTTP 500"))

    row = result.data[0]
    assert row["source_guid"] == "sg-1"
    assert row["target_id"] == "t-1"
    assert row["error"] == "HTTP 500"


def test_the_row_is_marked_a_tombstone_with_the_error_as_its_reason():
    result = _failed(BatchResult(custom_id="t-1", content=None, success=False, error="HTTP 500"))

    row = result.data[0]
    assert row["_tombstone"] is True
    assert row["metadata"]["reason"] == "HTTP 500"
    assert row["metadata"]["agent_type"] == "tombstone"


def test_the_providers_own_metadata_rides_on_the_row():
    result = _failed(
        BatchResult(
            custom_id="t-1",
            content=None,
            success=False,
            error="boom",
            metadata={"model": "m-1", "reason": "must not replace the tombstone's"},
        )
    )

    metadata = result.data[0]["metadata"]
    assert metadata["model"] == "m-1"
    assert metadata["reason"] == "boom"


def test_the_recovery_metadata_rides_on_the_row():
    recovery = RecoveryMetadata(expectations=ExpectationsMetadata(attempts=2, failed=["rule"]))
    result = _failed(
        BatchResult(
            custom_id="t-1", content=None, success=False, error="boom", recovery_metadata=recovery
        )
    )

    assert result.data[0]["_recovery"] == {"expectations": {"attempts": 2, "failed": ["rule"]}}


def test_an_empty_answer_under_warn_keeps_the_records_content_too():
    result = _failed(BatchResult(custom_id="t-1", content={}, success=True))

    assert result.status == ProcessingStatus.FAILED
    assert result.data[0]["content"]["intake"] == UPSTREAM
    assert result.data[0]["content"][ACTION] is None


def test_a_raw_answer_that_failed_processing_is_kept_beside_the_error():
    strategy = BatchResultStrategy()
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={"t-1": _record()},
        output_directory="/tmp/x",
        agent_config=_config(),
    )
    ctx.reconciler = BatchResultReconciler(context_map=ctx.context_map)

    result = strategy._build_error_result(
        ctx, "t-1", "Processing error: bad", {}, raw_content={"summary": 7}
    )

    assert result.data[0]["raw_content"] == {"summary": 7}
    assert result.data[0]["content"]["intake"] == UPSTREAM


def test_an_id_with_no_context_entry_still_builds_a_row():
    """A parser placeholder such as `error_line_3` names no record in the context map."""
    strategy = BatchResultStrategy()
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={"t-1": _record()},
        output_directory="/tmp/x",
        agent_config=_config(),
    )
    ctx.reconciler = BatchResultReconciler(context_map=ctx.context_map)

    result = strategy._build_error_result(ctx, "error_line_3", "unparseable line", {})

    assert result.status == ProcessingStatus.FAILED
    assert result.source_guid is None
    assert result.data[0]["error"] == "unparseable line"
