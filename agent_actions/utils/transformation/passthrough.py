"""Orchestrator for passthrough transformations using the Strategy Pattern."""

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.utils.field_management import FieldManager

from .strategies import (
    ContextScopeStructuredStrategy,
    ContextScopeUnstructuredStrategy,
    DefaultStructureStrategy,
    NoOpStrategy,
    PrecomputedStructuredStrategy,
    PrecomputedUnstructuredStrategy,
)
from .strategies.base import ensure_dict_output


class PassthroughTransformer:
    """Orchestrates passthrough transformations using strategy pattern dispatch.

    Strategies return flat action output dicts.  This class assembles
    the final records via ``RecordEnvelope.build()``, guaranteeing
    every output wraps under the action namespace and preserves
    upstream namespaces.
    """

    def __init__(self, field_manager: FieldManager | None = None):
        """Initialize with an optional FieldManager (defaults to a new instance)."""
        self.field_manager = field_manager or FieldManager()

        # First match wins, so order matters
        self.strategies = [
            PrecomputedStructuredStrategy(),
            PrecomputedUnstructuredStrategy(),
            ContextScopeStructuredStrategy(),
            ContextScopeUnstructuredStrategy(),
            NoOpStrategy(),
            DefaultStructureStrategy(),  # Catch-all
        ]

    def transform_with_passthrough(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        action_name: str = "unknown_action",
        passthrough_fields: dict | None = None,
        metadata: dict | None = None,
        existing_content: dict | None = None,
        input_record: dict | None = None,
    ) -> list:
        """Apply context_scope.passthrough logic to generated data.

        Strategies produce flat action output dicts (just the fields
        belonging to this action's namespace).  This method wraps each
        via ``RecordEnvelope.build()`` so the output always has the
        correct ``{content: {**upstream, action_name: output}}`` shape.

        Args:
            data: Generated data list.
            context_data: Context data dictionary containing fields.
            source_guid: Source GUID.
            agent_config: Agent configuration containing context_scope.
            action_name: Action name for namespace wrapping and node_id.
            passthrough_fields: Optional pre-computed passthrough fields
                from field_context (enables passthrough from any ancestor).
            metadata: Optional LLM response metadata to add to output items.
            existing_content: Upstream namespaces to preserve in the output.
                When provided, every output record will carry these namespaces
                alongside the current action's namespace.

        Returns:
            Transformed data list with passthrough fields merged.
        """
        if not isinstance(data, list):
            data = [data] if data is not None else []  # type: ignore[unreachable]

        already_structured = self._is_already_structured(data)

        action_outputs = None
        for strategy in self.strategies:
            if strategy.can_handle(data, passthrough_fields, agent_config, already_structured):
                action_outputs = strategy.transform(
                    data, context_data, source_guid, agent_config, passthrough_fields
                )
                break

        if action_outputs is None:
            action_outputs = []

        # Build records via RecordEnvelope — wraps under namespace, preserves upstream
        # content and carries tracking fields. If a real input_record is provided (from
        # the calling strategy), use it so version_correlation_id is preserved. Otherwise
        # fall back to a synthetic record (backward compat for callers without it).
        envelope_input = input_record or {
            "source_guid": source_guid,
            "content": existing_content or {},
        }
        output = [
            RecordEnvelope.build(action_name, ensure_dict_output(fields), envelope_input)
            for fields in action_outputs
        ]

        return [
            self.field_manager.ensure_required_fields(
                obj, source_guid, action_name, metadata=metadata
            )
            for obj in output
        ]

    @staticmethod
    def _is_already_structured(data: list) -> bool:
        """Check if every item has ``source_guid`` and ``content`` keys."""
        return len(data) > 0 and all(
            isinstance(item, dict) and "source_guid" in item and "content" in item for item in data
        )
