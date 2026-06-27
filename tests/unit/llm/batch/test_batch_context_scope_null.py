"""Regression test for the in-file ``context_scope`` sibling of VIOL-0031.

``BatchResultStrategy._process_successful_result`` reads
``ctx.agent_config.get("context_scope", {}).get("passthrough")`` on the
``custom_id not in context_map`` branch. A bare YAML ``context_scope:``
parses to ``None`` and the inner ``.get`` crashed with
``AttributeError``. Same antipattern as VIOL-0031 with a different
config key, in the same file as the original fix — brought in scope
per quality-gate 5 (same-file sibling).
"""

from typing import Any

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult


def _make_ctx(
    agent_config: dict[str, Any],
    known_custom_id: str,
    original_row: dict[str, Any],
) -> BatchProcessingContext:
    """Build a context whose context_map intentionally omits the custom_id
    used at call time, forcing the elif branch that reads
    ``context_scope.get("passthrough")``."""
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={known_custom_id: original_row},
        output_directory=None,
        agent_config=agent_config,
        json_mode=False,
    )
    ctx.reconciler = BatchResultReconciler(context_map={known_custom_id: original_row})
    return ctx


def test_process_successful_result_tolerates_context_scope_explicitly_none():
    """When ``context_scope: None`` (bare YAML key) and the custom_id is
    NOT in context_map, the missing-passthrough warning branch must
    short-circuit cleanly instead of raising ``AttributeError``."""
    known_id = "rec_in_map"
    missing_id = "rec_not_in_map"
    original_row = {"source_guid": "src_001", "content": {}}
    agent_config = {"action_name": "my_action", "context_scope": None}
    ctx = _make_ctx(agent_config, known_id, original_row)
    # The reconciler must still return *something* for the missing id so
    # the function reaches the context_scope branch; reuse the known row.
    ctx.reconciler = BatchResultReconciler(
        context_map={known_id: original_row, missing_id: original_row}
    )
    # But the context_map dict on ctx omits the missing id, so the
    # `custom_id in ctx.context_map` test fails and falls through to
    # the elif branch under review.

    batch_result = BatchResult(custom_id=missing_id, content="ok", success=True)

    # Must not raise AttributeError.
    result = BatchResultStrategy()._process_successful_result(ctx, batch_result, missing_id)

    assert result.status.value == "success"
    assert result.data
