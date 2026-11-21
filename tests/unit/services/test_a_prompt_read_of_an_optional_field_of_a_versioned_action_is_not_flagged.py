"""A prompt reads a versioned action by its base name; observed as optional, it is not flagged.

The normaliser expands `ext.x?` to `ext_1.x` and `ext_2.x`, but the prompt reads
`{{ ext.x }}`, so preflight must know the optional field by the base name too.
"""

from __future__ import annotations

from typing import Any

from agent_actions.input.context.normalizer import normalize_all_agent_configs
from agent_actions.services.preflight_service import PreflightService
from agent_actions.validation.prompt_required_field_validator import (
    find_unguarded_required_refs,
)

PROMPTS = {"consumer": "Value: {{ ext.x }}"}
NOT_GUARANTEED = {"fields": [{"id": "x", "required": False}]}
SCHEMAS = {"ext_1": NOT_GUARANTEED, "ext_2": NOT_GUARANTEED, "ext": NOT_GUARANTEED}


def _optional_observes(observed: str) -> dict[str, set[str]]:
    configs: dict[str, dict[str, Any]] = {
        "ext_1": {"is_versioned_agent": True, "version_base_name": "ext"},
        "ext_2": {"is_versioned_agent": True, "version_base_name": "ext"},
        "consumer": {"context_scope": {"observe": [observed]}},
    }
    normalize_all_agent_configs(configs)
    return PreflightService("wf", configs, None, "wf.yml")._collect_optional_observes()


def test_the_base_name_read_of_the_optional_field_is_not_flagged():
    findings = find_unguarded_required_refs(PROMPTS, SCHEMAS, _optional_observes("ext.x?"))

    assert findings == []


def test_the_same_read_is_flagged_without_the_mark():
    findings = find_unguarded_required_refs(PROMPTS, SCHEMAS, _optional_observes("ext.x"))

    assert len(findings) == 1
    assert "'ext.x'" in findings[0]
