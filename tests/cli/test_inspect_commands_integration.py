"""Integration tests for inspect command _output_rich() and _output_json() methods."""

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from agent_actions.cli.inspect import (
    ActionCommand,
    ContextCommand,
    DependenciesCommand,
    GraphCommand,
)
from agent_actions.models.action_schema import (
    ActionKind,
    ActionSchema,
    FieldInfo,
    FieldSource,
)
from agent_actions.workflow.coordinator import AgentWorkflow


def _make_workflow_mock():
    """Create a mock AgentWorkflow with realistic action configs."""
    wf = MagicMock(spec=AgentWorkflow)
    wf.action_configs = {
        "extract": {
            "kind": "llm",
            "model_name": "gpt-4",
            "granularity": "record",
            "dependencies": [],
            "schema": {"properties": {"fact": {"type": "string"}}},
        },
        "summarize": {
            "kind": "llm",
            "model_name": "gpt-4",
            "granularity": "record",
            "dependencies": ["extract"],
            "context_scope": {"observe": ["extract.fact"], "passthrough": []},
            "schema": {"properties": {"summary": {"type": "string"}, "score": {"type": "number"}}},
        },
    }
    wf.execution_order = ["extract", "summarize"]
    return wf


def _make_dependency_info():
    return {
        "extract": {
            "explicit_dependencies": [],
            "input_sources": [],
            "context_sources": [],
            "context_scope": {"observe": [], "passthrough": []},
            "has_primary_dependency": False,
            "primary_dependency": None,
        },
        "summarize": {
            "explicit_dependencies": ["extract"],
            "input_sources": ["extract"],
            "context_sources": [],
            "context_scope": {"observe": ["extract.fact"], "passthrough": []},
            "has_primary_dependency": False,
            "primary_dependency": None,
        },
    }


def _make_action_schemas():
    """Create ActionSchema objects matching the workflow mock fixture."""
    return {
        "extract": ActionSchema(
            name="extract",
            kind=ActionKind.LLM,
            upstream_refs=[],
            input_fields=[],
            output_fields=[
                FieldInfo(name="fact", source=FieldSource.SCHEMA, field_type="string"),
            ],
            dependencies=[],
            downstream=["summarize"],
        ),
        "summarize": ActionSchema(
            name="summarize",
            kind=ActionKind.LLM,
            upstream_refs=[],
            input_fields=[],
            output_fields=[
                FieldInfo(name="score", source=FieldSource.SCHEMA, field_type="number"),
                FieldInfo(name="summary", source=FieldSource.SCHEMA, field_type="string"),
            ],
            dependencies=["extract"],
            downstream=[],
        ),
    }


def _new_cmd(cls, **extra_attrs):
    """Instantiate a command class bypassing __init__.

    Mirrors the pattern in test_cli_hardening.py. If BaseInspectCommand.__init__
    adds required state, these tests will need updating.
    """
    cmd = cls.__new__(cls)
    cmd.agent = "test_wf.yml"
    cmd.agent_name = "test_wf"
    cmd.user_code = None
    cmd.json_output = False
    cmd.console = Console(file=StringIO(), force_terminal=True, width=120)
    cmd.paths = MagicMock(schema_dir=None)
    schemas = _make_action_schemas()
    cmd.schema_service = MagicMock()
    cmd.schema_service.get_action_schema.side_effect = lambda name: schemas.get(name)
    for k, v in extra_attrs.items():
        setattr(cmd, k, v)
    return cmd


# ── DependenciesCommand ─────────────────────────────────────────────


class TestDependenciesCommandOutput:
    def test_output_json(self, capsys):
        cmd = _new_cmd(DependenciesCommand, action_filter=None)
        dep_info = _make_dependency_info()
        cmd._output_json(dep_info)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["workflow"] == "test_wf"
        assert "extract" in data["actions"]
        assert "summarize" in data["actions"]

    def test_output_rich_renders_table(self):
        cmd = _new_cmd(DependenciesCommand, action_filter=None)
        dep_info = _make_dependency_info()
        execution_order = ["extract", "summarize"]

        cmd._output_rich(dep_info, execution_order)

        output = cmd.console.file.getvalue()
        assert "extract" in output
        assert "summarize" in output
        # "source data" is the label for actions with no inputs (type=Source)
        assert "source data" in output


# ── GraphCommand ─────────────────────────────────────────────────────


class TestGraphCommandOutput:
    def test_output_json(self, capsys):
        cmd = _new_cmd(GraphCommand)
        wf = _make_workflow_mock()
        dep_info = _make_dependency_info()
        execution_order = ["extract", "summarize"]

        cmd._output_json(wf, dep_info, execution_order)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["workflow"] == "test_wf"
        assert data["execution_order"] == ["extract", "summarize"]
        assert "extract" in data["actions"]
        assert data["actions"]["extract"]["type"] == "Source"
        assert "output_fields" in data["actions"]["summarize"]

    def test_output_rich_renders_tree(self):
        cmd = _new_cmd(GraphCommand)
        wf = _make_workflow_mock()
        dep_info = _make_dependency_info()
        execution_order = ["extract", "summarize"]

        cmd._output_rich(wf, dep_info, execution_order)

        output = cmd.console.file.getvalue()
        assert "extract" in output
        assert "summarize" in output
        assert "source data" in output


# ── ActionCommand ────────────────────────────────────────────────────


class TestActionCommandOutput:
    def test_output_json(self, capsys):
        cmd = _new_cmd(ActionCommand, action_name="summarize")
        action_config = _make_workflow_mock().action_configs["summarize"]
        info = _make_dependency_info()["summarize"]

        cmd._output_json(action_config, info)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["action"] == "summarize"
        assert data["workflow"] == "test_wf"
        assert data["kind"] == "llm"
        assert data["model"] == "gpt-4"
        assert "summary" in data["output_fields"]
        assert "score" in data["output_fields"]

    def test_output_rich_renders_panel_and_tree(self):
        cmd = _new_cmd(ActionCommand, action_name="summarize")
        action_config = _make_workflow_mock().action_configs["summarize"]
        info = _make_dependency_info()["summarize"]

        cmd._output_rich(action_config, info)

        output = cmd.console.file.getvalue()
        assert "summarize" in output
        assert "llm" in output
        assert "gpt-4" in output

    def test_output_rich_source_action(self):
        """Source action (no inputs) renders 'source data' label."""
        cmd = _new_cmd(ActionCommand, action_name="extract")
        action_config = _make_workflow_mock().action_configs["extract"]
        info = _make_dependency_info()["extract"]

        cmd._output_rich(action_config, info)

        output = cmd.console.file.getvalue()
        assert "source data" in output


# ── ContextCommand ───────────────────────────────────────────────────


class TestContextCommandOutput:
    def _make_context_data(self):
        return {
            "action_name": "summarize",
            "workflow": "test_wf",
            "namespaces": {
                "source": ["[from source data]"],
                "extract": ["fact"],
                "version": ["i", "idx", "length", "first", "last"],
                "workflow": ["name", "run_id"],
            },
            "context_scope": {
                "observe": ["extract.fact"],
                "passthrough": [],
                "drop": [],
            },
            "dependencies": {
                "input_sources": ["extract"],
                "context_sources": [],
            },
            "output_fields": ["summary", "score"],
            "total_template_variables": 9,
        }

    def test_output_json(self, capsys):
        cmd = _new_cmd(ContextCommand, target_action_name="summarize")
        context_data = self._make_context_data()

        cmd._output_json(context_data)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["action_name"] == "summarize"
        assert "extract" in data["namespaces"]
        assert data["total_template_variables"] == 9

    def test_output_rich_renders_namespaces_and_scope(self):
        cmd = _new_cmd(ContextCommand, target_action_name="summarize")
        context_data = self._make_context_data()

        cmd._output_rich(context_data)

        output = cmd.console.file.getvalue()
        assert "summarize" in output
        assert "extract" in output
        assert "observe" in output

    def test_output_rich_no_scope_no_crash(self):
        """Context with empty scope renders without error."""
        cmd = _new_cmd(ContextCommand, target_action_name="extract")
        context_data = {
            "action_name": "extract",
            "workflow": "test_wf",
            "namespaces": {"source": ["[from source data]"]},
            "context_scope": {"observe": [], "passthrough": [], "drop": []},
            "dependencies": {"input_sources": [], "context_sources": []},
            "output_fields": ["fact"],
            "total_template_variables": 1,
        }

        cmd._output_rich(context_data)

        output = cmd.console.file.getvalue()
        assert "extract" in output


# ── Regression: spec= mock enforces attribute names (B-1/B-5) ────────────────


class TestWorkflowMockSpecEnforcement:
    """MagicMock(spec=AgentWorkflow) raises AttributeError on .agent_configs access."""

    def test_spec_mock_raises_on_old_attribute(self):
        wf = _make_workflow_mock()
        with pytest.raises(AttributeError):
            _ = wf.agent_configs  # renamed to action_configs; spec enforces this
        # Durable guard: fails immediately if agent_configs is ever re-added as an alias
        assert not hasattr(AgentWorkflow, "agent_configs")

    def test_spec_mock_allows_new_attribute(self):
        wf = _make_workflow_mock()
        assert wf.action_configs is not None
