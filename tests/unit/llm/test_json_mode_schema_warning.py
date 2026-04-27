"""Tests for json_mode=false + schema mismatch warnings.

Validates that:
- Preflight: static analyzer warns when json_mode=false + schema defined
- Runtime: BaseClient.invoke() logs warning when schema is dropped
- Runtime: BaseBatchClient.prepare_tasks() logs warning when schema is dropped
- No false positives for valid configs
"""

from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchTask
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_workflow(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal workflow config for static analysis."""
    return {"actions": actions}


def _make_action(
    name: str = "test_action",
    json_mode: bool = True,
    schema: dict | str | None = None,
    schema_name: str | None = None,
    output_schema: dict | None = None,
    kind: str = "llm",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "json_mode": json_mode,
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "api_key": "${OPENAI_API_KEY}",
    }
    if schema is not None:
        action["schema"] = schema
    if schema_name is not None:
        action["schema_name"] = schema_name
    if output_schema is not None:
        action["output_schema"] = output_schema
    if depends_on is not None:
        action["depends_on"] = depends_on
    return action


class ConcreteClient(BaseClient):
    """Minimal concrete client for testing invoke() dispatch."""

    CAPABILITIES = {"json_mode": True}

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        return [{"content": "json"}]

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        return [{"content": "text"}]


class ConcreteBatchClient(BaseBatchClient):
    """Minimal concrete batch client for testing prepare_tasks()."""

    def _get_default_model(self) -> str:
        return "gpt-4"

    def format_task_for_provider(self, batch_task: BatchTask, schema=None) -> dict:
        return {"id": batch_task.custom_id, "schema": schema}

    def _fetch_status(self, batch_id: str) -> str:
        return "completed"

    def _normalize_status(self, raw_status: str) -> str:
        return raw_status

    def _extract_error_from_response(self, raw_response) -> str | None:
        return None

    def _extract_content_from_response(self, raw_response) -> Any:
        return raw_response

    def _extract_metadata_from_response(self, raw_response) -> dict:
        return {}

    def _extract_usage_from_response(self, raw_response) -> dict | None:
        return None

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        return b""

    def _get_result_file_name(self, batch_id: str) -> str:
        return f"{batch_id}.jsonl"

    def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
        return batch_dir / "input.jsonl"

    def _submit_to_provider_api(self, input_file, batch_name):
        return ("batch_123", "submitted")


# ══════════════════════════════════════════════════════════════════════
# Preflight: static analyzer warnings
# ══════════════════════════════════════════════════════════════════════


class TestPreflightJsonModeSchemaWarning:
    """Static analyzer warns when json_mode=false + schema is defined."""

    def test_json_mode_false_with_schema_warns(self):
        """json_mode=false + schema dict → warning."""
        action = _make_action(
            json_mode=False,
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 1
        assert "schema will be compiled but not sent" in json_mode_warnings[0].message

    def test_json_mode_false_with_schema_name_warns(self):
        """json_mode=false + schema_name → warning."""
        action = _make_action(json_mode=False, schema_name="summary_schema")
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 1

    def test_json_mode_false_with_output_schema_warns(self):
        """json_mode=false + output_schema → warning."""
        action = _make_action(
            json_mode=False,
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        )
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 1

    def test_json_mode_true_with_schema_no_warning(self):
        """json_mode=true + schema → no warning (correct config)."""
        action = _make_action(
            json_mode=True,
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 0

    def test_json_mode_false_no_schema_no_warning(self):
        """json_mode=false + no schema → no warning (valid text output)."""
        action = _make_action(json_mode=False)
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 0

    def test_tool_action_skipped(self):
        """Tool actions don't get json_mode/schema check."""
        action = _make_action(
            kind="tool",
            json_mode=False,
            schema={"type": "object"},
        )
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 0

    def test_warning_is_non_blocking(self):
        """json_mode mismatch warning does not block execution."""
        action = _make_action(
            json_mode=False,
            schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        workflow = _make_workflow([action])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        # Warning exists but result is still valid (not blocked)
        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        assert len(json_mode_warnings) == 1
        # No errors from the mismatch check itself
        json_mode_errors = [e for e in result.errors if "json_mode" in e.message]
        assert len(json_mode_errors) == 0

    def test_multiple_actions_each_warned(self):
        """Each misconfigured action gets its own warning."""
        a1 = _make_action(name="action_a", json_mode=False, schema={"type": "object"})
        a2 = _make_action(name="action_b", json_mode=False, schema_name="schema_b")
        a3 = _make_action(name="action_c", json_mode=True, schema={"type": "object"})
        workflow = _make_workflow([a1, a2, a3])
        result = WorkflowStaticAnalyzer(workflow).analyze()

        json_mode_warnings = [w for w in result.warnings if "json_mode=false" in w.message]
        warned_names = {w.location.agent_name for w in json_mode_warnings}
        assert warned_names == {"action_a", "action_b"}


# ══════════════════════════════════════════════════════════════════════
# Runtime: BaseClient.invoke() warning
# ══════════════════════════════════════════════════════════════════════


class TestRuntimeInvokeWarning:
    """BaseClient.invoke() logs warning when schema is dropped."""

    @patch("agent_actions.llm.providers.client_base.logger")
    @patch.object(BaseClient, "get_api_key", return_value="sk-test")
    def test_invoke_json_false_with_schema_warns(self, _mock_key, mock_logger):
        """invoke() with json_mode=false + schema logs a warning."""
        config = {"json_mode": False, "agent_type": "summarize"}
        schema = {"type": "object", "properties": {"summary": {"type": "string"}}}

        ConcreteClient.invoke(config, "prompt", {}, schema)

        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert "json_mode=false" in msg
        assert "summarize" in mock_logger.warning.call_args[0][1]

    @patch("agent_actions.llm.providers.client_base.logger")
    @patch.object(BaseClient, "get_api_key", return_value="sk-test")
    def test_invoke_json_false_no_schema_no_warning(self, _mock_key, mock_logger):
        """invoke() with json_mode=false + no schema → no warning."""
        config = {"json_mode": False, "agent_type": "summarize"}

        ConcreteClient.invoke(config, "prompt", {}, None)

        mock_logger.warning.assert_not_called()

    @patch("agent_actions.llm.providers.client_base.logger")
    @patch.object(BaseClient, "get_api_key", return_value="sk-test")
    def test_invoke_json_true_with_schema_no_warning(self, _mock_key, mock_logger):
        """invoke() with json_mode=true + schema → no warning (normal path)."""
        config = {"json_mode": True, "agent_type": "summarize"}
        schema = {"type": "object"}

        ConcreteClient.invoke(config, "prompt", {}, schema)

        mock_logger.warning.assert_not_called()

    @patch.object(BaseClient, "get_api_key", return_value="sk-test")
    def test_invoke_still_returns_result(self, _mock_key):
        """invoke() still calls call_non_json and returns result even with warning."""
        config = {"json_mode": False, "agent_type": "summarize"}
        schema = {"type": "object"}

        result = ConcreteClient.invoke(config, "prompt", {}, schema)
        assert result == [{"content": "text"}]


# ══════════════════════════════════════════════════════════════════════
# Runtime: BaseBatchClient.prepare_tasks() warning
# ══════════════════════════════════════════════════════════════════════


class TestRuntimeBatchWarning:
    """BaseBatchClient.prepare_tasks() logs warning when schema is dropped."""

    @patch("agent_actions.llm.providers.batch_base.logger")
    def test_batch_json_false_with_compiled_schema_warns(self, mock_logger):
        """prepare_tasks() with json_mode=false + compiled_schema logs warning."""
        config = {
            "json_mode": False,
            "compiled_schema": {"type": "object"},
            "agent_type": "summarize",
            "model_name": "gpt-4",
        }
        data = [{"target_id": "row1", "content": {"text": "hello"}}]

        client = ConcreteBatchClient()
        tasks = client.prepare_tasks(data, config)

        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert "json_mode=false" in msg
        # Schema should be None in formatted task (not forwarded)
        assert tasks[0]["schema"] is None

    @patch("agent_actions.llm.providers.batch_base.logger")
    def test_batch_json_false_no_schema_no_warning(self, mock_logger):
        """prepare_tasks() with json_mode=false + no schema → no warning."""
        config = {
            "json_mode": False,
            "agent_type": "summarize",
            "model_name": "gpt-4",
        }
        data = [{"target_id": "row1", "content": {"text": "hello"}}]

        client = ConcreteBatchClient()
        client.prepare_tasks(data, config)

        mock_logger.warning.assert_not_called()

    @patch("agent_actions.llm.providers.batch_base.logger")
    def test_batch_json_true_with_schema_no_warning(self, mock_logger):
        """prepare_tasks() with json_mode=true + schema → no warning."""
        config = {
            "json_mode": True,
            "compiled_schema": {"type": "object"},
            "agent_type": "summarize",
            "model_name": "gpt-4",
        }
        data = [{"target_id": "row1", "content": {"text": "hello"}}]

        client = ConcreteBatchClient()
        tasks = client.prepare_tasks(data, config)

        mock_logger.warning.assert_not_called()
        # Schema IS forwarded when json_mode=true
        assert tasks[0]["schema"] == {"type": "object"}


# ══════════════════════════════════════════════════════════════════════
# Runtime: BaseBatchClient.prepare_tasks() content key enforcement
# ══════════════════════════════════════════════════════════════════════


class TestPrepareTasksContentKeyRequired:
    """prepare_tasks() raises ValueError when a record lacks 'content'."""

    def test_missing_content_key_raises(self):
        """Record without 'content' key raises ValueError with target_id in message."""
        config = {"json_mode": False, "model_name": "gpt-4"}
        data = [{"target_id": "row-1", "score": 90}]

        client = ConcreteBatchClient()
        with pytest.raises(ValueError, match="row-1") as exc_info:
            client.prepare_tasks(data, config)

        assert "missing 'content' key" in str(exc_info.value)

    def test_missing_content_key_falls_back_to_id(self):
        """Error message uses 'id' when 'target_id' absent."""
        config = {"json_mode": False, "model_name": "gpt-4"}
        data = [{"id": "rec-42", "score": 90}]

        client = ConcreteBatchClient()
        with pytest.raises(ValueError, match="rec-42"):
            client.prepare_tasks(data, config)

    def test_missing_content_key_no_identifier(self):
        """Error message shows '?' when record has no target_id or id."""
        config = {"json_mode": False, "model_name": "gpt-4"}
        data = [{"score": 90}]

        client = ConcreteBatchClient()
        with pytest.raises(ValueError, match=r"\?"):
            client.prepare_tasks(data, config)
