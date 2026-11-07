"""`constraints`, `enable_caching`, `max_execution_time` and `where_clause` configured nothing.

Each validated on an action and in `defaults:`, inherited into every agent dict, and
was read by no runtime module. A project writing `where_clause:` believed its records
were filtered; they were not. The four-surface refusal comes free from
`_RETIRED_CONFIG_KEYS`; what that cannot see is the declarations that let them validate.
"""

import re
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import (
    _RETIRED_CONFIG_KEYS,
    ActionConfig,
    DefaultsConfig,
    WorkflowConfig,
)
from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS
from agent_actions.output.response.config_schema import AgentConfig

REPO = Path(__file__).resolve().parents[3]

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

WRITTEN = {
    "constraints": ["no_pii"],
    "enable_caching": True,
    "max_execution_time": 30,
    "where_clause": {"clause": "x = 1"},
}

HINT = {
    "constraints": "write the instruction into the action's prompt",
    "enable_caching": "Anthropic prompt caching is enable_prompt_caching",
    "max_execution_time": "",
    "where_clause": "filter records with a guard: condition plus on_false: filter",
}

KEYS = sorted(WRITTEN)


def _workflow(defaults=None, action=None):
    return {
        "name": "wf",
        "description": "d",
        "version": "1.0",
        "defaults": {**BASE_DEFAULTS, **(defaults or {})},
        "actions": [{"name": "a1", "intent": "i", "prompt": "p", **(action or {})}],
    }


def _messages(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return "; ".join(error["msg"] for error in caught.value.errors())


def _reason(key: str) -> str:
    reason = f"'{key}' is no longer read and configures nothing; remove it"
    return f"{reason} — {HINT[key]}" if HINT[key] else reason


def _tracked_configs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.yml", "*.yaml"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


@pytest.mark.parametrize("key", KEYS)
class TestTheKeyIsRetiredRatherThanDeclared:
    def test_it_is_in_the_retired_table(self, key):
        """So the shared four-surface test refuses it without new test code."""
        assert key in _RETIRED_CONFIG_KEYS

    def test_its_hint_names_what_to_write_instead(self, key):
        assert _RETIRED_CONFIG_KEYS[key] == HINT[key]

    def test_it_is_no_longer_declared(self, key):
        """Declared, it validated and read as supported; inherited, it reached every agent."""
        assert key not in ActionConfig.model_fields
        assert key not in DefaultsConfig.model_fields
        assert key not in AgentConfig.model_fields
        assert key not in SIMPLE_CONFIG_FIELDS

    def test_an_action_that_writes_it_is_refused_by_name(self, key):
        """The marker, not a bare raises: an undeclared key on a strict model already
        fails, so only the retired message says the key is dead rather than misspelt."""
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(action={key: WRITTEN[key]}))

        assert f"action 'a1': {_reason(key)}" in _messages(caught)

    def test_the_defaults_block_refuses_it_by_name(self, key):
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(defaults={key: WRITTEN[key]}))

        assert f"defaults: {_reason(key)}" in _messages(caught)


class TestAnActionWritingAllFourIsToldAboutEachOne:
    def test_every_key_is_named_in_one_message(self):
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(action=dict(WRITTEN)))

        message = _messages(caught)
        assert "action 'a1': " + "; ".join(_reason(key) for key in KEYS) in message


class TestTheRefusalIsForTheKeyNotItsNeighbours:
    def test_a_workflow_that_omits_them_still_loads(self):
        config = WorkflowConfig.model_validate(_workflow())

        assert [action.name for action in config.actions] == ["a1"]

    @pytest.mark.parametrize("level", ["action", "defaults"])
    def test_enable_prompt_caching_is_still_accepted(self, level):
        """The hint for `enable_caching` points here, so this key must keep validating."""
        block = {"enable_prompt_caching": True}
        config = WorkflowConfig.model_validate(
            _workflow(action=block) if level == "action" else _workflow(defaults=block)
        )

        holder = config.actions[0] if level == "action" else config.defaults
        assert holder.enable_prompt_caching is True


class TestNoProjectInThisRepoStillWritesThem:
    """Retiring them breaks any config that writes one, so none may be left behind."""

    def test_no_shipped_project_fixture_or_example_declares_one(self):
        files = [
            REPO / path for path in _tracked_configs() if path.startswith(("examples/", "tests/"))
        ]
        assert files, "no project files found"

        declares = re.compile(rf"^\s*({'|'.join(KEYS)})\s*:", re.MULTILINE)
        offenders = [
            str(path.relative_to(REPO))
            for path in files
            if path.exists() and declares.search(path.read_text())
        ]

        assert offenders == [], offenders
