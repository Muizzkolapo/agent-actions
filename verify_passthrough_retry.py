import sys
from unittest.mock import MagicMock
from agent_actions.llm_invocation.batch.services.batch_processing_service import (
    BatchProcessingService,
)
from agent_actions.llm_invocation.providers.batch_client_base import BatchResult
from agent_actions.core.types import RecoveryMetadata, RetryMetadata
from agent_actions.llm_invocation.batch.processing.batch_result_processor import (
    BatchResultProcessor,
)


def test_per_record_recovery_metadata_with_passthrough():
    # Setup mocks
    client_resolver = MagicMock()
    context_manager = MagicMock()
    result_processor = MagicMock()
    registry_manager_factory = MagicMock()

    # Define some batch results
    # res1 succeeded first time
    res1 = BatchResult(custom_id="req-1", content={"data": "success1"}, success=True)
    # req-2 is missing (will become passthrough)

    batch_results = [res1]
    context_map = {"req-1": {"source_guid": "guid-1"}, "req-2": {"source_guid": "guid-2"}}

    # Global recovery metadata (from a failed retry loop)
    global_recovery = RecoveryMetadata(
        retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="missing")
    )

    # Test Processor behavior
    processor = BatchResultProcessor()
    processed_data = processor.process(
        batch_results=batch_results,
        context_map=context_map,
        agent_config={"agent_type": "test_agent"},
        recovery_metadata=global_recovery,
    )

    # Verify guid-1 output has NO _recovery (succeeded first try)
    item1 = next(item for item in processed_data if item["source_guid"] == "guid-1")
    assert "_recovery" not in item1

    # Verify guid-2 output HAS _recovery (passthrough record from failed retry)
    item2 = next(item for item in processed_data if item["source_guid"] == "guid-2")
    assert "_recovery" in item2
    assert item2["_recovery"]["retry"]["attempts"] == 3
    assert item2["_recovery"]["retry"]["succeeded"] is False

    print("Verification passed: Passthrough records correctly receive global recovery metadata!")


if __name__ == "__main__":
    try:
        test_per_record_recovery_metadata_with_passthrough()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
