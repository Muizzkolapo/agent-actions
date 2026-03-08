"""Utility helpers shared across processors."""

from __future__ import annotations
import logging
from typing import Any, Optional
from agent_actions.errors import SchemaValidationError
from agent_actions.utils.udf_management.tooling import execute_user_defined_function
from agent_actions.llm.realtime import builder as agent_builder
from agent_actions.input.preprocessing.filtering.evaluator import get_guard_evaluator
from agent_actions.utils.transformation import PassthroughTransformer
from agent_actions.utils.constants import SCHEMA_KEY, STRICT_SCHEMA_KEY, ON_SCHEMA_MISMATCH_KEY

logger = logging.getLogger(__name__)


def evaluate_guard_condition(
    agent_config: dict[str, Any], context: Any
) -> tuple[bool, Optional[str]]:
    """
    Evaluate guard conditions (where_clause, conditional_clause).

    This is a centralized function for guard evaluation that can be called
    BEFORE prompt rendering to avoid template errors when guards would skip.

    Delegates to GuardEvaluator for unified evaluation logic.

    Args:
        agent_config: Agent configuration with guard conditions
        context: Context data for guard evaluation (should include upstream action data)

    Returns:
        Tuple of (should_execute, skip_behavior):
        - (True, None) = guard passed, proceed with execution
        - (False, 'skip') = guard failed with skip behavior, use passthrough
        - (False, 'filter') = guard failed with filter behavior, filter out entirely
    """
    evaluator = get_guard_evaluator()
    return evaluator.evaluate(
        item=context,
        guard_config=agent_config.get("guard"),
        conditional_clause=agent_config.get("conditional_clause"),
    )


def run_dynamic_agent(
    agent_config: dict[str, Any],
    agent_name: str,
    context: Any,
    formatted_prompt: str,
    *,
    tools_path: Optional[str] = None,
    tool_args: Optional[dict[str, Any]] = None,
    source_content: Optional[Any] = None,
    llm_context: Optional[Any] = None,
    skip_guard_eval: bool = False,
    skip_schema_validation: bool = False,
) -> tuple[Any, bool]:
    """Execute an agent with conditional guard processing and data filtering.

    Handles both legacy conditional clauses (UDF-based) and modern guard conditions
    with skip behavior. When skip conditions are met, returns the original context
    unchanged without executing the agent.

    Data Structure Handling:
        When context has nested structure (e.g., {source_guid, content{}, target_id}),
        this function extracts the 'content' dict before sending to tools/guards. This ensures:
        - Metadata fields (source_guid, target_id, node_id, lineage) are available for guards
        - Only actual data fields from 'content' are used for evaluation

    Context Separation:
        This function receives TWO contexts:
        - context: Original, untransformed data for guard evaluation
        - llm_context: Transformed data (with context_scope.drop applied) for LLM/tool execution

    Args:
        agent_config: Agent configuration including guard conditions
        agent_name: Name of the agent being executed
        context: Original data context for guard evaluation and tools/UDFs.
                 May be flat dict or nested structure with 'content' key.
        formatted_prompt: Formatted prompt for the agent
        tools_path: Optional path to tool functions
        tool_args: Optional tool arguments
        source_content: Optional source content
        llm_context: Optional transformed context for LLM (with context_scope applied).
                     If not provided, uses context for both guards and LLM.
        skip_guard_eval: If True, skip guard evaluation (already done by caller).
                        Used when guard was evaluated early (before prompt rendering).
        skip_schema_validation: If True, skip schema validation inside this function.
                        Set by callers that handle schema validation externally (e.g.,
                        the online reprompt loop via SchemaValidator).

    Returns:
        Tuple of (response/context, was_executed):
            - response/context: The response data or original context if skipped
            - was_executed: Whether the agent actually processed the data
    """
    # Skip guard evaluation if already done by caller (e.g., DataGenerator)
    if not skip_guard_eval:
        if _should_skip_legacy_conditional(agent_config, context):
            return (context, False)
        if _should_skip_guard(agent_config, context):
            return (context, False)
        if _should_filter_guard(agent_config, context):
            return (None, False)

    # Extract content from nested structure if needed (for tools/guards)
    if isinstance(context, dict) and "content" in context and isinstance(context["content"], dict):
        processed_context = context["content"]
    else:
        processed_context = context

    # Use llm_context if provided (transformed for LLM/tool), otherwise use processed_context
    llm_data = llm_context if llm_context is not None else processed_context

    # Pass both contexts to agent_builder (guards already ran on original data).
    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        llm_data,  # Send transformed context to LLM
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
        additional_context=None,
        original_context=processed_context,
    )

    # Note: passthrough fields are NOT merged here - they're merged later in
    # transform_with_observe() using the same pathway as observe directive
    # (via DataTransformer.update_schema_objects)

    # Validate LLM output against schema if enabled
    response = _validate_llm_output_schema(
        response, agent_config, agent_name, skip_schema_validation=skip_schema_validation
    )

    return (response, True)


def _resolve_schema_mismatch_mode(agent_config: dict[str, Any]) -> str:
    """Determine schema mismatch handling mode from config.

    Resolution order:
    1. ``on_schema_mismatch`` explicit key → "warn" | "reprompt" | "reject"
    2. ``strict_schema: true`` → "reject" (backward compat alias)
    3. Default → "warn"
    """
    explicit = agent_config.get(ON_SCHEMA_MISMATCH_KEY)
    if explicit in ("warn", "reprompt", "reject"):
        return explicit

    if explicit is not None:
        logger.warning(
            "Unrecognized on_schema_mismatch value '%s', defaulting to 'warn'",
            explicit,
        )

    if agent_config.get(STRICT_SCHEMA_KEY, False):
        return "reject"

    return "warn"


def _validate_llm_output_schema(
    response: Any,
    agent_config: dict[str, Any],
    agent_name: str,
    *,
    skip_schema_validation: bool = False,
) -> Any:
    """Validate LLM output against expected schema if schema is defined.

    When ``on_schema_mismatch`` is ``"reprompt"`` **and** the caller has set
    ``skip_schema_validation=True`` (indicating an outer reprompt loop will
    handle schema checks), this function returns early.  If the caller did
    *not* set the flag (e.g. file-mode tools), ``"reprompt"`` falls back to
    ``"warn"`` behaviour so mismatches are still surfaced.

    When strict_schema is enabled, raises SchemaValidationError if:
    - Required fields are missing
    - Extra fields are present (not in schema)
    - Field types don't match

    Args:
        response: The LLM response to validate
        agent_config: Agent configuration with schema and strict_schema settings
        agent_name: Name of the agent for error reporting
        skip_schema_validation: If True, skip validation entirely (caller handles it).

    Returns:
        The original response (validation is informational unless strict_schema is True)

    Raises:
        SchemaValidationError: If strict_schema is True and validation fails
    """
    schema = agent_config.get(SCHEMA_KEY)
    if not schema or not isinstance(schema, dict):
        return response

    mismatch_mode = _resolve_schema_mismatch_mode(agent_config)

    # Only skip when the caller explicitly says a reprompt loop is active
    if mismatch_mode == "reprompt" and skip_schema_validation:
        return response

    # Fall back to warn when reprompt is configured but no reprompt loop is active
    if mismatch_mode == "reprompt":
        mismatch_mode = "warn"

    strict_mode = mismatch_mode == "reject"

    try:
        from agent_actions.validation.schema_output_validator import (
            validate_output_against_schema,
        )

        report = validate_output_against_schema(
            response,
            schema,
            agent_name,
            strict_mode=strict_mode,
        )

        if not report.is_compliant:
            if strict_mode:
                raise SchemaValidationError(
                    f"LLM output does not match expected schema for action '{agent_name}'",
                    schema_name=report.schema_name,
                    validation_type="output",
                    action_name=agent_name,
                    expected_fields=list(report.expected_fields),
                    actual_fields=list(report.actual_fields),
                    missing_fields=report.missing_required,
                    extra_fields=report.extra_fields,
                    type_errors=report.type_errors,
                    hint="Enable strict_schema: false to allow schema mismatches, or update the prompt to match expected schema",
                )
            else:
                # Log warning but don't fail
                logger.warning(
                    "Schema validation warning for '%s': %s",
                    agent_name,
                    ", ".join(report.validation_errors)
                    if report.validation_errors
                    else "Schema mismatch detected",
                )

    except ImportError:
        # Module not available - skip validation (acceptable during testing/development)
        logger.warning("Schema output validator not available, skipping validation")
    except SchemaValidationError:
        # Re-raise schema validation errors - these should fail loudly
        raise
    except (ValueError, KeyError) as e:
        # Known validation data errors
        if strict_mode:
            raise SchemaValidationError(
                f"Schema validation failed unexpectedly for action '{agent_name}': {e}",
                action_name=agent_name,
                validation_type="output",
                hint="Check the schema format and LLM output structure",
                cause=e,
            ) from e
        logger.warning("Schema validation failed with error: %s", e, exc_info=True)

    return response


def _should_skip_legacy_conditional(agent_config: dict[str, Any], context: Any) -> bool:
    """Check if agent should be skipped based on legacy conditional clause."""
    conditional_clause = (agent_config.get("conditional_clause") or "").lower()
    if conditional_clause and (not execute_user_defined_function(conditional_clause, context)):
        return True
    return False


def _should_skip_guard(agent_config: dict[str, Any], context: Any) -> bool:
    """
    Check if agent should be skipped based on guard with skip behavior.

    Delegates to GuardEvaluator for unified evaluation logic.
    """
    evaluator = get_guard_evaluator()
    return evaluator.should_skip(agent_config, context)


def _should_filter_guard(agent_config: dict[str, Any], context: Any) -> bool:
    """
    Check if item should be filtered out based on guard with filter behavior.

    Delegates to GuardEvaluator for unified evaluation logic.
    """
    evaluator = get_guard_evaluator()
    return evaluator.should_filter(agent_config, context)


def transform_with_passthrough(
    data: list[Any],
    context_data: dict[str, Any],
    source_guid: str,
    agent_config: dict[str, Any],
    idx: int = 0,
    passthrough_fields: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> list[Any]:
    """Apply ``context_scope.passthrough`` logic to generated data consistently.

    Args:
        data: Generated data list
        context_data: Context data dictionary containing fields
        source_guid: Source GUID
        agent_config: Agent configuration containing context_scope
        idx: Index for node generation
        passthrough_fields: Optional pre-computed passthrough fields
        metadata: Optional LLM response metadata to add to output items

    Returns:
        Transformed data list with passthrough fields and metadata merged
    """
    transformer = PassthroughTransformer()
    return transformer.transform_with_passthrough(
        data,
        context_data,
        source_guid,
        agent_config,
        idx,
        passthrough_fields=passthrough_fields,
        metadata=metadata,
    )
