"""Tests for BatchRetryService and shared.retrieve_and_reconcile.

Covers:
- retrieve_and_reconcile delegates to provider and logs reconciliation
- retrieve_results_with_retry filters failed results from missing_ids
- retrieve_results_with_retry returns exhausted_recovery for still-missing records
- _resubmit_missing_records returns [] on failure (no crash)
"""

import pytest
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
