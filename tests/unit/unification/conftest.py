"""Shared fixtures for batch/online unification tests.

Provides reusable fixtures for testing both batch and online processing paths,
guard evaluation, and paired-mode execution for parity verification.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


@pytest.fixture
def sample_record() -> dict[str, Any]:
    """Standard record used across unification tests."""
    return {
        "target_id": "test-001",
        "source_guid": "sg-001",
        "content": {"text": "sample content", "upstream_ns": {"status": "ready"}},
    }


@pytest.fixture
def sample_records() -> list[dict[str, Any]]:
    """Multiple records for batch/list processing tests."""
    return [
        {
            "target_id": "test-001",
            "source_guid": "sg-001",
            "content": {"text": "record 1", "upstream_ns": {"status": "ready"}},
        },
        {
            "target_id": "test-002",
            "source_guid": "sg-002",
            "content": {"text": "record 2", "upstream_ns": {"status": "pending"}},
        },
        {
            "target_id": "test-003",
            "source_guid": "sg-003",
            "content": {"text": "record 3", "upstream_ns": {"status": "ready"}},
        },
    ]


@pytest.fixture
def batch_preparator() -> BatchTaskPreparator:
    """BatchTaskPreparator wired with default empty config."""
    return BatchTaskPreparator(
        action_indices={},
        dependency_configs={},
        storage_backend=None,
        version_context=None,
    )


@pytest.fixture
def guard_config_skip() -> dict[str, Any]:
    """Guard config with skip behavior."""
    return {
        "clause": "upstream_ns.status == 'ready'",
        "behavior": "skip",
    }


@pytest.fixture
def guard_config_filter() -> dict[str, Any]:
    """Guard config with filter behavior."""
    return {
        "clause": "upstream_ns.status == 'ready'",
        "behavior": "filter",
    }


@pytest.fixture
def agent_config_with_guard(guard_config_skip: dict[str, Any]) -> dict[str, Any]:
    """Agent config with guard enabled."""
    return {
        "name": "test_action",
        "prompt": "Process: {{ content }}",
        "guard": guard_config_skip,
    }


@pytest.fixture
def agent_config_no_guard() -> dict[str, Any]:
    """Agent config without guard."""
    return {
        "name": "test_action",
        "prompt": "Process: {{ content }}",
    }


@pytest.fixture
def paired_execution():
    """Run same payload through both online prefilter and batch prepare paths.

    Returns a function that accepts records and guard config, runs both paths,
    and returns (online_decisions, batch_decisions) as lists of decision strings
    for comparison.

    Both paths use a deterministic mock evaluator (hardcoded to check
    upstream_ns.status). This verifies the fixture plumbing works and that
    both paths exercise guard dispatch logic. It does NOT test real guard
    evaluation parity — that requires real evaluator integration tests.
    """

    def _run(
        records: list[dict[str, Any]],
        guard_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[str]]:
        if not guard_config:
            # No guard — both paths pass everything
            return (
                ["passed"] * len(records),
                ["passed"] * len(records),
            )

        agent_config = {"name": "test_action", "guard": guard_config}

        # --- Online path: prefilter_by_guard ---
        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator"
        ) as mock_eval:
            mock_evaluator = MagicMock()
            online_decisions: list[str] = []

            def online_evaluate(*, item, guard_config, context=None, **kwargs):
                result = MagicMock()
                # item is get_existing_content(record) — the record's own
                # namespaces. upstream_ns is a dependency namespace, not
                # source content, so it lives here, never under context["source"].
                is_ready = False
                if isinstance(item, dict):
                    ns = item.get("upstream_ns")
                    if isinstance(ns, dict):
                        is_ready = ns.get("status") == "ready"
                result.should_execute = is_ready
                online_decisions.append("passed" if result.should_execute else "skipped")
                return result

            mock_evaluator.evaluate.side_effect = online_evaluate
            mock_eval.return_value = mock_evaluator

            prefilter_by_guard(records, agent_config, "test_action")

        # --- Batch path: TaskPreparer.prepare with skip_guard=False ---
        batch_decisions: list[str] = []
        preparator = BatchTaskPreparator(
            action_indices={},
            dependency_configs={},
        )

        mock_preparer = MagicMock()

        def batch_prepare(row, ctx, **kwargs):
            content = row.get("content", {})
            is_ready = content.get("upstream_ns", {}).get("status") == "ready"
            result = MagicMock()
            if is_ready:
                result.guard_status = GuardStatus.PASSED
                batch_decisions.append("passed")
            else:
                result.guard_status = GuardStatus.SKIPPED
                batch_decisions.append("skipped")
            result.passthrough_fields = {}
            return result

        mock_preparer.prepare.side_effect = batch_prepare

        context_map: dict[str, Any] = {}
        stats = BatchTaskPreparationStats()
        prep_context = MagicMock(spec=PreparationContext)

        for row in records:
            preparator._process_single_item(row, prep_context, mock_preparer, context_map, stats)

        return online_decisions, batch_decisions

    return _run
