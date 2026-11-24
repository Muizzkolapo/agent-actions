"""A key whose runtime was deleted fails like any other key that no block takes.

Each surface that carries agent settings refuses it with its generic unknown-key
error: an action, a workflow's `defaults:`, a `versions:` block and the project's
`default_agent_config:`.
"""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import (
    ActionConfig,
    DefaultsConfig,
    VersionConfig,
    WorkflowConfig,
)
from agent_actions.expectations.loader import build_inline_suite
from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS
from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.output.response.expander import ActionExpander
from agent_actions.validation.expectations_validator import find_expectation_defects

RETIRED_KEYS = [
    "anthropic_version",
    "constraints",
    "enable_caching",
    "ephemeral",
    "idempotency_key",
    "interceptors",
    "max_execution_time",
    "on_schema_mismatch",
    "policy",
    "reduce_key",
    "reprompt",
    "skip_condition",
    "skip_if",
    "version_mode",
    "where_clause",
    # Renamed spellings: `dependencies` and `chunk_overlap`.
    "depends_on",
    "overlap",
]

REPO = Path(__file__).resolve().parents[3]

SURFACES = ["action", "defaults", "versions", "default_agent_config"]

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}


def _refusal(surface: str, key: str) -> list[dict]:
    """The pydantic errors *surface* gives for *key*."""
    written = {key: "x"}
    with pytest.raises(ValidationError) as caught:
        if surface == "action":
            ActionConfig.model_validate({"name": "a1", "intent": "i", **written})
        elif surface == "defaults":
            DefaultsConfig.model_validate({**BASE_DEFAULTS, **written})
        elif surface == "versions":
            VersionConfig.model_validate({"range": [1, 2], **written})
        else:
            DefaultAgentConfig.model_validate({**BASE_DEFAULTS, **written})
    return caught.value.errors()


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("key", [*RETIRED_KEYS, "not_a_key"])
def test_a_retired_key_is_refused_as_an_unknown_key(surface, key):
    """`not_a_key` is the control: a retired key gets exactly what any stray key gets."""
    errors = _refusal(surface, key)

    if surface == "action":
        assert [(e["type"], e["loc"]) for e in errors] == [("extra_forbidden", (key,))]
    else:
        message = "; ".join(e["msg"] for e in errors)
        assert f"unknown {surface} key '{key}'" in message
        assert f"valid {surface} keys are " in message
        assert "no longer read" not in message


@pytest.mark.parametrize("surface", ["defaults", "default_agent_config"])
def test_overlap_suggests_chunk_overlap(surface):
    message = "; ".join(e["msg"] for e in _refusal(surface, "overlap"))

    assert "did you mean 'chunk_overlap'?" in message


def test_a_mode_in_a_versions_block_is_refused_as_an_unknown_key():
    errors = _refusal("versions", "mode")

    message = "; ".join(e["msg"] for e in errors)
    assert "unknown versions key 'mode'" in message
    assert "valid versions keys are param, range" in message


@pytest.mark.parametrize("key", RETIRED_KEYS)
def test_no_model_that_carries_agent_settings_declares_it(key):
    """`AgentConfig` takes extras, so a declaration there is the only thing to check."""
    assert key not in ActionConfig.model_fields
    assert key not in DefaultsConfig.model_fields
    assert key not in AgentConfig.model_fields
    assert key not in SIMPLE_CONFIG_FIELDS


@pytest.mark.parametrize("level", ["action", "defaults"])
def test_enable_prompt_caching_is_still_accepted(level):
    block = {"enable_prompt_caching": True}
    workflow = {
        "name": "wf",
        "description": "d",
        "defaults": {**BASE_DEFAULTS, **(block if level == "defaults" else {})},
        "actions": [{"name": "a1", "intent": "i", **(block if level == "action" else {})}],
    }

    config = WorkflowConfig.model_validate(workflow)

    holder = config.actions[0] if level == "action" else config.defaults
    assert holder.enable_prompt_caching is True


@pytest.mark.parametrize("key", ["reprompt", "on_schema_mismatch"])
def test_a_field_named_like_a_retired_key_is_still_excludable(key):
    """Checked at the three layers a rule passes through, which take different shapes."""
    rule = {"type": "no_null_fields", "params": {"exclude": [key]}}
    workflow = {
        "name": "wf",
        "description": "d",
        "defaults": dict(BASE_DEFAULTS),
        "actions": [{"name": "a1", "intent": "i", "expect": {"expectations": [rule]}}],
    }

    validated = WorkflowConfig.model_validate(workflow)
    build_inline_suite([rule], "a1")
    defects = find_expectation_defects({"a1": {"expect": {"expectations": [rule]}}}, {"a1": set()})

    assert validated.actions[0].expect.expectations == [rule]
    assert not defects, defects


def test_the_expander_copies_no_undeclared_key_onto_the_agent():
    """The expander is reached here without validation, which refuses the key first."""
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [
                {
                    "name": "a1",
                    "intent": "i",
                    "prompt": "p",
                    "interceptors": [{"type": "validation"}],
                    "expect": {"repair": "auto"},
                }
            ],
            "defaults": dict(BASE_DEFAULTS),
        }
    )
    agent = expanded["wf"][0]

    assert "interceptors" not in agent
    assert agent["expect"]["repair"] == "auto"


class TestNothingAdvertisesARetiredKey:
    """The docs echo and the reference pages are how a project learned to write one."""

    def test_the_docs_parser_echoes_none(self):
        parser = (REPO / "agent_actions/tooling/docs/parser.py").read_text()

        for key in ("idempotency_key", "reduce_key"):
            assert key not in parser
        assert '"policy"' not in parser

    def test_the_configuration_reference_lists_none(self):
        reference = REPO / "docs.agent-actions/docs/reference/configuration/index.md"
        if not reference.exists():
            pytest.skip("docs not present")
        text = reference.read_text()

        assert "idempotency_key" not in text
        assert not re.search(r"^\|\s*`policy`\s*\|", text, re.MULTILINE)

    def test_the_troubleshooting_guide_does_not_teach_reduce_key(self):
        guide = REPO / "docs.agent-actions/docs/guides/troubleshooting.md"
        if not guide.exists():
            pytest.skip("docs not present")

        assert "reduce_key" not in guide.read_text()
