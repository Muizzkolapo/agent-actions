"""Tests for BatchRetryService and shared.retrieve_and_reconcile.

Covers:
- retrieve_and_reconcile delegates to provider and logs reconciliation
- retrieve_results_with_retry filters failed results from missing_ids
- retrieve_results_with_retry returns exhausted_recovery for still-missing records
- _resubmit_missing_records returns [] on failure (no crash)
- Non-blocking async methods: submit_retry_batch, process_retry_results,
  serialize/deserialize_results
- validate_and_reprompt passed flag reflects post-reprompt validation state
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# shared.retrieve_and_reconcile
# ---------------------------------------------------------------------------


class TestRetrieveAndReconcile:
    """Tests for the shared retrieve_and_reconcile function."""

    def test_delegates_to_provider_and_returns_results(self):
        """Should call provider.retrieve_results and return the results."""
        from agent_actions.llm.batch.services.shared import retrieve_and_reconcile

        result_a = BatchResult(custom_id="a", content="ok", success=True)
        provider = MagicMock()
        provider.retrieve_results.return_value = [result_a]

        results = retrieve_and_reconcile(
            provider, "batch-123", "/tmp/out", context_map={"a": {"target_id": "a"}}
        )

        provider.retrieve_results.assert_called_once_with("batch-123", "/tmp/out")
        assert results == [result_a]

    def test_works_without_context_map(self):
        """Should handle None context_map gracefully."""
        from agent_actions.llm.batch.services.shared import retrieve_and_reconcile

        provider = MagicMock()
        provider.retrieve_results.return_value = []

        results = retrieve_and_reconcile(provider, "batch-123", None)
        assert results == []


# ---------------------------------------------------------------------------
# BatchRetryService.retrieve_results_with_retry
# ---------------------------------------------------------------------------


class TestRetrieveResultsWithRetry:
    """Tests for retry logic in BatchRetryService."""

    def _make_result(self, custom_id: str, success: bool = True) -> BatchResult:
        return BatchResult(
            custom_id=custom_id,
            content="ok" if success else "error",
            success=success,
        )

    def test_no_retry_when_disabled(self):
        """Should skip retry loop when retry is not enabled."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()
        result_a = self._make_result("a")

        with patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile"
        ) as mock_retrieve:
            mock_retrieve.return_value = [result_a]

            results, exhausted = service.retrieve_results_with_retry(
                provider,
                "batch-1",
                "/tmp/out",
                context_map={"a": {"target_id": "a"}},
                agent_config={"retry": None},
            )

        assert len(results) == 1
        assert exhausted is None

    def test_no_retry_when_all_received(self):
        """Should skip retry when all expected records are received."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()
        result_a = self._make_result("a")
        result_b = self._make_result("b")

        with patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile"
        ) as mock_retrieve:
            mock_retrieve.return_value = [result_a, result_b]

            results, exhausted = service.retrieve_results_with_retry(
                provider,
                "batch-1",
                "/tmp/out",
                context_map={
                    "a": {"target_id": "a"},
                    "b": {"target_id": "b"},
                },
                agent_config={"retry": {"enabled": True, "max_attempts": 2}},
            )

        assert len(results) == 2
        assert exhausted is None

    def test_failed_retry_results_stay_in_missing_ids(self):
        """REGRESSION: Failed retry results must NOT remove IDs from missing_ids.

        This was the blocking bug: collect_result_custom_ids didn't filter
        by success, so failed retries permanently removed IDs from missing_ids.
        """
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        # Initial retrieval returns nothing for "b"
        initial_results = [self._make_result("a")]
        # First retry returns "b" but it failed
        retry_1_results = [self._make_result("b", success=False)]
        # Second retry returns "b" successfully
        retry_2_results = [self._make_result("b", success=True)]

        call_count = {"resubmit": 0}

        def mock_resubmit(*args, **kwargs):
            call_count["resubmit"] += 1
            if call_count["resubmit"] == 1:
                return retry_1_results
            return retry_2_results

        with patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile"
        ) as mock_retrieve:
            mock_retrieve.return_value = initial_results

            service._resubmit_missing_records = MagicMock(side_effect=mock_resubmit)

            results, exhausted = service.retrieve_results_with_retry(
                provider,
                "batch-1",
                "/tmp/out",
                context_map={
                    "a": {"target_id": "a"},
                    "b": {"target_id": "b"},
                },
                agent_config={"retry": {"enabled": True, "max_attempts": 2}},
            )

        # "b" failed on attempt 1, so it should have been retried on attempt 2
        assert service._resubmit_missing_records.call_count == 2
        # The final results include: initial(a) + retry1(b_fail) + retry2(b_success)
        assert len(results) == 3
        # Verify "b" eventually succeeded
        successful_b = [r for r in results if r.custom_id == "b" and r.success]
        assert len(successful_b) == 1

    def test_exhausted_recovery_metadata_for_missing_records(self):
        """Should produce exhausted_recovery metadata for records that never succeed."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        # Only "a" is returned, "b" is always missing
        initial_results = [self._make_result("a")]

        with patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile"
        ) as mock_retrieve:
            mock_retrieve.return_value = initial_results

            # Resubmit always returns empty (b never comes back)
            service._resubmit_missing_records = MagicMock(return_value=[])

            results, exhausted = service.retrieve_results_with_retry(
                provider,
                "batch-1",
                "/tmp/out",
                context_map={
                    "a": {"target_id": "a"},
                    "b": {"target_id": "b"},
                },
                agent_config={"retry": {"enabled": True, "max_attempts": 1}},
            )

        # exhausted should have metadata for "b"
        assert exhausted is not None
        assert "b" in exhausted
        assert exhausted["b"].retry.succeeded is False
        assert exhausted["b"].retry.failures >= 1


class TestResubmitMissingRecords:
    """Tests for _resubmit_missing_records error handling."""

    def test_returns_empty_on_exception(self):
        """Should return [] and log warning when resubmission fails."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        # Make prepare_tasks raise via patching at the source module
        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep_cls.side_effect = RuntimeError("prep failed")

            result = service._resubmit_missing_records(
                provider=provider,
                missing_ids={"a"},
                context_map={"a": {"target_id": "a"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config={},
            )

        assert result == []

    def test_returns_empty_when_no_records_in_context_map(self):
        """Should return [] when missing IDs are not in context_map."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        result = service._resubmit_missing_records(
            provider=provider,
            missing_ids={"missing_id"},
            context_map={},
            output_directory="/tmp/out",
            file_name="test",
            agent_config={},
        )

        assert result == []


# ---------------------------------------------------------------------------
# BatchJobEntry.__post_init__ validation (warning, not error)
# ---------------------------------------------------------------------------


class TestBatchJobEntryValidation:
    """Tests for BatchJobEntry status validation."""

    def test_valid_status_accepted(self):
        """Should accept valid BatchStatus values without warning."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry

        entry = BatchJobEntry(
            batch_id="b-1",
            status="completed",
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
        )
        assert entry.status == "completed"

    def test_unknown_status_warns_but_does_not_raise(self):
        """Should log warning for unknown status, not raise ValueError.

        This ensures existing registries with provider-specific statuses
        can still be deserialized.
        """
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry

        # Should NOT raise — just logs a warning
        entry = BatchJobEntry(
            batch_id="b-1",
            status="provider_specific_status",
            timestamp="2024-01-01T00:00:00Z",
            provider="custom",
        )
        assert entry.status == "provider_specific_status"


# ---------------------------------------------------------------------------
# Non-blocking async methods (#942)
# ---------------------------------------------------------------------------


class TestSubmitRetryBatch:
    """Tests for submit_retry_batch (non-blocking)."""

    def test_returns_batch_id_and_count(self):
        """Should return (batch_id, record_count) on successful submission."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()
        provider.submit_batch.return_value = ("retry-batch-1", "submitted")

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "task"}])
            mock_prep_cls.return_value = mock_prep

            result = service.submit_retry_batch(
                provider=provider,
                missing_ids={"a"},
                context_map={"a": {"target_id": "a"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config={},
            )

        assert result == ("retry-batch-1", 1)

    def test_returns_none_when_no_records_in_context_map(self):
        """Should return None when missing IDs not in context_map."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        result = service.submit_retry_batch(
            provider=provider,
            missing_ids={"missing"},
            context_map={},
            output_directory="/tmp/out",
            file_name="test",
            agent_config={},
        )

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None when submission fails."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep_cls.side_effect = RuntimeError("prep failed")

            result = service.submit_retry_batch(
                provider=provider,
                missing_ids={"a"},
                context_map={"a": {"target_id": "a"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config={},
            )

        assert result is None


class TestProcessRetryResults:
    """Tests for process_retry_results."""

    def _make_result(self, custom_id, success=True):
        return BatchResult(
            custom_id=custom_id,
            content="ok" if success else "error",
            success=success,
        )

    def test_merges_successful_results_and_reduces_missing(self):
        """Should merge results and remove successful IDs from missing."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()

        accumulated = [self._make_result("a")]
        retry_results = [self._make_result("b")]

        merged, still_missing, counts, exhausted = service.process_retry_results(
            results=retry_results,
            accumulated_results=accumulated,
            context_map={"a": {}, "b": {}},
            record_failure_counts={"b": 1},
            missing_ids={"b"},
        )

        assert len(merged) == 2
        assert still_missing == set()
        assert exhausted is None

    def test_failed_results_stay_in_missing(self):
        """Failed retry results should NOT reduce missing_ids."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()

        accumulated = [self._make_result("a")]
        retry_results = [self._make_result("b", success=False)]

        merged, still_missing, counts, _ = service.process_retry_results(
            results=retry_results,
            accumulated_results=accumulated,
            context_map={"a": {}, "b": {}},
            record_failure_counts={"b": 1},
            missing_ids={"b"},
        )

        assert "b" in still_missing
        assert counts["b"] == 2  # incremented


class TestSerializeDeserializeResults:
    """Tests for serialize_results / deserialize_results round-trip."""

    def test_round_trip(self):
        """Should serialize and deserialize back to equivalent BatchResults."""
        from agent_actions.llm.batch.services.retry import BatchRetryService
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        result = BatchResult(custom_id="a", content="hello", success=True)
        result.recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="missing")
        )

        serialized = BatchRetryService.serialize_results([result])
        deserialized = BatchRetryService.deserialize_results(serialized)

        assert len(deserialized) == 1
        r = deserialized[0]
        assert r.custom_id == "a"
        assert r.content == "hello"
        assert r.success is True
        assert r.recovery_metadata is not None
        assert r.recovery_metadata.retry.attempts == 2
        assert r.recovery_metadata.retry.succeeded is True

    def test_round_trip_without_recovery_metadata(self):
        """Should handle results without recovery metadata."""
        from agent_actions.llm.batch.services.retry import BatchRetryService

        result = BatchResult(custom_id="b", content="world", success=False)

        serialized = BatchRetryService.serialize_results([result])
        deserialized = BatchRetryService.deserialize_results(serialized)

        assert len(deserialized) == 1
        assert deserialized[0].recovery_metadata is None


# ---------------------------------------------------------------------------
# BatchRetryService.validate_and_reprompt — post-reprompt validation
# ---------------------------------------------------------------------------


class TestValidateAndRepromptPassedFlag:
    """Regression test: RepromptMetadata.passed must reflect post-reprompt state.

    Before the fix, validation_status was populated only during the reprompt loop
    and never refreshed after reprompt results were merged. So .passed was always
    False even when the reprompted result actually passed validation.
    """

    def test_passed_reflects_post_reprompt_validation(self):
        """REGRESSION: .passed should be True when reprompted result passes validation."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        # Initial result fails validation (content="bad")
        initial_result = BatchResult(custom_id="a", content="bad", success=True)

        # After reprompt, provider returns a good result
        reprompted_result = BatchResult(custom_id="a", content="good", success=True)
        provider.submit_batch.return_value = ("reprompt-batch-1", "submitted")
        provider.retrieve_results.return_value = [reprompted_result]

        # Validation: "good" passes, anything else fails
        def validation_func(content):
            return content == "good"

        agent_config = {
            "reprompt": {
                "validation": "test_validator",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            }
        }

        with (
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(validation_func, "Please fix your response."),
            ),
            patch(
                "agent_actions.llm.batch.services.retry._import_validation_module",
            ),
            patch(
                "agent_actions.llm.batch.services.retry.wait_for_batch_completion",
                return_value=BatchStatus.COMPLETED,
            ),
            patch(
                "agent_actions.processing.recovery.response_validator.build_validation_feedback",
                return_value="Feedback: Please fix.",
            ),
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
            ) as mock_prep_cls,
        ):
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "task"}])
            mock_prep_cls.return_value = mock_prep

            results = service.validate_and_reprompt(
                results=[initial_result],
                provider=provider,
                context_map={"a": {"target_id": "a", "user_content": "original"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config=agent_config,
            )

        # Find the result for "a"
        result_a = next(r for r in results if r.custom_id == "a")

        # The key assertion: .passed must be True because reprompted content is "good"
        assert result_a.recovery_metadata is not None
        assert result_a.recovery_metadata.reprompt is not None
        assert result_a.recovery_metadata.reprompt.passed is True
        assert result_a.recovery_metadata.reprompt.validation == "test_validator"

    def test_passed_is_false_when_reprompt_still_fails(self):
        """Passed should be False when reprompted result still fails validation.

        Uses max_attempts=2 so the reprompt is actually submitted on attempt 1,
        and the still-bad result is re-validated on attempt 2 (exhaustion).
        """
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.retry import BatchRetryService

        service = BatchRetryService()
        provider = MagicMock()

        initial_result = BatchResult(custom_id="a", content="bad", success=True)

        # Reprompt also returns bad content
        reprompted_result = BatchResult(custom_id="a", content="still_bad", success=True)
        provider.submit_batch.return_value = ("reprompt-batch-1", "submitted")
        provider.retrieve_results.return_value = [reprompted_result]

        def validation_func(content):
            return content == "good"

        agent_config = {
            "reprompt": {
                "validation": "test_validator",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            }
        }

        with (
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(validation_func, "Please fix."),
            ),
            patch(
                "agent_actions.llm.batch.services.retry._import_validation_module",
            ),
            patch(
                "agent_actions.llm.batch.services.retry.wait_for_batch_completion",
                return_value=BatchStatus.COMPLETED,
            ),
            patch(
                "agent_actions.processing.recovery.response_validator.build_validation_feedback",
                return_value="Feedback: Please fix.",
            ),
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
            ) as mock_prep_cls,
        ):
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "task"}])
            mock_prep_cls.return_value = mock_prep

            results = service.validate_and_reprompt(
                results=[initial_result],
                provider=provider,
                context_map={"a": {"target_id": "a", "user_content": "original"}},
                output_directory="/tmp/out",
                file_name="test",
                agent_config=agent_config,
            )

        # Verify the reprompt path was actually exercised
        provider.submit_batch.assert_called_once()
        provider.retrieve_results.assert_called_once()

        result_a = next(r for r in results if r.custom_id == "a")

        assert result_a.recovery_metadata is not None
        assert result_a.recovery_metadata.reprompt is not None
        assert result_a.recovery_metadata.reprompt.passed is False


class TestBatchJobEntryRecoveryFields:
    """Tests for recovery fields on BatchJobEntry."""

    def test_recovery_fields_default_to_none(self):
        """Recovery fields should be None by default (backward compatible)."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry

        entry = BatchJobEntry(
            batch_id="b-1",
            status="completed",
            timestamp="2024-01-01",
            provider="openai",
        )
        assert entry.parent_file_name is None
        assert entry.recovery_type is None
        assert entry.recovery_attempt is None

    def test_recovery_fields_serialize_round_trip(self):
        """Recovery fields should survive to_dict/from_dict round-trip."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry

        entry = BatchJobEntry(
            batch_id="b-1",
            status="submitted",
            timestamp="2024-01-01",
            provider="openai",
            parent_file_name="original.json",
            recovery_type="retry",
            recovery_attempt=2,
        )

        d = entry.to_dict()
        restored = BatchJobEntry.from_dict(d)

        assert restored.parent_file_name == "original.json"
        assert restored.recovery_type == "retry"
        assert restored.recovery_attempt == 2
