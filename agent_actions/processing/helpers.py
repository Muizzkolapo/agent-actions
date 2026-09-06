"""Utility helpers shared across processors."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.utils.constants import SCHEMA_KEY, VERDICT_KEY
from agent_actions.utils.schema_echo import is_schema_echo as _is_schema_echo
from agent_actions.utils.schema_echo import make_schema_echo_error as _make_schema_echo_error
from agent_actions.utils.transformation import PassthroughTransformer

logger = logging.getLogger(__name__)


def get_parse_error_marker(response: Any) -> str | None:
    """Return ``_parse_error`` string if *response* contains a provider JSON parse failure.

    Checks both dict and list-wrapped formats used by online providers.
    Returns ``None`` when no parse error is present.
    """
    if isinstance(response, dict):
        return response.get("_parse_error") or None
    if isinstance(response, list) and response and isinstance(response[0], dict):
        return response[0].get("_parse_error") or None
    return None


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
        llm_data,
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
        additional_context=None,
    )

    response = _validate_llm_output_schema(response, agent_config, agent_name)

    return (response, True)


def _is_tool_action(agent_config: dict[str, Any]) -> bool:
    return agent_config.get("kind") == "tool" or agent_config.get("model_vendor") == "tool"


def _reject_schema_echo_items(response: Any, agent_name: str) -> Any:
    """Replace schema-echo responses with ``_parse_error`` dicts.

    Handles both dict responses (single schema-echo) and list responses
    (schema-echo items within a list).  Runs unconditionally because
    schema echoes are never valid output regardless of validation settings.
    """
    if isinstance(response, dict) and _is_schema_echo(response):
        logger.warning(
            "[%s] Schema-echo detected in LLM response (dict) — replacing with _parse_error.",
            agent_name,
        )
        return _make_schema_echo_error(response)

    if not isinstance(response, list):
        return response

    # Fast path: scan for echoes before allocating a new list
    first_echo = None
    for i, item in enumerate(response):
        if _is_schema_echo(item):
            first_echo = i
            break
    if first_echo is None:
        return response

    # Build replacement list only when at least one echo was found
    result: list[Any] = list(response[:first_echo])
    for item in response[first_echo:]:
        if _is_schema_echo(item):
            logger.warning(
                "[%s] Schema-echo detected in LLM response — replacing with _parse_error.",
                agent_name,
            )
            result.append(_make_schema_echo_error(item))
        else:
            result.append(item)
    return result


def _content_keys(record: Any) -> int:
    """How many real content keys a record has, ignoring the attached verdict.

    An expectations verdict is framework metadata, not output — a record that
    carries nothing else is still empty.
    """
    if not isinstance(record, dict):
        return 1
    verdict = record.get(VERDICT_KEY)
    is_verdict = isinstance(verdict, dict) and "overall_pass" in verdict
    return len(record) - (1 if is_verdict else 0)


def _is_empty_output(response: Any) -> bool:
    """Check if a tool/LLM response is effectively empty."""
    if response is None:
        return True
    if isinstance(response, dict) and _content_keys(response) == 0:
        return True
    if isinstance(response, list):
        if len(response) == 0:
            return True
        if all(isinstance(item, dict) and _content_keys(item) == 0 for item in response):
            return True
    return False


def _validate_llm_output_schema(
    response: Any,
    agent_config: dict[str, Any],
    agent_name: str,
) -> Any:
    """Warn when LLM output does not match the action's schema.

    Enforcement belongs to an ``expect:`` block, whose structural gate
    regenerates a response the schema rejects. This reports the mismatch for an
    action that has no such block.

    Schema-echo detection runs unconditionally because an echoed schema is never
    valid output.
    """
    # Unconditional schema-echo rejection — runs even when validation is skipped
    response = _reject_schema_echo_items(response, agent_name)

    schema = agent_config.get(SCHEMA_KEY)
    if not schema or not isinstance(schema, dict):
        return response

    # Empty output is the on_empty handler's domain, not schema validation's:
    # an empty response has no fields to check, so rejecting it here would
    # pre-empt the on_empty policy (skip/warn/error) with a hard failure.
    if _is_empty_output(response):
        return response

    try:
        from agent_actions.validation.schema_output_validator import (
            validate_output_against_schema,
        )

        report = validate_output_against_schema(response, schema, agent_name, strict_mode=False)

        if not report.is_compliant:
            logger.warning(
                "Schema validation warning for '%s': %s",
                agent_name,
                ", ".join(report.validation_errors)
                if report.validation_errors
                else "Schema mismatch detected",
            )

    except ImportError:
        logger.warning("Schema output validator not available, skipping validation")
    except ValueError as e:
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
