"""Tests for ProcessorErrorHandlerMixin."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import (
    FileLoadError,
    FileWriteError,
    ProcessingError,
    TransformationError,
    ValidationError,
)
from agent_actions.errors.base import AgentActionsError
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin

# ---------------------------------------------------------------------------
# Concrete test harness
# ---------------------------------------------------------------------------


class _StubProcessor(ProcessorErrorHandlerMixin):
    """Minimal concrete class that inherits the mixin for testing."""

    def __init__(self, agent_name=None, agent_config=None):
        if agent_name is not None:
            self.agent_name = agent_name
        if agent_config is not None:
            self.agent_config = agent_config


class _StubProcessorWithAttrs(ProcessorErrorHandlerMixin):
    """Processor that always has agent_name and agent_config."""

    def __init__(self):
        self.agent_name = "my_agent"
        self.agent_config = {"type": "llm"}


# ---------------------------------------------------------------------------
# get_error_context
# ---------------------------------------------------------------------------


class TestGetErrorContext:
    """Tests for the get_error_context helper."""

    def test_basic_context(self):
        proc = _StubProcessor()
        ctx = proc.get_error_context("load_data")
        assert ctx["processor"] == "_StubProcessor"
        assert ctx["operation"] == "load_data"
        assert "timestamp" in ctx

    def test_file_path_string(self):
        proc = _StubProcessor()
        ctx = proc.get_error_context("read", file_path="/tmp/data.json")
        assert ctx["file_path"] == "/tmp/data.json"

    def test_file_path_pathlib(self):
        proc = _StubProcessor()
        ctx = proc.get_error_context("read", file_path=Path("/tmp/data.json"))
        assert ctx["file_path"] == "/tmp/data.json"

    def test_no_file_path_when_none(self):
        proc = _StubProcessor()
        ctx = proc.get_error_context("op", file_path=None)
        assert "file_path" not in ctx

    def test_agent_name_included(self):
        proc = _StubProcessor(agent_name="test_agent")
        ctx = proc.get_error_context("op")
        assert ctx["agent_name"] == "test_agent"

    def test_agent_config_type(self):
        proc = _StubProcessorWithAttrs()
        ctx = proc.get_error_context("op")
        assert ctx["agent_type"] == "llm"

    def test_agent_config_type_defaults_to_unknown(self):
        proc = _StubProcessor(agent_config={})
        ctx = proc.get_error_context("op")
        assert ctx["agent_type"] == "unknown"

    def test_extra_kwargs_merged(self):
        proc = _StubProcessor()
        ctx = proc.get_error_context("op", custom_key="custom_value")
        assert ctx["custom_key"] == "custom_value"

    def test_no_agent_attrs_no_keys(self):
        """When the mixin host has no agent_name/agent_config, those keys are absent."""
        proc = _StubProcessor()
        ctx = proc.get_error_context("op")
        assert "agent_name" not in ctx
        assert "agent_type" not in ctx


# ---------------------------------------------------------------------------
# Logger property
# ---------------------------------------------------------------------------


class TestLoggerProperty:
    def test_lazy_logger_creation(self):
        proc = _StubProcessor()
        logger = proc.logger
        assert logger.name == proc.__class__.__module__

    def test_logger_setter(self):
        import logging

        proc = _StubProcessor()
        custom = logging.getLogger("custom_test")
        proc.logger = custom
        assert proc.logger is custom


# ---------------------------------------------------------------------------
# handle_processing_error
# ---------------------------------------------------------------------------


class TestHandleProcessingError:
    """Tests for handle_processing_error."""

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_raises_processing_error_by_default(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("boom")
        with pytest.raises(ProcessingError, match="load failed: boom") as exc_info:
            proc.handle_processing_error(cause, "load")
        assert exc_info.value.__cause__ is cause

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_raises_custom_error_type(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("bad data")
        with pytest.raises(ValidationError, match="validate failed: bad data"):
            proc.handle_processing_error(cause, "validate", error_type=ValidationError)

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_no_reraise_when_false(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("minor")
        # Should NOT raise
        proc.handle_processing_error(cause, "optional_op", reraise=False)

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_fires_data_loading_event_for_generic_error(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("generic")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "load", file_path="/tmp/f.txt")

        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events.validation_events import DataLoadingErrorEvent

        assert isinstance(event, DataLoadingErrorEvent)
        assert event.file_path == "/tmp/f.txt"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_fires_data_parsing_event_for_json_error(self, mock_fire):
        proc = _StubProcessor()
        cause = json.JSONDecodeError("Expecting value", "doc", 0)
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "parse")

        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events.validation_events import DataParsingErrorEvent

        assert isinstance(event, DataParsingErrorEvent)
        assert event.format == "json"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_context_kwargs_passed_through(self, mock_fire):
        """Extra kwargs appear in the error context built by get_error_context."""
        proc = _StubProcessor()
        cause = RuntimeError("x")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "op", extra="data")
        # If we got here without TypeError, the kwargs flowed through fine.

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_error_chain_preserved(self, mock_fire):
        proc = _StubProcessor()
        original = ValueError("root cause")
        with pytest.raises(ProcessingError) as exc_info:
            proc.handle_processing_error(original, "transform")
        assert exc_info.value.__cause__ is original

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_agent_actions_error_uses_detailed_str(self, mock_fire):
        """When the cause is an AgentActionsError, its detailed_str() is used in the message."""
        proc = _StubProcessor()
        cause = AgentActionsError("inner fail", context={"key": "val"})
        with pytest.raises(ProcessingError, match="inner fail"):
            proc.handle_processing_error(cause, "op")


# ---------------------------------------------------------------------------
# handle_validation_error
# ---------------------------------------------------------------------------


class TestHandleValidationError:
    """Tests for handle_validation_error."""

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_raises_validation_error(self, mock_fire):
        proc = _StubProcessor()
        cause = ValueError("bad field")
        with pytest.raises(ValidationError, match="Validation of schema"):
            proc.handle_validation_error(cause, "schema")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_chain_preserves_cause(self, mock_fire):
        proc = _StubProcessor()
        cause = TypeError("wrong type")
        with pytest.raises(ValidationError) as exc_info:
            proc.handle_validation_error(cause, "field_x")
        assert exc_info.value.__cause__ is cause

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_file_path_forwarded(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("fail")
        with pytest.raises(ValidationError):
            proc.handle_validation_error(cause, "config", file_path="/etc/config.yaml")
        # Verify the event received the file_path
        event = mock_fire.call_args[0][0]
        assert event.file_path == "/etc/config.yaml"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_with_validation_error_as_cause(self, mock_fire):
        """TypeVar bound verified: ValidationError input is wrapped correctly."""
        proc = _StubProcessor()
        cause = ValidationError("original validation issue")
        with pytest.raises(ValidationError, match="Validation of data"):
            proc.handle_validation_error(cause, "data")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_extra_context_kwargs(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("err")
        with pytest.raises(ValidationError):
            proc.handle_validation_error(cause, "target", severity="high")


# ---------------------------------------------------------------------------
# handle_file_error
# ---------------------------------------------------------------------------


class TestHandleFileError:
    """Tests for handle_file_error."""

    @patch("agent_actions.processing.error_handling.fire_event")
    @pytest.mark.parametrize("operation", ["read", "load", "open"])
    def test_read_operations_raise_file_load_error(self, mock_fire, operation):
        proc = _StubProcessor()
        cause = OSError("permission denied")
        with pytest.raises(FileLoadError, match=f"File {operation} failed"):
            proc.handle_file_error(cause, operation, "/tmp/data.csv")

    @patch("agent_actions.processing.error_handling.fire_event")
    @pytest.mark.parametrize("operation", ["write", "save", "create"])
    def test_write_operations_raise_file_write_error(self, mock_fire, operation):
        proc = _StubProcessor()
        cause = OSError("disk full")
        with pytest.raises(FileWriteError, match=f"File {operation} failed"):
            proc.handle_file_error(cause, operation, "/tmp/out.csv")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_unknown_operation_raises_processing_error(self, mock_fire):
        """Operations not in the read/write lists fall back to ProcessingError."""
        proc = _StubProcessor()
        cause = OSError("???")
        with pytest.raises(ProcessingError, match="File rename failed"):
            proc.handle_file_error(cause, "rename", "/tmp/old.csv")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_chain_preserves_cause(self, mock_fire):
        proc = _StubProcessor()
        cause = PermissionError("no access")
        with pytest.raises(FileLoadError) as exc_info:
            proc.handle_file_error(cause, "read", "/tmp/secret.json")
        assert exc_info.value.__cause__ is cause

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_file_path_as_pathlib(self, mock_fire):
        proc = _StubProcessor()
        cause = OSError("not found")
        with pytest.raises(FileLoadError):
            proc.handle_file_error(cause, "load", Path("/tmp/missing.json"))

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_with_file_load_error_as_cause(self, mock_fire):
        """TypeVar bound verified: FileLoadError input wraps correctly."""
        proc = _StubProcessor()
        cause = FileLoadError("nested load failure")
        with pytest.raises(FileLoadError, match="File read failed"):
            proc.handle_file_error(cause, "read", "/tmp/file.txt")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_with_file_write_error_as_cause(self, mock_fire):
        """TypeVar bound verified: FileWriteError input wraps correctly."""
        proc = _StubProcessor()
        cause = FileWriteError("nested write failure")
        with pytest.raises(FileWriteError, match="File write failed"):
            proc.handle_file_error(cause, "write", "/tmp/file.txt")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_case_insensitive_operation_matching(self, mock_fire):
        """Operation matching is case-insensitive (lowered before comparison)."""
        proc = _StubProcessor()
        cause = OSError("err")
        with pytest.raises(FileLoadError):
            proc.handle_file_error(cause, "Read", "/tmp/data.json")
        with pytest.raises(FileWriteError):
            proc.handle_file_error(cause, "WRITE", "/tmp/data.json")


# ---------------------------------------------------------------------------
# handle_transformation_error
# ---------------------------------------------------------------------------


class TestHandleTransformationError:
    """Tests for handle_transformation_error."""

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_raises_transformation_error(self, mock_fire):
        proc = _StubProcessor()
        cause = ValueError("incompatible types")
        with pytest.raises(
            TransformationError,
            match="Transformation from dict to list failed",
        ):
            proc.handle_transformation_error(cause, "dict", "list")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_chain_preserves_cause(self, mock_fire):
        proc = _StubProcessor()
        cause = KeyError("missing_key")
        with pytest.raises(TransformationError) as exc_info:
            proc.handle_transformation_error(cause, "raw", "processed")
        assert exc_info.value.__cause__ is cause

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_source_and_target_in_message(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("fail")
        with pytest.raises(TransformationError, match="from csv to json"):
            proc.handle_transformation_error(cause, "csv", "json")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_extra_context_kwargs(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("fail")
        with pytest.raises(TransformationError):
            proc.handle_transformation_error(cause, "a", "b", step="normalize")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_empty_type_strings(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("fail")
        with pytest.raises(TransformationError, match="Transformation from  to "):
            proc.handle_transformation_error(cause, "", "")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Cross-cutting edge cases."""

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_empty_operation_string(self, mock_fire):
        proc = _StubProcessor()
        cause = RuntimeError("x")
        with pytest.raises(ProcessingError, match=" failed: x"):
            proc.handle_processing_error(cause, "")

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_none_file_path_in_context(self, mock_fire):
        """file_path defaults to 'unknown' in event when not supplied."""
        proc = _StubProcessor()
        cause = RuntimeError("x")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "op")
        event = mock_fire.call_args[0][0]
        assert event.file_path == "unknown"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_yaml_error_fires_parsing_event(self, mock_fire):
        import yaml

        proc = _StubProcessor()
        cause = yaml.YAMLError("bad yaml")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "parse")
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events.validation_events import DataParsingErrorEvent

        assert isinstance(event, DataParsingErrorEvent)
        assert event.format == "yaml"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_csv_error_fires_parsing_event(self, mock_fire):
        import csv

        proc = _StubProcessor()
        cause = csv.Error("bad csv")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "parse")
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events.validation_events import DataParsingErrorEvent

        assert isinstance(event, DataParsingErrorEvent)
        assert event.format == "csv"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_xml_parse_error_fires_parsing_event(self, mock_fire):
        from xml.etree.ElementTree import ParseError

        proc = _StubProcessor()
        cause = ParseError("bad xml")
        with pytest.raises(ProcessingError):
            proc.handle_processing_error(cause, "parse")
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events.validation_events import DataParsingErrorEvent

        assert isinstance(event, DataParsingErrorEvent)
        assert event.format == "xml"

    @patch("agent_actions.processing.error_handling.fire_event")
    def test_no_reraise_logs_warning(self, mock_fire):
        """When reraise=False, a warning is logged instead of raising."""
        proc = _StubProcessor()
        cause = RuntimeError("soft fail")
        with patch.object(proc.logger, "warning") as mock_warn:
            proc.handle_processing_error(cause, "soft_op", reraise=False)
            mock_warn.assert_called_once()
            assert "soft_op" in mock_warn.call_args[0][0] % mock_warn.call_args[0][1:]
