"""Action-fatal is declared by the layer that knows, and survives every wrapper.

The collector that decides whether an error stops the whole action sees the
error only after each layer above the failure has wrapped it. Reading the
declaration back through the chain is what makes the two ends agree; reading
the outermost type instead would classify the wrapper.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import (
    AgentActionsError,
    ConfigurationError,
    EmptyOutputError,
    NetworkError,
    RecordContextError,
    SchemaValidationError,
    exhaustion_halt,
    is_action_fatal,
    mark_action_fatal,
)
from agent_actions.errors.operations import TemplateVariableError


def _wrap(error: Exception) -> AgentActionsError:
    """The shape a strategy error has after the pipeline re-raises it."""
    return AgentActionsError(f"Error generating target: {error}", cause=error)


class TestADeclaredErrorIsFatalThroughEveryWrapper:
    @pytest.mark.parametrize(
        "error",
        [
            ConfigurationError("schema missing"),
            EmptyOutputError("no output with on_empty=error"),
            SchemaValidationError("output failed validation"),
        ],
        ids=["configuration", "empty_output", "schema_validation"],
    )
    def test_a_marked_error_survives_being_wrapped(self, error):
        marked = mark_action_fatal(error)

        assert is_action_fatal(marked) is True
        assert is_action_fatal(_wrap(marked)) is True, (
            "the pipeline wraps a strategy error before the collector sees it, "
            "so a classifier reading the outermost type sees only the wrapper"
        )
        assert is_action_fatal(_wrap(_wrap(marked))) is True

    def test_a_halt_is_fatal_without_being_marked(self):
        """``on_exhausted: raise`` already tags its own exception."""
        halt = exhaustion_halt("Retry exhausted (on_exhausted=raise)")

        assert is_action_fatal(halt) is True
        assert is_action_fatal(_wrap(halt)) is True


class TestAnUndeclaredErrorIsNotFatal:
    @pytest.mark.parametrize(
        "error",
        [
            ConfigurationError("nobody declared this fatal"),
            SchemaValidationError("nobody declared this fatal"),
            RecordContextError("record context incomplete"),
            NetworkError("timeout"),
            AgentActionsError("wrapped file accident"),
            ValueError("unreadable row"),
        ],
        ids=[
            "configuration",
            "schema_validation",
            "record_context",
            "network",
            "wrapped_accident",
            "file_scoped",
        ],
    )
    def test_type_alone_never_makes_an_error_fatal(self, error):
        """A type that is fatal from a record loop is not fatal from anywhere else."""
        assert is_action_fatal(error) is False

    def test_wrapping_an_undeclared_error_does_not_make_it_fatal(self):
        assert is_action_fatal(_wrap(ConfigurationError("undeclared"))) is False

    def test_marking_one_error_does_not_leak_to_another(self):
        mark_action_fatal(ConfigurationError("declared"))

        assert is_action_fatal(ConfigurationError("a different instance")) is False


class TestTheStrategyAndTheCollectorAgree:
    """What the record loop re-raises is what the collector must call fatal."""

    def _strategy(self):
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

        return OnlineLLMStrategy.__new__(OnlineLLMStrategy)

    def _context(self):
        from agent_actions.processing.types import ProcessingContext

        return ProcessingContext(
            agent_config={},
            agent_name="label_page",
            storage_backend=None,
            file_path="/out/output.json",
            output_directory="/out",
        )

    @pytest.mark.parametrize(
        "error",
        [
            ConfigurationError("schema missing"),
            EmptyOutputError("no output with on_empty=error"),
            SchemaValidationError("output failed validation"),
            TemplateVariableError(
                missing_variables=[],
                available_variables=["source"],
                agent_name="label_page",
                mode="online",
                cause=Exception("jinja syntax"),
            ),
            exhaustion_halt("Retry exhausted (on_exhausted=raise)"),
        ],
        ids=["configuration", "empty_output", "schema_validation", "broken_template", "halt"],
    )
    def test_what_the_record_loop_reraises_is_fatal(self, monkeypatch, error):
        strategy = self._strategy()
        monkeypatch.setattr(
            strategy, "process_record", lambda *_a, **_kw: (_ for _ in ()).throw(error)
        )

        with pytest.raises(Exception) as exc_info:
            strategy.invoke([{"source_guid": "g1"}], self._context())

        assert is_action_fatal(exc_info.value) is True, (
            "the record loop re-raised this deliberately, so the collector "
            "above must not treat it as one file's accident"
        )

    def test_what_the_record_loop_tombstones_is_not_fatal(self, monkeypatch):
        strategy = self._strategy()
        recoverable = RecordContextError("record context incomplete")
        monkeypatch.setattr(
            strategy, "process_record", lambda *_a, **_kw: (_ for _ in ()).throw(recoverable)
        )

        results = strategy.invoke([{"source_guid": "g1"}], self._context())

        assert len(results) == 1
        assert is_action_fatal(recoverable) is False
