"""A record carried across a deferred round must arrive intact.

Batch defers: a round is a whole submission, so records are persisted between
passes. Anything the serializer forgets is silently gone by the time the record
reaches the output — and the shape is a hand-written key list, which is exactly
the kind that falls behind the dataclass it mirrors.
"""

import dataclasses
import json

from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata


def _full_record() -> BatchResult:
    return BatchResult(
        custom_id="r1",
        content={"answer": "kept"},
        success=False,
        error="rate limited",
        metadata={"model": "test-model"},
        usage={"input_tokens": 11, "output_tokens": 22},
        recovery_metadata=RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=False, reason="rate_limit")
        ),
    )


class TestEveryFieldSurvivesTheRoundTrip:
    def test_no_field_is_silently_dropped(self):
        """Names the fields, so adding one to BatchResult fails here first."""
        serialized = serialize_results([_full_record()])[0]
        declared = {f.name for f in dataclasses.fields(BatchResult)}
        missing = declared - set(serialized)
        assert not missing, (
            f"{sorted(missing)} never reach the persisted state, so they are gone by the time a "
            "deferred round finishes"
        )

    def test_usage_survives(self):
        restored = deserialize_results(serialize_results([_full_record()]))[0]
        assert restored.usage == {"input_tokens": 11, "output_tokens": 22}

    def test_the_error_and_recovery_metadata_survive(self):
        restored = deserialize_results(serialize_results([_full_record()]))[0]
        assert restored.error == "rate limited"
        assert restored.recovery_metadata is not None
        assert restored.recovery_metadata.retry.attempts == 2

    def test_what_is_persisted_is_actually_json(self):
        """The state file is written with json.dumps, so key presence is not enough."""
        json.dumps(serialize_results([_full_record()]))

    def test_an_empty_optional_stays_absent_rather_than_null(self):
        lean = BatchResult(custom_id="r2", content={"a": 1}, success=True)
        serialized = serialize_results([lean])[0]
        assert "error" not in serialized
        assert "usage" not in serialized
        assert deserialize_results([serialized])[0].usage is None
