"""Manual verification for async batch retry & reprompt (#942).

Exercises:
  (a) Retry submission without blocking
  (b) Reprompt submission without blocking
  (c) Multi-pass recovery lifecycle (retry → reprompt → finalize)
  (d) Recovery state persistence across passes
  (e) Registry skip-recovery-entries behavior

Run: pytest tests/verify_async_recovery.py -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata


def _make_result(custom_id, content="ok", success=True):
    return BatchResult(custom_id=custom_id, content=content, success=success)


class TestRetrySubmissionWithoutBlocking(unittest.TestCase):
    """(a) Verify retry batch submission returns immediately (no sleep/poll)."""

    def test_submit_retry_returns_batch_id_without_waiting(self):
        """submit_retry_batch should return (batch_id, count) immediately."""
        service = BatchRetryService()
        provider = MagicMock()
        provider.submit_batch.return_value = ("retry-batch-99", "submitted")

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "t1"}, {"body": "t2"}])
            mock_prep_cls.return_value = mock_prep

            result = service.submit_retry_batch(
                provider=provider,
                missing_ids={"a", "b"},
                context_map={"a": {"target_id": "a"}, "b": {"target_id": "b"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config={},
            )

        self.assertIsNotNone(result)
        batch_id, count = result
        self.assertEqual(batch_id, "retry-batch-99")
        self.assertEqual(count, 2)
        # Verify no blocking calls
        provider.check_status.assert_not_called()
        print("  PASS: submit_retry_batch returns immediately without blocking")


class TestRepromptSubmissionWithoutBlocking(unittest.TestCase):
    """(b) Verify reprompt batch submission returns immediately."""

    def test_submit_reprompt_returns_batch_id_without_waiting(self):
        """submit_reprompt_batch should return (batch_id, count) immediately."""
        service = BatchRetryService()
        provider = MagicMock()
        provider.submit_batch.return_value = ("reprompt-batch-42", "submitted")

        failed_results = [_make_result("x", content="bad", success=False)]
        agent_config = {
            "reprompt": {"validation": "check_json", "max_attempts": 2},
        }

        with (
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
            ) as mock_prep_cls,
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function"
            ) as mock_get_val,
            patch(
                "agent_actions.processing.recovery.response_validator.build_validation_feedback",
                return_value="Please fix your response.",
            ),
        ):
            mock_get_val.return_value = (MagicMock(), "Fix your output")
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "t1"}])
            mock_prep_cls.return_value = mock_prep

            result = service.submit_reprompt_batch(
                provider=provider,
                failed_results=failed_results,
                context_map={"x": {"target_id": "x", "user_content": "original prompt"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config=agent_config,
                attempt=1,
            )

        self.assertIsNotNone(result)
        batch_id, count = result
        self.assertEqual(batch_id, "reprompt-batch-42")
        self.assertEqual(count, 1)
        provider.check_status.assert_not_called()
        print("  PASS: submit_reprompt_batch returns immediately without blocking")


class TestMultiPassRecoveryLifecycle(unittest.TestCase):
    """(c) Simulate a full multi-pass lifecycle: original → retry → reprompt → finalize."""

    def test_full_lifecycle(self):
        """Simulate 3-pass recovery: submit retry, process retry, finalize."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # --- Pass 1: Original batch result has missing record "b" ---
            initial_results = [_make_result("a")]
            serialized = BatchRetryService.serialize_results(initial_results)

            state = RecoveryState(
                phase="retry",
                retry_attempt=1,
                retry_max_attempts=2,
                missing_ids=["b"],
                record_failure_counts={"b": 1},
                accumulated_results=serialized,
            )

            # Save state
            RecoveryStateManager.save(tmp_dir, "original.jsonl", state)
            self.assertTrue(
                RecoveryStateManager.exists(tmp_dir, "original.jsonl"),
                "State should be persisted after save",
            )

            # --- Pass 2: Retry batch returns "b" successfully ---
            loaded = RecoveryStateManager.load(tmp_dir, "original.jsonl")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.phase, "retry")

            accumulated = BatchRetryService.deserialize_results(loaded.accumulated_results)
            retry_results = [_make_result("b")]

            service = BatchRetryService()
            merged, still_missing, counts, exhausted = service.process_retry_results(
                results=retry_results,
                accumulated_results=accumulated,
                context_map={"a": {}, "b": {}},
                record_failure_counts=loaded.record_failure_counts,
                missing_ids=set(loaded.missing_ids),
            )

            self.assertEqual(len(merged), 2, "Should have both a and b")
            self.assertEqual(still_missing, set(), "No more missing records")
            self.assertIsNone(exhausted, "No exhausted records")

            # --- Pass 3: No reprompt configured → finalize ---
            # Clean up state
            RecoveryStateManager.delete(tmp_dir, "original.jsonl")
            self.assertFalse(
                RecoveryStateManager.exists(tmp_dir, "original.jsonl"),
                "State should be cleaned up after finalization",
            )

            print("  PASS: Multi-pass lifecycle (retry → merge → finalize)")

    def test_exhausted_retry_produces_metadata(self):
        """When retries exhaust, build_exhausted_recovery produces metadata."""
        service = BatchRetryService()
        still_missing = {"b", "c"}
        failure_counts = {"b": 3, "c": 2}

        exhausted = service.build_exhausted_recovery(still_missing, failure_counts)

        self.assertIn("b", exhausted)
        self.assertIn("c", exhausted)
        self.assertFalse(exhausted["b"].retry.succeeded)
        self.assertEqual(exhausted["b"].retry.failures, 3)
        self.assertFalse(exhausted["c"].retry.succeeded)
        self.assertEqual(exhausted["c"].retry.failures, 2)
        print("  PASS: Exhausted retry metadata generated correctly")


class TestRecoveryStatePersistence(unittest.TestCase):
    """(d) Verify recovery state survives across passes."""

    def test_reprompt_state_round_trip(self):
        """Reprompt-phase state should survive save/load."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = [_make_result("x", content="bad", success=False)]
            serialized = BatchRetryService.serialize_results(results)

            state = RecoveryState(
                phase="reprompt",
                reprompt_attempt=1,
                reprompt_max_attempts=3,
                validation_name="check_schema",
                reprompt_attempts_per_record={"x": 1},
                validation_status={"x": False},
                on_exhausted="raise",
                accumulated_results=serialized,
            )

            RecoveryStateManager.save(tmp_dir, "test.jsonl", state)
            loaded = RecoveryStateManager.load(tmp_dir, "test.jsonl")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.phase, "reprompt")
            self.assertEqual(loaded.reprompt_attempt, 1)
            self.assertEqual(loaded.reprompt_max_attempts, 3)
            self.assertEqual(loaded.validation_name, "check_schema")
            self.assertEqual(loaded.on_exhausted, "raise")
            self.assertEqual(loaded.reprompt_attempts_per_record, {"x": 1})

            # Deserialize accumulated results
            deserialized = BatchRetryService.deserialize_results(loaded.accumulated_results)
            self.assertEqual(len(deserialized), 1)
            self.assertEqual(deserialized[0].custom_id, "x")
            self.assertFalse(deserialized[0].success)

            print("  PASS: Reprompt state persists across passes")

    def test_recovery_metadata_serialization(self):
        """BatchResult with recovery_metadata survives serialize/deserialize."""
        result = _make_result("a")
        result.recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="missing")
        )

        serialized = BatchRetryService.serialize_results([result])
        deserialized = BatchRetryService.deserialize_results(serialized)

        self.assertEqual(len(deserialized), 1)
        r = deserialized[0]
        self.assertIsNotNone(r.recovery_metadata)
        self.assertEqual(r.recovery_metadata.retry.attempts, 2)
        self.assertTrue(r.recovery_metadata.retry.succeeded)
        self.assertEqual(r.recovery_metadata.retry.reason, "missing")
        print("  PASS: Recovery metadata survives serialization round-trip")


class TestRegistrySkipsRecoveryEntries(unittest.TestCase):
    """(e) process_all_batch_results skips entries with parent_file_name."""

    def test_recovery_entries_skipped_in_processing(self):
        """Entries with parent_file_name should be skipped (processed via parent)."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        # Original entry (should be processed)
        original = MagicMock()
        original.batch_id = "batch-1"
        original.parent_file_name = None
        original.recovery_type = None
        original.record_count = 1

        # Recovery entry (should be skipped)
        recovery = MagicMock()
        recovery.batch_id = "batch-2"
        recovery.parent_file_name = "original.jsonl"
        recovery.recovery_type = "retry"
        recovery.recovery_attempt = 1

        stats = MagicMock()
        stats.in_progress = 0

        manager = MagicMock()
        manager.get_all_jobs.return_value = {
            "original.jsonl": original,
            "original.jsonl_retry_1": recovery,
        }
        manager.get_registry_stats.return_value = stats

        # Provider returns completed
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        result1 = MagicMock()
        result1.custom_id = "r1"
        result1.content = "ok"
        result1.success = True
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        result_processor = MagicMock()
        result_processor.process.return_value = [{"id": "1", "result": "done"}]

        mock_storage = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=result_processor,
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="test",
        )

        result = service.process_all_batch_results("/tmp/test")

        # Only original should be processed (1 file)
        self.assertEqual(len(result), 1)
        # Provider should only be called for original, not recovery
        self.assertEqual(provider.check_status.call_count, 1)
        print("  PASS: Recovery entries skipped in process_all_batch_results")


class TestBatchJobEntryRecoveryFields(unittest.TestCase):
    """Verify BatchJobEntry recovery fields work end-to-end."""

    def test_backward_compatible_deserialization(self):
        """Old registries without recovery fields should load fine."""
        old_data = {
            "batch_id": "b-1",
            "status": "completed",
            "timestamp": "2024-01-01",
            "provider": "openai",
            "record_count": 10,
        }
        entry = BatchJobEntry.from_dict(old_data)
        self.assertIsNone(entry.parent_file_name)
        self.assertIsNone(entry.recovery_type)
        self.assertIsNone(entry.recovery_attempt)
        print("  PASS: Old registry entries load without recovery fields")

    def test_recovery_entry_round_trip(self):
        """Recovery entry should survive to_dict/from_dict."""
        entry = BatchJobEntry(
            batch_id="retry-1",
            status="submitted",
            timestamp="2024-01-01",
            provider="openai",
            parent_file_name="original.jsonl",
            recovery_type="retry",
            recovery_attempt=2,
        )
        d = entry.to_dict()
        restored = BatchJobEntry.from_dict(d)
        self.assertEqual(restored.parent_file_name, "original.jsonl")
        self.assertEqual(restored.recovery_type, "retry")
        self.assertEqual(restored.recovery_attempt, 2)
        print("  PASS: Recovery entry survives to_dict/from_dict round-trip")


class TestProcessRetryResultsMerge(unittest.TestCase):
    """Verify process_retry_results correctly tracks missing IDs."""

    def test_failed_results_do_not_reduce_missing(self):
        """REGRESSION: Failed results must NOT remove IDs from missing_ids."""
        service = BatchRetryService()
        accumulated = [_make_result("a")]
        retry_results = [_make_result("b", success=False)]

        merged, still_missing, counts, _ = service.process_retry_results(
            results=retry_results,
            accumulated_results=accumulated,
            context_map={"a": {}, "b": {}},
            record_failure_counts={"b": 1},
            missing_ids={"b"},
        )

        self.assertIn("b", still_missing)
        self.assertEqual(counts["b"], 2)
        print("  PASS: Failed retry results keep IDs in missing_ids (regression)")

    def test_successful_results_reduce_missing(self):
        """Successful results should remove IDs from missing_ids."""
        service = BatchRetryService()
        accumulated = [_make_result("a")]
        retry_results = [_make_result("b")]

        merged, still_missing, counts, _ = service.process_retry_results(
            results=retry_results,
            accumulated_results=accumulated,
            context_map={"a": {}, "b": {}},
            record_failure_counts={"b": 1},
            missing_ids={"b"},
        )

        self.assertNotIn("b", still_missing)
        self.assertEqual(len(merged), 2)
        print("  PASS: Successful retry results reduce missing_ids")


if __name__ == "__main__":
    print("\n=== Async Batch Recovery (#942) — Manual Verification ===\n")
    unittest.main(verbosity=2)
