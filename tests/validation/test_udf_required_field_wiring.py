"""Wire-point test for the conditional-required-field preflight warning.

Anchors RED on the actual behavioural failure (no preflight warning is emitted
today for a tool UDF that only conditionally produces a required output-schema
field) so the fix is proven end-to-end through the public `PreflightService`
API — no new symbol is imported here."""

from __future__ import annotations

import logging

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


def _capture_preflight_warnings(cfgs: dict, caplog) -> list[str]:
    """Full `validate()` must reach the new check and stay non-fatal.

    The `agent_actions` logger does not propagate by default; caplog needs it
    on to see the warning."""
    logger_name = "agent_actions.services.preflight_service"
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger=logger_name):
            _make_service(cfgs).validate()
        return [r.getMessage() for r in caplog.records if r.name == logger_name]
    finally:
        aa_logger.propagate = original


def test_preflight_warns_when_required_field_only_conditionally_emitted(caplog):
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
        msgs = _capture_preflight_warnings(cfgs, caplog)
        assert any("reconstruct_options" in m and "source_quote" in m for m in msgs), msgs
    finally:
        clear_registry()
