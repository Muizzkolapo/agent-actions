"""Wave 9 Group E regression tests — LLM batch service P1 fixes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.services.submission import BatchSubmissionService

# ---------------------------------------------------------------------------
# E-1  ·  submission.py — datetime.now() → datetime.now(UTC)
# ---------------------------------------------------------------------------


class TestBatchEntryTimestampIsUTCAware:
    """E-1 — datetime.now(UTC) is used — timestamp is timezone-aware."""

    def test_submission_module_imports_utc(self):
        """UTC must be importable via the submission module (proves the import was added)."""
        import agent_actions.llm.batch.services.submission as submission_mod

        assert hasattr(submission_mod, "UTC"), "submission module must import UTC from datetime"

    def test_utc_isoformat_is_timezone_aware(self):
        """datetime.now(UTC).isoformat() produces a timezone-aware string."""
        ts = datetime.now(UTC).isoformat()
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_batch_job_entry_timestamp_is_utc_aware(self, tmp_path):
        """BatchJobEntry.timestamp set during _submit_to_provider is UTC-aware."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry

        captured_entries: list[BatchJobEntry] = []

        mock_registry = MagicMock()
        mock_registry.save_batch_job.side_effect = lambda key, entry: captured_entries.append(entry)

        svc = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=mock_registry),
        )
        svc._client_resolver.get_for_config.return_value = MagicMock(
            submit_batch=MagicMock(return_value=("b-001", "in_progress"))
        )

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            svc._submit_to_provider(
                agent_config={"model_vendor": "openai"},
                batch_name="test",
                tasks=[{"custom_id": "r1"}],
                output_directory=str(tmp_path),
            )

        assert captured_entries, "save_batch_job was not called"
        ts = datetime.fromisoformat(captured_entries[0].timestamp)
        assert ts.tzinfo is not None, "BatchJobEntry timestamp must be timezone-aware"
        assert ts.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# E-2  ·  submission.py — check_status raises ConfigurationError when output_directory=None
# ---------------------------------------------------------------------------


class TestCheckStatusGuardsNoneOutputDirectory:
    """E-2 — check_status raises ConfigurationError instead of crashing."""

    def _make_service(self):
        return BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

    def test_none_output_directory_raises_configuration_error(self):
        svc = self._make_service()
        with pytest.raises(ConfigurationError, match="output_directory"):
            svc.check_status("batch-xyz", output_directory=None)

    def test_valid_output_directory_does_not_raise(self, tmp_path):
        svc = self._make_service()
        svc._client_resolver.get_for_batch_id.return_value = MagicMock(
            check_status=MagicMock(return_value="completed")
        )
        svc._registry_manager_factory.return_value = MagicMock()
        with patch("agent_actions.llm.batch.services.submission.fire_event"):
            result = svc.check_status("batch-xyz", output_directory=str(tmp_path))
        assert result == "completed"


# ---------------------------------------------------------------------------
# E-3  ·  batch_client_resolver.py — ConfigurationError not double-wrapped
# ---------------------------------------------------------------------------


class TestBatchClientResolverNoDoubleWrap:
    """E-3 — ConfigurationError from validate_config() propagates without double-wrapping."""

    def test_configuration_error_propagates_unchanged(self):
        """ConfigurationError raised by client.validate_config() must not be
        wrapped in another ConfigurationError."""
        resolver = BatchClientResolver(client_cache={}, default_client=None)

        mock_client = MagicMock()
        mock_client.validate_config.return_value = (False, "bad config")

        with (
            patch(
                "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory.create_client",
                return_value=mock_client,
            ),
            patch("agent_actions.llm.batch.infrastructure.batch_client_resolver.fire_event"),
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                resolver.get_for_config({"model_vendor": "openai", "model_name": "gpt-4"})

        err = exc_info.value
        # Double-wrapping produces a message starting with "Failed to create client for…"
        # Check the error message itself, not the cause (which is None when re-raised directly).
        assert "Failed to create client for" not in str(err), (
            "ConfigurationError was double-wrapped — message contains outer wrapper text"
        )

    def test_create_client_raises_configuration_error_directly(self):
        """ConfigurationError raised by create_client() itself must also propagate unchanged."""
        resolver = BatchClientResolver(client_cache={}, default_client=None)

        with (
            patch(
                "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory.create_client",
                side_effect=ConfigurationError("inner error"),
            ),
            patch("agent_actions.llm.batch.infrastructure.batch_client_resolver.fire_event"),
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                resolver.get_for_config({"model_vendor": "openai", "model_name": "gpt-4"})

        assert str(exc_info.value) == "inner error", (
            "ConfigurationError from create_client() must propagate verbatim, not be re-wrapped"
        )

    def test_generic_exception_still_wrapped(self):
        """Non-ConfigurationError exceptions are still wrapped in ConfigurationError."""
        resolver = BatchClientResolver(client_cache={}, default_client=None)

        with (
            patch(
                "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory.create_client",
                side_effect=RuntimeError("network down"),
            ),
            patch("agent_actions.llm.batch.infrastructure.batch_client_resolver.fire_event"),
        ):
            with pytest.raises(ConfigurationError, match="Failed to create client"):
                resolver.get_for_config({"model_vendor": "openai", "model_name": "gpt-4"})


# ---------------------------------------------------------------------------
# E-5  ·  gemini/client.py — response_text guarded with `or ""`
# ---------------------------------------------------------------------------


class TestGeminiNonJsonResponseTextGuard:
    """E-5 — response_temp.text=None doesn't propagate as None to the output."""

    # Patch targets:
    # - set_last_usage and fire_event (LLMResponseEvent) now live in response_builder
    # - fire_event (LLMRequestEvent/LLMErrorEvent) still in gemini.client
    _RB = "agent_actions.output.response.response_builder"
    _GC = "agent_actions.llm.providers.gemini.client"

    def _make_mock_response(self, text):
        mock_response = MagicMock()
        mock_response.text = text
        mock_response.usage_metadata = None
        return mock_response

    def _call_non_json(self, text):
        """Drive GeminiClient.call_non_json with a mocked Gemini SDK response."""
        from agent_actions.llm.providers.gemini.client import GeminiClient

        mock_response = self._make_mock_response(text)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch(
                f"{self._GC}._build_client",
                return_value=mock_client,
            ),
            patch(f"{self._GC}.fire_event"),
            patch(f"{self._RB}.set_last_usage"),
            patch(f"{self._RB}.fire_event"),
        ):
            return GeminiClient.call_non_json(
                "fake-api-key",
                {"model_name": "gemini-1.5-pro", "output_field": "raw_response"},
                "Summarise the text",
                "some context",
            )

    def test_none_response_text_becomes_empty_string(self):
        """call_non_json with response.text=None must return "" in the output record."""
        result = self._call_non_json(text=None)
        assert result == [{"raw_response": ""}], (
            "None text must produce empty string in output record, not None"
        )

    def test_non_none_text_preserved(self):
        """call_non_json with non-None text must return it unchanged."""
        result = self._call_non_json(text="hello world")
        assert result == [{"raw_response": "hello world"}]

    def test_call_json_passes_empty_string_not_none_to_parser(self):
        """call_json with response.text=None must pass "" to parse_json_response, not None."""
        from agent_actions.llm.providers.gemini.client import GeminiClient

        mock_response = self._make_mock_response(text=None)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        captured: list[str] = []

        def capture_parse(response_content, **kwargs):
            captured.append(response_content)
            return [{}]

        with (
            patch(
                f"{self._GC}._build_client",
                return_value=mock_client,
            ),
            patch(f"{self._GC}.fire_event"),
            patch(f"{self._RB}.set_last_usage"),
            patch(f"{self._RB}.fire_event"),
            patch.object(GeminiClient, "parse_json_response", side_effect=capture_parse),
        ):
            GeminiClient.call_json(
                "fake-api-key",
                {"model_name": "gemini-1.5-pro"},
                "Classify the text",
                "some context",
                '{"label": "string"}',
            )

        assert captured, "parse_json_response was not called"
        assert captured[0] == "", (
            "call_json must pass '' (not None) to parse_json_response when response.text is None"
        )


# ---------------------------------------------------------------------------
# E-6  ·  retry.py — ImportError raised as ConfigurationError
# ---------------------------------------------------------------------------


class TestImportValidationModuleRaisesOnImportError:
    """E-6 — ImportError from load_module_from_path surfaces as ConfigurationError."""

    def test_import_error_raises_configuration_error(self):
        from agent_actions.llm.batch.services.retry import _import_validation_module

        with patch(
            "agent_actions.llm.batch.services.retry_polling.load_module_from_path",
            side_effect=ImportError("No module named 'my_validator'"),
        ):
            with pytest.raises(ConfigurationError, match="my_validator"):
                _import_validation_module("my_validator", "/some/path")

    def test_other_exception_logs_warning_not_raises(self):
        """Non-ImportError exceptions are still suppressed to a warning."""
        from agent_actions.llm.batch.services.retry import _import_validation_module

        with patch(
            "agent_actions.llm.batch.services.retry_polling.load_module_from_path",
            side_effect=RuntimeError("disk error"),
        ):
            # Should not raise — other exceptions are downgraded to warning
            _import_validation_module("my_validator", None)


# ---------------------------------------------------------------------------
# E-7  ·  retry.py — backward-compat re-export of wait_for_batch_completion
# ---------------------------------------------------------------------------


class TestBackwardCompatReExports:
    """E-7 — Ensure facade re-exports don't silently break."""

    def test_wait_for_batch_completion_importable_from_retry(self):
        """wait_for_batch_completion should be importable from the facade."""
        from agent_actions.llm.batch.services.retry import wait_for_batch_completion  # noqa: F401

        # Must be the same function object as the canonical location
        from agent_actions.llm.batch.services.retry_polling import (
            wait_for_batch_completion as canonical,
        )

        assert wait_for_batch_completion is canonical

    def test_serialize_deserialize_importable_from_retry(self):
        """serialize/deserialize_results should be importable from the facade."""
        from agent_actions.llm.batch.services.retry import (  # noqa: F401
            deserialize_results,
            serialize_results,
        )
        from agent_actions.llm.batch.services.retry_serialization import (
            deserialize_results as canonical_de,
        )
        from agent_actions.llm.batch.services.retry_serialization import (
            serialize_results as canonical_se,
        )

        assert serialize_results is canonical_se
        assert deserialize_results is canonical_de


# ---------------------------------------------------------------------------
# E-8  ·  retry_serialization — RepromptMetadata round-trip
# ---------------------------------------------------------------------------


class TestSerializationRepromptRoundTrip:
    """E-8 — Verify serialize → deserialize with RepromptMetadata preserves data."""

    def test_reprompt_metadata_round_trip(self):
        from agent_actions.llm.batch.services.retry_serialization import (
            deserialize_results,
            serialize_results,
        )
        from agent_actions.llm.providers.batch_base import BatchResult
        from agent_actions.processing.types import RecoveryMetadata, RepromptMetadata

        original = BatchResult(
            custom_id="rec-1",
            content="some content",
            success=True,
        )
        original.recovery_metadata = RecoveryMetadata(
            reprompt=RepromptMetadata(attempts=2, passed=False, validation="check_format"),
        )

        serialized = serialize_results([original])
        deserialized = deserialize_results(serialized)

        assert len(deserialized) == 1
        result = deserialized[0]
        assert result.custom_id == "rec-1"
        assert result.content == "some content"
        assert result.success is True
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.retry is None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 2
        assert result.recovery_metadata.reprompt.passed is False
        assert result.recovery_metadata.reprompt.validation == "check_format"

    def test_both_retry_and_reprompt_round_trip(self):
        from agent_actions.llm.batch.services.retry_serialization import (
            deserialize_results,
            serialize_results,
        )
        from agent_actions.llm.providers.batch_base import BatchResult
        from agent_actions.processing.types import (
            RecoveryMetadata,
            RepromptMetadata,
            RetryMetadata,
        )

        original = BatchResult(
            custom_id="rec-2",
            content="result",
            success=True,
        )
        original.recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=2, succeeded=True, reason="missing"),
            reprompt=RepromptMetadata(attempts=1, passed=True, validation="my_udf"),
        )

        serialized = serialize_results([original])
        deserialized = deserialize_results(serialized)

        result = deserialized[0]
        assert result.recovery_metadata.retry.attempts == 3
        assert result.recovery_metadata.retry.failures == 2
        assert result.recovery_metadata.retry.succeeded is True
        assert result.recovery_metadata.retry.reason == "missing"
        assert result.recovery_metadata.reprompt.attempts == 1
        assert result.recovery_metadata.reprompt.passed is True
        assert result.recovery_metadata.reprompt.validation == "my_udf"
