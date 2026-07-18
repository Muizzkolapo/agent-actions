"""Wire-point test for the DAG schema-fit preflight warning, driven through
the public `PreflightService.validate()` — no new symbol is imported."""

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


def test_preflight_warns_when_tool_consumer_required_field_not_guaranteed_upstream(caplog):
    """Producer LLM's nested items declare properties but no `required:` list; the
    downstream tool consumer's output schema requires the same field. Runtime schema
    validation will reject any record whose input item omitted it. F must warn."""
    cfgs = {
        "code_extractor": {
            "kind": "llm",
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "candidate_code_list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code_block": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            # No `required:` on items — the mismatch.
                        },
                    },
                },
                "required": ["candidate_code_list"],
                "additionalProperties": True,
            },
        },
        "flatten_code": {
            "kind": "tool",
            "impl": "cc_flatten_code",
            "dependencies": ["code_extractor"],
            "context_scope": {"observe": ["code_extractor.*"]},
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "code_block": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["code_block", "description"],
                "additionalProperties": True,
            },
        },
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    assert any("flatten_code" in m and "description" in m for m in msgs), msgs


def test_preflight_quiet_when_producer_guarantees_the_field(caplog):
    """Same shape but producer declares nested items' `required: [description]` — no
    gap, no warning."""
    cfgs = {
        "code_extractor": {
            "kind": "llm",
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "candidate_code_list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code_block": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["code_block", "description"],
                        },
                    },
                },
                "required": ["candidate_code_list"],
                "additionalProperties": True,
            },
        },
        "flatten_code": {
            "kind": "tool",
            "impl": "cc_flatten_code",
            "dependencies": ["code_extractor"],
            "context_scope": {"observe": ["code_extractor.*"]},
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "code_block": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["code_block", "description"],
                "additionalProperties": True,
            },
        },
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    assert not any("flatten_code" in m and "description" in m and "dag-fit" in m for m in msgs), msgs


def test_preflight_quiet_when_consumer_declares_defaults(caplog):
    """Consumer declares `defaults: { description: "" }` — synthesis is promised;
    F excludes the field from the input-requirement set."""
    cfgs = {
        "code_extractor": {
            "kind": "llm",
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "candidate_code_list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"description": {"type": "string"}},
                        },
                    },
                },
                "required": ["candidate_code_list"],
                "additionalProperties": True,
            },
        },
        "flatten_code": {
            "kind": "tool",
            "impl": "cc_flatten_code",
            "dependencies": ["code_extractor"],
            "context_scope": {"observe": ["code_extractor.*"]},
            "defaults": {"description": ""},
            "json_output_schema": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
                "required": ["description"],
                "additionalProperties": True,
            },
        },
    }
    msgs = _capture_preflight_warnings(cfgs, caplog)
    assert not any("flatten_code" in m and "description" in m and "dag-fit" in m for m in msgs), msgs
