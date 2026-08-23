"""Utility helpers shared across processors."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.errors import SchemaValidationError
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


def _is_tool_action(agent_config: dict[str, Any]) -> bool:
    return agent_config.get("kind") == "tool" or agent_config.get("model_vendor") == "tool"


def _resolve_schema_mismatch_mode(agent_config: dict[str, Any]) -> str:
    """Resolve schema mismatch mode from reprompt.on_schema_mismatch.

    Returns ``"reject"``, ``"reprompt"``, or ``"warn"`` (internal signal for
    no enforcement).

    For deterministic tool actions, ``"reprompt"`` is coerced to ``"reject"``
    because re-running the same UDF on the same input always yields the same
    output — reprompt is inert and would only burn futile attempts.
    """
    reprompt = agent_config.get("reprompt")
    if isinstance(reprompt, dict) and reprompt.get("on_schema_mismatch"):
        mode = str(reprompt["on_schema_mismatch"])
        if mode == "reprompt" and _is_tool_action(agent_config):
            logger.warning(
                "Action '%s': on_schema_mismatch=reprompt is inert for deterministic tools "
                "— treating as reject.",
                agent_config.get("name", "unknown"),
            )
            return "reject"
        return mode
    return "warn"


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
    return len([key for key in record if key != VERDICT_KEY])


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
    *,
    skip_schema_validation: bool = False,
) -> Any:
    """Validate LLM output against expected schema if defined.

    Returns the response unchanged. When ``reprompt.on_schema_mismatch`` is
    "reprompt" and ``skip_schema_validation`` is True, validation is deferred
    to the outer reprompt loop.

    Schema-echo detection runs unconditionally (not gated by
    ``skip_schema_validation``) because echoed schemas are never valid output.

    Raises:
        SchemaValidationError: If on_schema_mismatch="reject" and validation fails.
    """
    # Unconditional schema-echo rejection — runs even when validation is skipped
    response = _reject_schema_echo_items(response, agent_name)

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

    # Empty output is the on_empty handler's domain, not schema validation's:
    # an empty response has no fields to check, so rejecting it here would
    # pre-empt the on_empty policy (skip/warn/error) with a hard failure.
    if _is_empty_output(response):
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
