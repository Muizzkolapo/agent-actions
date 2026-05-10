"""Utility helpers shared across processors."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.errors import SchemaValidationError
from agent_actions.utils.constants import SCHEMA_KEY
from agent_actions.utils.transformation import PassthroughTransformer

logger = logging.getLogger(__name__)


def run_dynamic_agent(
    agent_config: dict[str, Any],
    agent_name: str,
    context: Any,
    formatted_prompt: str,
    *,
    tools_path: str | None = None,
    tool_args: dict[str, Any] | None = None,
    source_content: Any | None = None,
    llm_context: Any | None = None,
    skip_guard_eval: bool = False,
    skip_schema_validation: bool = False,
) -> tuple[Any, bool]:
    """Execute an agent with guard evaluation, returning (response, was_executed).

    Uses ``context`` (original data) for guard evaluation and ``llm_context``
    (transformed data with context_scope.drop applied) for LLM execution.
    When skip conditions are met, returns the original context without executing.
    """
    if not skip_guard_eval:
        from agent_actions.guards import GuardBehavior
        from agent_actions.input.preprocessing.filtering.evaluator import (
            get_guard_evaluator,
        )

        guard_result = get_guard_evaluator().evaluate(
            item=context,
            guard_config=agent_config.get("guard"),
            conditional_clause=agent_config.get("conditional_clause"),
        )
        if not guard_result.should_execute:
            if guard_result.behavior == GuardBehavior.FILTER:
                return (None, False)
            return (context, False)

    from agent_actions.llm.realtime import builder as agent_builder

    llm_data = llm_context if llm_context is not None else context

    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        llm_data,
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
        additional_context=None,
    )

    response = _validate_llm_output_schema(
        response, agent_config, agent_name, skip_schema_validation=skip_schema_validation
    )

    return (response, True)


def _resolve_schema_mismatch_mode(agent_config: dict[str, Any]) -> str:
    """Resolve schema mismatch mode from reprompt.on_schema_mismatch.

    Returns ``"reject"``, ``"reprompt"``, or ``"warn"`` (internal signal for
    no enforcement).
    """
    reprompt = agent_config.get("reprompt")
    if isinstance(reprompt, dict) and reprompt.get("on_schema_mismatch"):
        return str(reprompt["on_schema_mismatch"])
    return "warn"


def _validate_llm_output_schema(
    response: Any,
    agent_config: dict[str, Any],
    agent_name: str,
    *,
    skip_schema_validation: bool = False,
) -> Any:
    """Validate LLM output against expected schema if defined.

    Returns the response unchanged. When ``reprompt.on_schema_mismatch`` is
    "reprompt" and ``skip_schema_validation`` is True, validation is deferred
    to the outer reprompt loop.

    Raises:
        SchemaValidationError: If on_schema_mismatch="reject" and validation fails.
    """
    schema = agent_config.get(SCHEMA_KEY)
    if not schema or not isinstance(schema, dict):
        mismatch_mode = _resolve_schema_mismatch_mode(agent_config)
        if mismatch_mode in ("reject", "reprompt"):
            logger.warning(
                "Action '%s': reprompt.on_schema_mismatch is '%s' but no schema is "
                "defined — schema validation will be skipped.",
                agent_name,
                mismatch_mode,
            )
        return response

    mismatch_mode = _resolve_schema_mismatch_mode(agent_config)

    if mismatch_mode == "reprompt" and skip_schema_validation:
        return response

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
                hint = (
                    "Remove reprompt.on_schema_mismatch: reject to allow schema "
                    "mismatches, or update the prompt to match expected schema"
                )
                if report.namespace_hint:
                    hint = f"{hint}. {report.namespace_hint}"
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
                    hint=hint,
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
        logger.warning("Schema output validator not available, skipping validation")
    except SchemaValidationError:
        raise
    except ValueError as e:
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


def transform_with_passthrough(
    data: list[Any],
    context_data: dict[str, Any],
    source_guid: str,
    agent_config: dict[str, Any],
    action_name: str = "unknown_action",
    passthrough_fields: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    existing_content: dict[str, Any] | None = None,
    input_record: dict[str, Any] | None = None,
) -> list[Any]:
    """Apply ``context_scope.passthrough`` logic to generated data."""
    transformer = PassthroughTransformer()
    return transformer.transform_with_passthrough(
        data,
        context_data,
        source_guid,
        agent_config,
        action_name,
        passthrough_fields=passthrough_fields,
        metadata=metadata,
        existing_content=existing_content,
        input_record=input_record,
    )
