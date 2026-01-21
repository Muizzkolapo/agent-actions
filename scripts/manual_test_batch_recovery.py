#!/usr/bin/env python3
"""
Manual verification script for Batch Recovery Implementation.
Tests the batch retry and reprompt flows using simulated BatchClient.
"""

import logging
import json
import sys
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from unittest.mock import Mock, patch, MagicMock
from agent_actions.llm.batch.services.processing import (
    BatchProcessingService,
)
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.core.types import RecoveryMetadata, RetryMetadata

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_batch_retry():
    print("\n" + "=" * 50)
    print("Testing BATCH RETRY Simulation")
    print("=" * 50)

    # Mock dependencies
    client_resolver = Mock()
    context_manager = Mock()
    result_processor = Mock()
    registry_manager_factory = Mock()
    registry_manager = Mock()
    registry_manager_factory.return_value = registry_manager

    provider = MagicMock()
    client_resolver.get_for_batch_id.return_value = provider

    # Setup test data
    batch_id = "test_batch_1"
    output_dir = "/tmp/test"

    # Context map (Expected records)
    context_map = {
        "rec_1": {"id": "rec_1", "target_id": "rec_1", "text": "A"},
        "rec_2": {"id": "rec_2", "target_id": "rec_2", "text": "B"},
        "rec_3": {"id": "rec_3", "target_id": "rec_3", "text": "C"},
    }
    context_manager.load_batch_context_map.return_value = context_map

    # Config with retry enabled
    agent_config = {"name": "test_batch", "retry": {"enabled": True, "max_attempts": 2}}

    # MOCK BEHAVIOR:
    # 1. Initial retrieval: Returns rec_1 only (missing rec_2, rec_3)
    # 2. Retry 1: Returns rec_2 (still missing rec_3)
    # 3. Retry 2: Returns rec_3 (all found)

    def retrieve_side_effect(bid, *args, **kwargs):
        if bid == "test_batch_1":
            print("  [Initial] Retrieved 1 record (missing 2)")
            return [BatchResult(custom_id="rec_1", success=True, content={"res": 1})]
        elif bid == "retry_batch_1":
            print("  [Retry 1] Retrieved 1 missing record (found rec_2)")
            return [BatchResult(custom_id="rec_2", success=True, content={"res": 2})]
        elif bid == "retry_batch_2":
            print("  [Retry 2] Retrieved 1 missing record (found rec_3)")
            return [BatchResult(custom_id="rec_3", success=True, content={"res": 3})]
        return []

    provider.retrieve_results.side_effect = retrieve_side_effect
    provider.check_status.return_value = BatchStatus.COMPLETED

    # Capture retry submissions
    provider.submit_batch.side_effect = [
        ("retry_batch_1", "submitted"),
        ("retry_batch_2", "submitted"),
    ]

    # Stub Mock for batch entry
    entry = Mock()
    entry.record_count = 3
    registry_manager.get_batch_job_by_id.return_value = entry

    # Init service
    service = BatchProcessingService(
        client_resolver, context_manager, result_processor, registry_manager_factory
    )

    # We patch _write_batch_output to avoid file IO and just check logic
    with patch.object(service, "_write_batch_output"):
        with patch.object(service, "_determine_output_path", return_value=Path("/tmp/out.json")):
            # Mock the preparator to avoid reading files
            with patch(
                "agent_actions.llm.batch.processing.batch_task_preparator.BatchTaskPreparator"
            ) as prep_cls:
                prep_instance = prep_cls.return_value
                prep_instance.prepare_tasks.return_value = Mock(tasks=[1])  # dummy task

                # Fix: Make process return a list so downstream code can iterate
                result_processor.process.return_value = [{"content": "dummy"}]

                service._process_single_batch_file(
                    batch_id, "test.json", entry, output_dir, agent_config, registry_manager
                )

    # Verify Retries
    print("\nResults:")
    print(f"- Submit calls (retries): {provider.submit_batch.call_count}")

    # Check if results sent to processor include recovery metadata
    call_args = result_processor.process.call_args
    if call_args:
        results = call_args.kwargs["batch_results"]
        print(f"- Total consolidated results: {len(results)}")

        # Check rec_3 metadata (should have 2 retry attempts)
        rec_3 = next((r for r in results if r.custom_id == "rec_3"), None)
        if rec_3 and rec_3.recovery_metadata:
            meta = rec_3.recovery_metadata.retry
            print(f"- Rec_3 Retry Meta: attempts={meta.attempts}, reason={meta.reason}")

            if meta.attempts == 3 and provider.submit_batch.call_count == 2:
                print("✅ TEST PASSED: Batch Retry worked (Original + 2 Retries)")
            else:
                print(f"❌ TEST FAILED: Meta mismatch (Attempts: {meta.attempts})")
        else:
            print("❌ TEST FAILED: No metadata for retried record")
    else:
        print("❌ TEST FAILED: Processor not called")


if __name__ == "__main__":
    test_batch_retry()
