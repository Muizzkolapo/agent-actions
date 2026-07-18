"""Wire-point test for the conditional-required-field preflight refusal, driven
through the public `PreflightService.validate()` — no new symbol is imported."""

from __future__ import annotations

import pytest

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.services.preflight_service import PreflightService


# Real module-level UDF so `inspect.getsource` returns its true body: the
# initial dict literal fixes only `options`; `source_quote` is written only
# when a runtime guard passes — the exact shape that crashed qanalabs
# `reconstruct_options` at 39/52 records post-568.
def _conditional_source_quote_tool(data):
    flat = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    result = {"options": flat.get("options", [])}
    if "source_quote" in flat:
        result["source_quote"] = flat["source_quote"]
    return result


def _make_service(action_configs: dict) -> PreflightService:
    return PreflightService(
        agent_name="wf",
        action_configs=action_configs,
        project_root=None,
        workflow_config_path="wf.yml",
        verify_keys=False,
    )


def test_preflight_refuses_when_required_field_only_conditionally_emitted():
    from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

    clear_registry()
    udf_tool(_conditional_source_quote_tool)
    try:
        cfgs = {
            "reconstruct_options": {
                "kind": "tool",
                "impl": "_conditional_source_quote_tool",
                "context_scope": {"observe": ["source.*"]},
                "schema": {
                    "type": "object",
                    "properties": {
                        "options": {"type": "array", "items": {"type": "string"}},
                        "source_quote": {"type": "string"},
                    },
                },
                "json_output_schema": {
                    "type": "object",
                    "properties": {
                        "options": {"type": "array", "items": {"type": "string"}},
                        "source_quote": {"type": "string"},
                    },
                    "required": ["options", "source_quote"],
                    "additionalProperties": True,
                },
            }
        }
        with pytest.raises(PreFlightValidationError) as excinfo:
            _make_service(cfgs).validate()
        message = str(excinfo.value)
        assert "reconstruct_options" in message, message
        assert "source_quote" in message, message
    finally:
        clear_registry()
