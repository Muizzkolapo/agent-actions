"""Wire-point tests for the DAG schema-fit preflight warning, driven through
the public `PreflightService.validate()` — no new symbol is imported.

Quiet tests include a sentinel consumer that is expected to warn: if F is ever
silenced or its message prefix is renamed, the sentinel assertion breaks first,
so the quiet-side assertions cannot pass on a dead check."""

from __future__ import annotations

import logging

from agent_actions.services.preflight_service import PreflightService


def _make_service(action_configs: dict) -> PreflightService:
    return PreflightService(
        agent_name="wf",
        action_configs=action_configs,
        project_root=None,
        workflow_config_path="wf.yml",
        verify_keys=False,
    )


def _capture_preflight_warnings(cfgs: dict, caplog) -> list[str]:
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


def _llm_producer(nested_required: list[str] | None = None) -> dict:
    items: dict = {
        "type": "object",
        "properties": {
            "code_block": {"type": "string"},
            "description": {"type": "string"},
        },
    }
    if nested_required:
        items["required"] = list(nested_required)
    return {
        "kind": "llm",
        "context_scope": {"observe": ["source.*"]},
        "schema": {
            "type": "object",
            "properties": {
                "candidate_code_list": {
                    "type": "array",
                    "items": {"type": "object", "properties": {}},
                }
            },
        },
        "json_output_schema": {
            "type": "object",
            "properties": {
                "candidate_code_list": {"type": "array", "items": items},
            },
            "required": ["candidate_code_list"],
            "additionalProperties": True,
        },
    }


def _tool_consumer(
    name: str,
    required: list[str],
    defaults: dict | None = None,
    producer: str = "code_extractor",
) -> dict:
    schema_props = {f: {"type": "string"} for f in required}
    cfg: dict = {
        "kind": "tool",
        "impl": f"cc_{name}",
        "dependencies": [producer],
        "context_scope": {"observe": [f"{producer}.*"]},
        "schema": {"type": "object", "properties": schema_props},
        "json_output_schema": {
            "type": "object",
            "properties": schema_props,
            "required": list(required),
            "additionalProperties": True,
        },
    }
    if defaults is not None:
        cfg["defaults"] = defaults
    return cfg


# The sentinel consumer requires a field the producer never guarantees at any
# depth and never declares in `defaults:` — F is required to warn for it.
# Every quiet test uses this sentinel to prove F actually ran.
_SENTINEL_FIELD = "unrelated_sentinel_field"
_SENTINEL_NAME = "sentinel_consumer"


def _sentinel() -> dict:
    return _tool_consumer(_SENTINEL_NAME, required=[_SENTINEL_FIELD])


def test_preflight_warns_when_tool_consumer_required_field_not_guaranteed_upstream(caplog):
    """Producer LLM's nested items declare properties but no `required:` list; the
    downstream tool consumer's output schema requires `description`. F must warn,
    and the warning message must carry the `dag-fit` prefix that pins the emission
    to F rather than any other preflight step."""
    cfgs = {
        "code_extractor": _llm_producer(nested_required=None),
        "flatten_code": _tool_consumer("flatten_code", required=["code_block", "description"]),
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    assert any("dag-fit" in m and "flatten_code" in m and "description" in m for m in msgs), msgs


def test_preflight_quiet_when_producer_guarantees_the_field(caplog):
    """When the producer declares `required: [description]` on its nested items,
    F must NOT emit for the target consumer. The sentinel consumer proves F ran."""
    cfgs = {
        "code_extractor": _llm_producer(nested_required=["code_block", "description"]),
        "flatten_code": _tool_consumer("flatten_code", required=["code_block", "description"]),
        _SENTINEL_NAME: _sentinel(),
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    # Sentinel must fire — proves F ran and its message prefix hasn't drifted.
    assert any("dag-fit" in m and _SENTINEL_NAME in m and _SENTINEL_FIELD in m for m in msgs), (
        f"F did not warn on the sentinel — is step 9 wired? msgs={msgs}"
    )
    # Target consumer must be quiet.
    assert not any("dag-fit" in m and "flatten_code" in m and "description" in m for m in msgs), (
        msgs
    )


def test_preflight_quiet_when_consumer_declares_defaults(caplog):
    """When the consumer declares `defaults: { description: "" }`, F must exclude
    `description` from the input-requirement set and NOT emit for it. The sentinel
    proves F still runs on other consumers."""
    cfgs = {
        "code_extractor": _llm_producer(nested_required=None),
        "flatten_code": _tool_consumer(
            "flatten_code",
            required=["description"],
            defaults={"description": ""},
        ),
        _SENTINEL_NAME: _sentinel(),
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    # Sentinel must fire.
    assert any("dag-fit" in m and _SENTINEL_NAME in m and _SENTINEL_FIELD in m for m in msgs), (
        f"F did not warn on the sentinel — is step 9 wired? msgs={msgs}"
    )
    # Target consumer must be quiet on the defaulted field.
    assert not any("dag-fit" in m and "flatten_code" in m and "description" in m for m in msgs), (
        msgs
    )
