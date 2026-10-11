"""`policy:` validated, was listed as a real action field, and configured nothing.

The declaration, the generated docs and the configuration reference all presented it
as supported, while no runtime module read it. It was an untyped string, so no value
was ever rejected and a project could carry `policy: strict` indefinitely.

The four-surface refusal comes free from `_RETIRED_CONFIG_KEYS`. What that cannot see
is the declaration and the two places that advertised the key.
"""

import re
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import _RETIRED_CONFIG_KEYS, ActionConfig, WorkflowConfig

REPO = Path(__file__).resolve().parents[3]

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}


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


def _tracked_configs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.yml", "*.yaml"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


class TestTheKeyIsRetiredRatherThanDeclared:
    def test_it_is_in_the_retired_table(self):
        """So the shared four-surface test refuses it without new test code."""
        assert "policy" in _RETIRED_CONFIG_KEYS

    def test_it_is_no_longer_a_declared_field(self):
        """Declared, it validated and read as supported."""
        assert "policy" not in ActionConfig.model_fields

    def test_an_action_that_writes_it_is_refused_by_name(self):
        """The marker, not a bare raises: an undeclared key on a strict model already
        fails, so only the retired message says the key is dead rather than misspelt."""
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(action={"policy": "strict"}))

        assert "'policy' is no longer read and configures nothing" in _messages(caught)

    def test_the_defaults_block_refuses_it_by_name(self):
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(defaults={"policy": "strict"}))

        assert "'policy' is no longer read and configures nothing" in _messages(caught)

    def test_a_workflow_that_omits_it_still_loads(self):
        """Control: the refusal is for the key, not for the action around it."""
        config = WorkflowConfig.model_validate(_workflow())

        assert [action.name for action in config.actions] == ["a1"]


class TestNothingStillAdvertisesIt:
    def test_the_docs_parser_no_longer_echoes_it(self):
        """The echo put it in generated docs, which is how a project learned to write it."""
        parser = REPO / "agent_actions/tooling/docs/parser.py"

        assert '"policy"' not in parser.read_text()

    def test_the_configuration_reference_no_longer_lists_it(self):
        reference = REPO / "docs.agent-actions/docs/reference/configuration/index.md"
        if not reference.exists():
            pytest.skip("docs not present")

        assert not re.search(r"^\|\s*`policy`\s*\|", reference.read_text(), re.MULTILINE)


class TestNoProjectInThisRepoStillWritesIt:
    """Retiring it breaks any config that writes it, so none may be left behind."""

    def test_no_shipped_project_fixture_or_example_declares_it(self):
        files = [
            REPO / path for path in _tracked_configs() if path.startswith(("examples/", "tests/"))
        ]
        assert files, "no project files found"

        declares = re.compile(r"^\s*policy\s*:", re.MULTILINE)
        offenders = [
            str(path.relative_to(REPO))
            for path in files
            if path.exists() and declares.search(path.read_text())
        ]

        assert offenders == [], offenders
