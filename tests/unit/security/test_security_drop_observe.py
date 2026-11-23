"""Security regression tests for Wave 2 fixes.

Tests critical security paths:
- Drop+observe on same field proves no data leak (M1)
- Atomic write cleanup on failure (C1)
- Batch flush failure preserves queue state (L1)
"""

from unittest.mock import MagicMock

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
        assert "api_key" not in llm_context.get("dep", {}), (
            "Dropped field 'api_key' leaked into llm_context via observe wildcard"
        )
        # Other fields should be present under namespace
        assert "name" in llm_context["dep"]
        assert "value" in llm_context["dep"]

    def test_drop_then_observe_single_field_raises(self):
        """Dropped field raises when observed — secret not leaked, config contradiction caught."""
        import pytest

        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.context.scope_application import apply_context_scope

        field_context = {"dep": {"secret": "hunter2", "public": "hello"}}

        with pytest.raises(ConfigurationError, match="not found in namespace"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.secret"], "observe": ["dep.secret"]},
                action_name="test",
            )


class TestAtomicWriteCleanup:
    """Verify tempfile is cleaned up on write failure."""

    def test_tempfile_cleaned_on_serialization_error(self, tmp_path):
        from agent_actions.errors import FileWriteError
        from agent_actions.output.writer import FileWriter

        output_file = tmp_path / "output.json"
        writer = FileWriter(str(output_file))

        # Object that can't be serialized — atomic_json_write wraps the
        # JSON TypeError as OSError, which FileWriter must surface as
        # FileWriteError (the canonical write-failure type).
        class Unserializable:
            pass

        with pytest.raises(FileWriteError):
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
