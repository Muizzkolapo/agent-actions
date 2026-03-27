"""Security regression tests for Wave 2 fixes.

Tests critical security paths:
- Drop+observe on same field proves no data leak (M1)
- Path traversal rejection in tools_resolver (J4)
- Atomic write cleanup on failure (C1)
- Batch flush failure preserves queue state (L1)
"""

from unittest.mock import MagicMock, patch

import pytest


class TestDropObserveNoLeak:
    """Verify that dropping a field prevents it from leaking into llm_context via observe."""

    def test_drop_then_observe_wildcard_excludes_dropped_field(self):
        """If dep.api_key is dropped, observe: [dep.*] must NOT include api_key in llm_context."""
        from agent_actions.prompt.context.scope_application import apply_context_scope

        field_context = {"dep": {"api_key": "sk-secret-123", "name": "test", "value": "safe_data"}}
        context_scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.*"],
        }

        prompt_context, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope=context_scope,
            action_name="test_action",
        )

        # api_key must NOT be in llm_context
        assert "api_key" not in llm_context, (
            "Dropped field 'api_key' leaked into llm_context via observe wildcard"
        )
        # Other fields should be present
        assert "name" in llm_context
        assert "value" in llm_context

    def test_drop_then_observe_single_field_raises(self):
        """Explicitly observing a dropped field must raise — not silently skip."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.context.scope_application import apply_context_scope

        field_context = {"dep": {"secret": "hunter2", "public": "hello"}}

        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.secret"], "observe": ["dep.secret"]},
                action_name="test",
            )


class TestPathTraversalRejection:
    """Verify tools_resolver rejects path traversal attempts."""

    def test_dotdot_in_path_raises(self, tmp_path):
        """.. traversal that resolves outside project root raises ConfigValidationError."""
        from agent_actions.errors import ConfigValidationError
        from agent_actions.utils.tools_resolver import resolve_tools_path

        # project_dir is the controlled project root; outside_dir is a sibling
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        evil_file = outside_dir / "evil.yaml"
        evil_file.write_text("module_path: evil")

        config = {
            "tools": [
                {
                    "type": "function",
                    "function": {"file": str(evil_file)},
                }
            ]
        }
        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=project_dir,
        ):
            with pytest.raises(ConfigValidationError, match="path traversal"):
                resolve_tools_path(config)

    def test_normal_path_is_accepted(self, tmp_path):
        from unittest.mock import patch

        from agent_actions.utils.tools_resolver import resolve_tools_path

        tool_file = tmp_path / "tool_config.yaml"
        tool_file.write_text("module_path: my_module\n")

        config = {
            "tools": [
                {
                    "type": "function",
                    "function": {"file": str(tool_file)},
                }
            ]
        }
        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=tmp_path,
        ):
            result = resolve_tools_path(config)
        assert result == "my_module"


class TestAtomicWriteCleanup:
    """Verify tempfile is cleaned up on write failure."""

    def test_tempfile_cleaned_on_serialization_error(self, tmp_path):
        from agent_actions.errors import ProcessingError
        from agent_actions.output.writer import FileWriter

        output_file = tmp_path / "output.json"
        writer = FileWriter(str(output_file))

        # Object that can't be serialized
        class Unserializable:
            pass

        with pytest.raises(ProcessingError):
            writer.write_staging(Unserializable())

        # No leftover .tmp files (cleaned up in except block)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
        # Original file should not exist (atomic write never completed)
        assert not output_file.exists()


class TestBatchFlushPreservesQueueOnFailure:
    """Verify batch flush preserves queue state when submission fails."""

    def test_queue_preserved_on_submit_failure(self):
        from agent_actions.processing.invocation.batch import BatchStrategy

        strategy = BatchStrategy.__new__(BatchStrategy)
        strategy._queued = [MagicMock(), MagicMock()]
        strategy._context_map = {"a": {}, "b": {}}
        strategy._agent_config = {"model_vendor": "openai"}
        strategy._provider = MagicMock()
        strategy._provider.prepare_tasks.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="API down"):
            strategy.flush(batch_name="test", output_directory="/tmp")

        # Queue should NOT be cleared on failure
        assert len(strategy._queued) == 2
        assert len(strategy._context_map) == 2
        assert strategy._agent_config is not None
