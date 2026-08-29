"""A policy halt must escape the per-record loop, not become a failed record.

``OnlineLLMStrategy.invoke`` re-raises a short list of action-fatal exception
types and turns everything else into a per-record failure.  An
``on_exhausted: raise`` halt is action-fatal by definition — the user asked the
run to stop — but it arrives as a RuntimeError, so it was flattened into a
result and the policy tag went with it.  By the time the action's status is
resolved there is no exception left to read the policy from, the node row is
written without a halt marker, and the next run resets and re-runs it.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError, exhaustion_halt
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus

HALT_TEXT = "Reprompt validation exhausted after 2 attempts (validation: schema_check)"


def _invoke_raising(monkeypatch, error: Exception):
    """Drive the real per-record loop with one record whose processing raises."""
    strategy = OnlineLLMStrategy.__new__(OnlineLLMStrategy)
    monkeypatch.setattr(
        OnlineLLMStrategy,
        "process_record",
        lambda self, item, ctx: (_ for _ in ()).throw(error),
    )
    context = ProcessingContext(agent_config={}, agent_name="summarize_page_content")
    return strategy.invoke([{"source_guid": "rec-1"}], context)


class TestAPolicyHaltEscapesTheLoop:
    def test_a_tagged_halt_is_re_raised(self, monkeypatch):
        error = exhaustion_halt(HALT_TEXT)

        with pytest.raises(RuntimeError) as exc_info:
            _invoke_raising(monkeypatch, error)

        assert exc_info.value is error

    def test_an_ordinary_error_is_still_flattened(self, monkeypatch):
        results = _invoke_raising(monkeypatch, RuntimeError("provider timed out"))

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "provider timed out" in results[0].error

    def test_an_untagged_runtime_error_with_the_same_text_is_flattened(self, monkeypatch):
        """The policy makes it fatal, not the wording."""
        results = _invoke_raising(monkeypatch, RuntimeError(HALT_TEXT))

        assert results[0].status == ProcessingStatus.FAILED


class TestTheExistingFatalTypesStayFatal:
    def test_a_configuration_error_still_escapes(self, monkeypatch):
        with pytest.raises(ConfigurationError):
            _invoke_raising(monkeypatch, ConfigurationError("bad config"))
