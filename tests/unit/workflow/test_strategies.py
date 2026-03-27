"""Tests for ActionStrategy hierarchy (InitialStrategy, StandardStrategy)."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.strategies import (
    ActionStrategy,
    InitialStrategy,
    StandardStrategy,
    StrategyExecutionParams,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _make_params(**overrides):
    """Build a StrategyExecutionParams with sensible defaults."""
    defaults = {
        "action_config": {"agent_type": "test", "model_vendor": "openai"},
        "action_name": "test_action",
        "file_path": "/data/input/file.json",
        "base_directory": "/data/input",
        "output_directory": "/data/output",
        "idx": 0,
        "action_configs": None,
        "storage_backend": None,
        "source_relative_path": None,
        "data": None,
    }
    defaults.update(overrides)
    return StrategyExecutionParams(**defaults)


# ── StrategyExecutionParams dataclass ──────────────────────────────────


class TestStrategyExecutionParams:
    """Basic dataclass contract tests."""

    def test_defaults(self):
        params = _make_params()
        assert params.action_name == "test_action"
        assert params.action_configs is None
        assert params.storage_backend is None
        assert params.source_relative_path is None
        assert params.data is None

    def test_optional_fields(self):
        backend = MagicMock()
        params = _make_params(
            action_configs={"a": {}},
            storage_backend=backend,
            source_relative_path="rel/path",
            data=[{"x": 1}],
        )
        assert params.action_configs == {"a": {}}
        assert params.storage_backend is backend
        assert params.source_relative_path == "rel/path"
        assert params.data == [{"x": 1}]


# ── ActionStrategy base class ──────────────────────────────────────────


class TestActionStrategyBase:
    """Tests for the abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            ActionStrategy()

    def test_repr_includes_class_name(self):
        strategy = InitialStrategy(processor_factory=None)
        assert "InitialStrategy" in repr(strategy)

    def test_repr_includes_processor_factory(self):
        factory = MagicMock()
        strategy = StandardStrategy(processor_factory=factory)
        r = repr(strategy)
        assert "StandardStrategy" in r
        assert "processor_factory" in r

    def test_execute_generate_target_requires_processor_factory(self):
        """_execute_generate_target should raise RuntimeError when processor_factory is None."""
        strategy = StandardStrategy(processor_factory=None)
        params = _make_params()
        with pytest.raises(RuntimeError, match="requires processor_factory"):
            strategy._execute_generate_target(params)


# ── InitialStrategy ────────────────────────────────────────────────────


class TestInitialStrategy:
    """Tests for the InitialStrategy execute path."""

    @patch("agent_actions.workflow.strategies.process_initial_stage")
    def test_execute_calls_process_initial_stage(self, mock_process):
        mock_process.return_value = "/data/output/file.json"
        strategy = InitialStrategy(processor_factory=None)
        params = _make_params()

        result = strategy.execute(params)

        assert result == "/data/output/file.json"
        mock_process.assert_called_once()

    @patch("agent_actions.workflow.strategies.process_initial_stage")
    def test_execute_passes_correct_context_fields(self, mock_process):
        mock_process.return_value = "/out/file.json"
        backend = MagicMock()
        strategy = InitialStrategy(processor_factory=None)
        params = _make_params(
            action_config={"key": "val"},
            action_name="my_action",
            file_path="/in/data.json",
            base_directory="/in",
            output_directory="/out",
            idx=3,
            storage_backend=backend,
        )

        strategy.execute(params)

        ctx = mock_process.call_args[0][0]
        assert ctx.agent_name == "my_action"
        assert ctx.file_path == "/in/data.json"
        assert ctx.base_directory == "/in"
        assert ctx.output_directory == "/out"
        assert ctx.idx == 3
        assert ctx.storage_backend is backend

    @patch("agent_actions.workflow.strategies.process_initial_stage")
    def test_execute_passes_action_config_as_agent_config(self, mock_process):
        """The InitialStageContext.agent_config should be the action_config dict."""
        mock_process.return_value = "/out/f.json"
        config = {"prompt": "hello", "model_vendor": "openai"}
        strategy = InitialStrategy(processor_factory=None)
        params = _make_params(action_config=config)

        strategy.execute(params)

        ctx = mock_process.call_args[0][0]
        assert ctx.agent_config == config

    def test_equality_same_factory(self):
        factory = MagicMock()
        a = InitialStrategy(processor_factory=factory)
        b = InitialStrategy(processor_factory=factory)
        assert a == b

    def test_equality_different_factory(self):
        a = InitialStrategy(processor_factory=MagicMock())
        b = InitialStrategy(processor_factory=MagicMock())
        assert a != b

    def test_equality_different_type(self):
        a = InitialStrategy(processor_factory=None)
        b = StandardStrategy(processor_factory=None)
        assert a != b


# ── StandardStrategy ───────────────────────────────────────────────────


class TestStandardStrategy:
    """Tests for the StandardStrategy execute path."""

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    def test_execute_calls_pipeline_process(self, mock_create):
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/data/output/file.json"
        mock_create.return_value = mock_pipeline

        factory = MagicMock()
        strategy = StandardStrategy(processor_factory=factory)
        params = _make_params()

        result = strategy.execute(params)

        assert result == "/data/output/file.json"
        mock_pipeline.process.assert_called_once_with(
            params.file_path,
            params.base_directory,
            params.output_directory,
            data=params.data,
        )

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    def test_execute_passes_correct_kwargs_to_pipeline_factory(self, mock_create):
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/out/file.json"
        mock_create.return_value = mock_pipeline

        factory = MagicMock()
        backend = MagicMock()
        strategy = StandardStrategy(processor_factory=factory)
        params = _make_params(
            action_config={"key": "val"},
            action_name="my_action",
            idx=5,
            action_configs={"a": {}, "b": {}},
            storage_backend=backend,
            source_relative_path="rel/path.json",
        )

        strategy.execute(params)

        mock_create.assert_called_once_with(
            action_config={"key": "val"},
            action_name="my_action",
            idx=5,
            processor_factory=factory,
            action_configs={"a": {}, "b": {}},
            storage_backend=backend,
            source_relative_path="rel/path.json",
        )

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    def test_execute_passes_data_to_pipeline_process(self, mock_create):
        """Pre-loaded data should be forwarded to pipeline.process."""
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/out/file.json"
        mock_create.return_value = mock_pipeline

        factory = MagicMock()
        strategy = StandardStrategy(processor_factory=factory)
        pre_loaded = [{"id": 1, "content": "hello"}]
        params = _make_params(data=pre_loaded)

        strategy.execute(params)

        call_kwargs = mock_pipeline.process.call_args[1]
        assert call_kwargs["data"] is pre_loaded

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    def test_execute_passes_none_data_when_not_provided(self, mock_create):
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/out/file.json"
        mock_create.return_value = mock_pipeline

        factory = MagicMock()
        strategy = StandardStrategy(processor_factory=factory)
        params = _make_params()  # data=None by default

        strategy.execute(params)

        call_kwargs = mock_pipeline.process.call_args[1]
        assert call_kwargs["data"] is None

    def test_execute_raises_when_no_processor_factory(self):
        """StandardStrategy.execute should raise RuntimeError if processor_factory is None."""
        strategy = StandardStrategy(processor_factory=None)
        params = _make_params()
        with pytest.raises(RuntimeError, match="requires processor_factory"):
            strategy.execute(params)

    def test_equality_same_factory(self):
        factory = MagicMock()
        a = StandardStrategy(processor_factory=factory)
        b = StandardStrategy(processor_factory=factory)
        assert a == b

    def test_equality_different_factory(self):
        a = StandardStrategy(processor_factory=MagicMock())
        b = StandardStrategy(processor_factory=MagicMock())
        assert a != b

    def test_equality_different_type(self):
        a = StandardStrategy(processor_factory=None)
        b = InitialStrategy(processor_factory=None)
        assert a != b

    def test_equality_with_non_strategy(self):
        a = StandardStrategy(processor_factory=None)
        assert a != "not a strategy"
        assert a != 42
