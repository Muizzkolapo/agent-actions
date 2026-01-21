"""
Unit tests for recovery statistics calculation.

Tests the recovery_stats module for calculating and formatting
recovery metadata statistics.
"""

import pytest
from agent_actions.processing.recovery.stats import (
    RecoveryStats,
    calculate_recovery_stats_from_results,
    calculate_recovery_stats_from_output_data,
    add_recovery_stats_to_manifest,
    add_recovery_stats_to_agent_status,
)
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata, RepromptMetadata


class TestRecoveryStats:
    """Tests for RecoveryStats dataclass."""

    def test_default_values(self):
        """RecoveryStats should initialize with zero counts."""
        stats = RecoveryStats()
        assert stats.retry_count == 0
        assert stats.reprompt_count == 0
        assert stats.retry_succeeded == 0
        assert stats.reprompt_succeeded == 0
        assert stats.retry_exhausted == 0
        assert stats.reprompt_exhausted == 0

    def test_to_dict(self):
        """to_dict should convert all fields to dictionary."""
        stats = RecoveryStats(
            retry_count=5,
            reprompt_count=3,
            retry_succeeded=4,
            reprompt_succeeded=2,
            retry_exhausted=1,
            reprompt_exhausted=1,
        )

        result = stats.to_dict()

        assert result == {
            "retry_count": 5,
            "reprompt_count": 3,
            "retry_succeeded": 4,
            "reprompt_succeeded": 2,
            "retry_exhausted": 1,
            "reprompt_exhausted": 1,
        }

    def test_to_summary_dict(self):
        """to_summary_dict should return only counts (for manifest)."""
        stats = RecoveryStats(
            retry_count=5,
            reprompt_count=3,
            retry_succeeded=4,
            reprompt_succeeded=2,
            retry_exhausted=1,
            reprompt_exhausted=1,
        )

        result = stats.to_summary_dict()

        assert result == {
            "retry_count": 5,
            "reprompt_count": 3,
        }


class TestCalculateRecoveryStatsFromResults:
    """Tests for calculate_recovery_stats_from_results."""

    def test_empty_results(self):
        """Should return zero stats for empty list."""
        stats = calculate_recovery_stats_from_results([])
        assert stats.retry_count == 0
        assert stats.reprompt_count == 0

    def test_results_without_recovery_metadata(self):
        """Should return zero stats when no recovery metadata present."""

        class MockResult:
            recovery_metadata = None

        results = [MockResult(), MockResult()]
        stats = calculate_recovery_stats_from_results(results)

        assert stats.retry_count == 0
        assert stats.reprompt_count == 0

    def test_retry_only_succeeded(self):
        """Should count retry successes correctly."""

        class MockResult:
            def __init__(self, recovery):
                self.recovery_metadata = recovery

        results = [
            MockResult(
                RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=2,
                        failures=1,
                        succeeded=True,
                        reason="timeout",
                        timestamp="2024-01-13T12:00:00Z",
                    )
                )
            ),
            MockResult(
                RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=3,
                        failures=2,
                        succeeded=True,
                        reason="missing",
                        timestamp="2024-01-13T12:01:00Z",
                    )
                )
            ),
        ]

        stats = calculate_recovery_stats_from_results(results)

        assert stats.retry_count == 2
        assert stats.retry_succeeded == 2
        assert stats.retry_exhausted == 0
        assert stats.reprompt_count == 0

    def test_retry_exhausted(self):
        """Should count retry exhaustion correctly."""

        class MockResult:
            def __init__(self, recovery):
                self.recovery_metadata = recovery

        results = [
            MockResult(
                RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=3,
                        failures=3,
                        succeeded=False,
                        reason="timeout",
                        timestamp="2024-01-13T12:00:00Z",
                    )
                )
            )
        ]

        stats = calculate_recovery_stats_from_results(results)

        assert stats.retry_count == 1
        assert stats.retry_succeeded == 0
        assert stats.retry_exhausted == 1

    def test_reprompt_only_passed(self):
        """Should count reprompt passes correctly."""

        class MockResult:
            def __init__(self, recovery):
                self.recovery_metadata = recovery

        results = [
            MockResult(
                RecoveryMetadata(
                    reprompt=RepromptMetadata(attempts=2, passed=True, validation="check_fields")
                )
            ),
            MockResult(
                RecoveryMetadata(
                    reprompt=RepromptMetadata(attempts=1, passed=True, validation="check_format")
                )
            ),
        ]

        stats = calculate_recovery_stats_from_results(results)

        assert stats.reprompt_count == 2
        assert stats.reprompt_succeeded == 2
        assert stats.reprompt_exhausted == 0
        assert stats.retry_count == 0

    def test_reprompt_exhausted(self):
        """Should count reprompt exhaustion correctly."""

        class MockResult:
            def __init__(self, recovery):
                self.recovery_metadata = recovery

        results = [
            MockResult(
                RecoveryMetadata(
                    reprompt=RepromptMetadata(attempts=2, passed=False, validation="check_fields")
                )
            )
        ]

        stats = calculate_recovery_stats_from_results(results)

        assert stats.reprompt_count == 1
        assert stats.reprompt_succeeded == 0
        assert stats.reprompt_exhausted == 1

    def test_both_retry_and_reprompt(self):
        """Should count both retry and reprompt correctly."""

        class MockResult:
            def __init__(self, recovery):
                self.recovery_metadata = recovery

        results = [
            # Retry succeeded, reprompt passed
            MockResult(
                RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=2,
                        failures=1,
                        succeeded=True,
                        reason="timeout",
                        timestamp="2024-01-13T12:00:00Z",
                    ),
                    reprompt=RepromptMetadata(attempts=2, passed=True, validation="check_fields"),
                )
            ),
            # Only reprompt
            MockResult(
                RecoveryMetadata(
                    reprompt=RepromptMetadata(attempts=1, passed=True, validation="check_format")
                )
            ),
            # Only retry
            MockResult(
                RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=3,
                        failures=2,
                        succeeded=True,
                        reason="missing",
                        timestamp="2024-01-13T12:01:00Z",
                    )
                )
            ),
        ]

        stats = calculate_recovery_stats_from_results(results)

        assert stats.retry_count == 2
        assert stats.retry_succeeded == 2
        assert stats.reprompt_count == 2
        assert stats.reprompt_succeeded == 2


class TestCalculateRecoveryStatsFromOutputData:
    """Tests for calculate_recovery_stats_from_output_data."""

    def test_empty_data(self):
        """Should return zero stats for empty list."""
        stats = calculate_recovery_stats_from_output_data([])
        assert stats.retry_count == 0
        assert stats.reprompt_count == 0

    def test_records_without_recovery(self):
        """Should return zero stats when no _recovery field."""
        data = [{"content": {"title": "Test"}}, {"content": {"title": "Test 2"}}]

        stats = calculate_recovery_stats_from_output_data(data)

        assert stats.retry_count == 0
        assert stats.reprompt_count == 0

    def test_retry_from_json(self):
        """Should parse retry metadata from JSON."""
        data = [
            {
                "content": {"title": "Test"},
                "_recovery": {
                    "retry": {
                        "attempts": 2,
                        "failures": 1,
                        "succeeded": True,
                        "reason": "timeout",
                        "timestamp": "2024-01-13T12:00:00Z",
                    }
                },
            },
            {
                "content": {"title": "Test 2"},
                "_recovery": {
                    "retry": {"attempts": 3, "failures": 3, "succeeded": False, "reason": "missing"}
                },
            },
        ]

        stats = calculate_recovery_stats_from_output_data(data)

        assert stats.retry_count == 2
        assert stats.retry_succeeded == 1
        assert stats.retry_exhausted == 1

    def test_reprompt_from_json(self):
        """Should parse reprompt metadata from JSON."""
        data = [
            {
                "content": {"title": "Test"},
                "_recovery": {
                    "reprompt": {"attempts": 2, "passed": True, "validation": "check_fields"}
                },
            },
            {
                "content": {"title": "Test 2"},
                "_recovery": {
                    "reprompt": {"attempts": 2, "passed": False, "validation": "check_format"}
                },
            },
        ]

        stats = calculate_recovery_stats_from_output_data(data)

        assert stats.reprompt_count == 2
        assert stats.reprompt_succeeded == 1
        assert stats.reprompt_exhausted == 1

    def test_both_retry_and_reprompt_from_json(self):
        """Should parse both retry and reprompt from JSON."""
        data = [
            {
                "content": {"title": "Test"},
                "_recovery": {
                    "retry": {"attempts": 2, "failures": 1, "succeeded": True, "reason": "timeout"},
                    "reprompt": {"attempts": 2, "passed": True, "validation": "check_fields"},
                },
            }
        ]

        stats = calculate_recovery_stats_from_output_data(data)

        assert stats.retry_count == 1
        assert stats.retry_succeeded == 1
        assert stats.reprompt_count == 1
        assert stats.reprompt_succeeded == 1


class TestAddRecoveryStatsToManifest:
    """Tests for add_recovery_stats_to_manifest."""

    def test_add_to_empty_manifest(self):
        """Should create manifest structure if not present."""
        manifest = {}
        stats = RecoveryStats(retry_count=1, reprompt_count=2)

        add_recovery_stats_to_manifest(manifest, "classify_genre", stats)

        assert manifest == {
            "actions": {
                "classify_genre": {"recovery_stats": {"retry_count": 1, "reprompt_count": 2}}
            }
        }

    def test_add_to_existing_action(self):
        """Should add recovery_stats to existing action."""
        manifest = {"actions": {"classify_genre": {"status": "completed", "record_count": 10}}}

        stats = RecoveryStats(retry_count=1, reprompt_count=2)

        add_recovery_stats_to_manifest(manifest, "classify_genre", stats)

        assert manifest["actions"]["classify_genre"]["recovery_stats"] == {
            "retry_count": 1,
            "reprompt_count": 2,
        }
        assert manifest["actions"]["classify_genre"]["status"] == "completed"

    def test_overwrite_existing_recovery_stats(self):
        """Should overwrite existing recovery_stats."""
        manifest = {
            "actions": {
                "classify_genre": {"recovery_stats": {"retry_count": 0, "reprompt_count": 0}}
            }
        }

        stats = RecoveryStats(retry_count=5, reprompt_count=3)

        add_recovery_stats_to_manifest(manifest, "classify_genre", stats)

        assert manifest["actions"]["classify_genre"]["recovery_stats"] == {
            "retry_count": 5,
            "reprompt_count": 3,
        }


class TestAddRecoveryStatsToAgentStatus:
    """Tests for add_recovery_stats_to_agent_status."""

    def test_add_to_empty_status(self):
        """Should create status structure if not present."""
        status = {}
        stats = RecoveryStats(retry_count=1, reprompt_count=2)

        add_recovery_stats_to_agent_status(status, "classify_genre", stats)

        assert status == {
            "classify_genre": {"recovery": {"retried": 1, "reprompted": 2, "failed": 0}}
        }

    def test_add_to_existing_action(self):
        """Should add recovery to existing action."""
        status = {"classify_genre": {"status": "completed"}}

        stats = RecoveryStats(retry_count=1, reprompt_count=2)

        add_recovery_stats_to_agent_status(status, "classify_genre", stats)

        assert status["classify_genre"]["recovery"] == {"retried": 1, "reprompted": 2, "failed": 0}
        assert status["classify_genre"]["status"] == "completed"

    def test_calculate_failed_count(self):
        """Should calculate failed count from exhausted records."""
        status = {}
        stats = RecoveryStats(
            retry_count=5,
            reprompt_count=3,
            retry_succeeded=3,
            reprompt_succeeded=2,
            retry_exhausted=2,
            reprompt_exhausted=1,
        )

        add_recovery_stats_to_agent_status(status, "classify_genre", stats)

        # Failed = retry_exhausted + reprompt_exhausted
        assert status["classify_genre"]["recovery"]["failed"] == 3

    def test_overwrite_existing_recovery(self):
        """Should overwrite existing recovery info."""
        status = {"classify_genre": {"recovery": {"retried": 0, "reprompted": 0, "failed": 0}}}

        stats = RecoveryStats(retry_count=5, reprompt_count=3)

        add_recovery_stats_to_agent_status(status, "classify_genre", stats)

        assert status["classify_genre"]["recovery"] == {"retried": 5, "reprompted": 3, "failed": 0}
