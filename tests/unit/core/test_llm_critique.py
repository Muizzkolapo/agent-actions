"""Unit tests for LLM critique module.

Tests critique prompt construction, feedback formatting, threshold gating,
non-fatal failure handling, and integration with RepromptService.
"""

from unittest.mock import Mock, patch

import pytest

from agent_actions.processing.recovery.critique import (
    build_critique_prompt,
    format_critique_feedback,
)
from agent_actions.processing.recovery.reprompt import RepromptService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubValidator:
    """Minimal ResponseValidator for tests."""

    def __init__(self, results: list[bool], feedback: str = "bad output"):
        self._results = iter(results)
        self._feedback = feedback

    def validate(self, response):
        return next(self._results)

    @property
    def feedback_message(self) -> str:
        return self._feedback

    @property
    def name(self) -> str:
        return "stub_validator"


def _llm_op_factory(responses: list[tuple], *, capture_prompts: list | None = None):
    """Return a callable that yields successive (response, executed) tuples."""
    it = iter(responses)

    def op(prompt: str):
        if capture_prompts is not None:
            capture_prompts.append(prompt)
        return next(it)

    return op


# ---------------------------------------------------------------------------
# TestBuildCritiquePrompt
# ---------------------------------------------------------------------------


class TestBuildCritiquePrompt:
    """Tests for build_critique_prompt()."""

    def test_contains_response_and_errors(self):
        """Prompt includes the failed response and validation errors."""
        prompt = build_critique_prompt({"name": "John"}, "Missing required field: age")

        assert "John" in prompt
        assert "Missing required field: age" in prompt
        assert "Failed Response" in prompt
        assert "Validation Errors" in prompt

    def test_dict_response_serialized_as_json(self):
        """Dict responses are JSON-serialized for readability."""
        prompt = build_critique_prompt({"key": "value"}, "error")

        assert '"key"' in prompt
        assert '"value"' in prompt

    def test_string_response_used_directly(self):
        """String responses are used as-is, not double-serialized."""
        prompt = build_critique_prompt("raw text response", "error")

        assert "raw text response" in prompt
        # Should not be wrapped in extra quotes
        assert '"raw text response"' not in prompt

    def test_non_serializable_response_falls_back_to_str(self):
        """Non-JSON-serializable objects use str() fallback."""

        class Custom:
            def __str__(self):
                return "Custom(id=42)"

        prompt = build_critique_prompt(Custom(), "error")
        assert "Custom(id=42)" in prompt

    def test_no_internal_code_paths_in_prompt(self):
        """Critique prompt should not leak internal code paths or stack traces."""
        prompt = build_critique_prompt({"data": "test"}, "Schema mismatch")

        assert "agent_actions" not in prompt
        assert "Traceback" not in prompt
        assert ".py" not in prompt


# ---------------------------------------------------------------------------
# TestFormatCritiqueFeedback
# ---------------------------------------------------------------------------


class TestFormatCritiqueFeedback:
    """Tests for format_critique_feedback()."""

    def test_appends_critique_alongside_standard(self):
        """Critique is appended after standard feedback, not replacing it."""
        standard = "---\nYour response failed: missing field\nPlease correct."
        critique = "The model is ignoring the age field in the schema."

        combined = format_critique_feedback(critique, standard)

        assert combined.startswith(standard)
        assert "## Analysis of Failure" in combined
        assert critique in combined

    def test_standard_feedback_preserved_intact(self):
        """Standard feedback appears exactly as passed, without modification."""
        standard = "Original error message with special chars: <>&"
        critique = "Analysis text"

        combined = format_critique_feedback(critique, standard)

        assert standard in combined

    def test_empty_critique_still_has_header(self):
        """Even empty critique text includes the section header."""
        combined = format_critique_feedback("", "standard feedback")

        assert "## Analysis of Failure" in combined
        assert "standard feedback" in combined


# ---------------------------------------------------------------------------
# TestCritiqueThresholdGating
# ---------------------------------------------------------------------------


class TestCritiqueThresholdGating:
    """Tests for critique threshold behavior in RepromptService."""

    def test_critique_not_called_below_threshold(self):
        """Critique should not fire on attempts before critique_after_attempt."""
        critique_fn = Mock(return_value="analysis")
        # Fails on attempt 1, passes on attempt 2
        validator = _StubValidator([False, True], feedback="fix it")
        svc = RepromptService(
            validator=validator,
            max_attempts=5,
            critique_fn=critique_fn,
            critique_after_attempt=3,  # critique only after attempt 3
        )

        svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"bad": True}, True),
                    ({"good": True}, True),
                ]
            ),
            original_prompt="test",
        )

        # Attempt 1 failed, but threshold is 3 — critique should NOT fire
        critique_fn.assert_not_called()

    def test_critique_called_at_threshold(self):
        """Critique should fire when attempt reaches critique_after_attempt."""
        critique_fn = Mock(return_value="The model is missing the required field")
        # Fails 3 times, passes on attempt 4
        validator = _StubValidator([False, False, False, True], feedback="missing field")
        svc = RepromptService(
            validator=validator,
            max_attempts=5,
            critique_fn=critique_fn,
            critique_after_attempt=2,  # critique fires from attempt 2 onward
        )

        captured = []
        svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"v1": True}, True),
                    ({"v2": True}, True),
                    ({"v3": True}, True),
                    ({"v4": True}, True),
                ],
                capture_prompts=captured,
            ),
            original_prompt="base",
        )

        # critique_fn called on attempts 2 and 3 (both >= threshold, both < max)
        assert critique_fn.call_count == 2

    def test_critique_not_called_on_last_attempt(self):
        """Critique should not fire on the last attempt (no more retries after it)."""
        critique_fn = Mock(return_value="analysis")
        # Fails all 3 attempts
        validator = _StubValidator([False, False, False], feedback="bad")
        svc = RepromptService(
            validator=validator,
            max_attempts=3,
            on_exhausted="return_last",
            critique_fn=critique_fn,
            critique_after_attempt=1,
        )

        with patch("agent_actions.processing.recovery.reprompt.fire_event"):
            svc.execute(
                llm_operation=_llm_op_factory(
                    [
                        ({"v1": True}, True),
                        ({"v2": True}, True),
                        ({"v3": True}, True),
                    ]
                ),
                original_prompt="test",
            )

        # Attempts 1 and 2 trigger critique (>= threshold 1 and < max 3)
        # Attempt 3 is the last — no critique (no retry after it)
        assert critique_fn.call_count == 2

    def test_critique_disabled_when_fn_is_none(self):
        """No critique fires when critique_fn is None (default)."""
        validator = _StubValidator([False, False, True], feedback="bad")
        svc = RepromptService(
            validator=validator,
            max_attempts=5,
            critique_fn=None,  # disabled
        )

        result = svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"v1": True}, True),
                    ({"v2": True}, True),
                    ({"v3": True}, True),
                ]
            ),
            original_prompt="test",
        )

        assert result.passed is True
        assert result.attempts == 3


# ---------------------------------------------------------------------------
# TestCritiqueFailureHandling
# ---------------------------------------------------------------------------


class TestCritiqueFailureHandling:
    """Tests for non-fatal critique failure handling."""

    def test_critique_failure_nonfatal(self):
        """When critique_fn raises, the reprompt loop continues without critique."""
        critique_fn = Mock(side_effect=RuntimeError("API timeout"))
        validator = _StubValidator([False, False, True], feedback="fix it")
        svc = RepromptService(
            validator=validator,
            max_attempts=5,
            critique_fn=critique_fn,
            critique_after_attempt=1,
        )

        captured = []
        result = svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"v1": True}, True),
                    ({"v2": True}, True),
                    ({"v3": True}, True),
                ],
                capture_prompts=captured,
            ),
            original_prompt="base",
        )

        # Should still succeed — critique failure doesn't kill the loop
        assert result.passed is True
        assert result.attempts == 3

        # Feedback should be standard (no critique section) since critique failed
        assert "## Analysis of Failure" not in captured[1]
        assert "## Analysis of Failure" not in captured[2]

    def test_critique_failure_logs_warning(self):
        """Critique failure should log a warning with exc_info."""
        critique_fn = Mock(side_effect=ValueError("bad response"))
        validator = _StubValidator([False, True], feedback="fix")
        svc = RepromptService(
            validator=validator,
            max_attempts=3,
            critique_fn=critique_fn,
            critique_after_attempt=1,
        )

        with patch("agent_actions.processing.recovery.reprompt.logger") as mock_logger:
            svc.execute(
                llm_operation=_llm_op_factory(
                    [
                        ({"bad": True}, True),
                        ({"good": True}, True),
                    ]
                ),
                original_prompt="test",
                context="test_action",
            )

            mock_logger.warning.assert_any_call(
                "[%s] LLM critique call failed, continuing without critique",
                "test_action",
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# TestCritiqueFeedbackIntegration
# ---------------------------------------------------------------------------


class TestCritiqueFeedbackIntegration:
    """Tests for critique feedback appearing correctly in reprompt prompts."""

    def test_critique_combined_in_prompt(self):
        """When critique succeeds, both standard feedback and critique appear in prompt."""
        critique_fn = Mock(return_value="The model is confusing X with Y")
        validator = _StubValidator([False, True], feedback="wrong format")
        svc = RepromptService(
            validator=validator,
            max_attempts=3,
            critique_fn=critique_fn,
            critique_after_attempt=1,
        )

        captured = []
        svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"bad": True}, True),
                    ({"good": True}, True),
                ],
                capture_prompts=captured,
            ),
            original_prompt="original prompt",
        )

        reprompted = captured[1]
        # Standard feedback present
        assert "wrong format" in reprompted
        assert "Please correct and respond again" in reprompted
        # Critique present
        assert "## Analysis of Failure" in reprompted
        assert "The model is confusing X with Y" in reprompted
        # Original prompt at the start
        assert reprompted.startswith("original prompt\n\n---")

    def test_critique_fn_receives_correct_args(self):
        """critique_fn receives (response, feedback_message) from the validator."""
        critique_fn = Mock(return_value="analysis")
        validator = _StubValidator([False, True], feedback="specific error msg")
        svc = RepromptService(
            validator=validator,
            max_attempts=3,
            critique_fn=critique_fn,
            critique_after_attempt=1,
        )

        svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"the_response": 42}, True),
                    ({"good": True}, True),
                ]
            ),
            original_prompt="test",
        )

        critique_fn.assert_called_once_with({"the_response": 42}, "specific error msg")


# ---------------------------------------------------------------------------
# TestCritiqueConfig
# ---------------------------------------------------------------------------


class TestCritiqueConfig:
    """Tests for critique configuration via RepromptConfig."""

    def test_reprompt_config_defaults(self):
        """RepromptConfig defaults: use_llm_critique=False, critique_after_attempt=2."""
        from agent_actions.config.schema import RepromptConfig

        config = RepromptConfig()
        assert config.use_llm_critique is False
        assert config.critique_after_attempt == 2

    def test_reprompt_config_critique_enabled(self):
        """RepromptConfig accepts critique fields."""
        from agent_actions.config.schema import RepromptConfig

        config = RepromptConfig(
            validation="check_output",
            max_attempts=5,
            use_llm_critique=True,
            critique_after_attempt=3,
        )
        assert config.use_llm_critique is True
        assert config.critique_after_attempt == 3

    def test_reprompt_config_critique_after_attempt_validation(self):
        """critique_after_attempt must be >= 1 and <= 10."""
        from pydantic import ValidationError

        from agent_actions.config.schema import RepromptConfig

        with pytest.raises(ValidationError):
            RepromptConfig(critique_after_attempt=0)

        with pytest.raises(ValidationError):
            RepromptConfig(critique_after_attempt=11)

    def test_create_service_passes_critique_fn(self):
        """create_reprompt_service_from_config passes critique_fn through."""
        from agent_actions.processing.recovery.reprompt import (
            create_reprompt_service_from_config,
        )

        critique_fn = Mock(return_value="analysis")
        validator = _StubValidator([True])

        svc = create_reprompt_service_from_config(
            {"max_attempts": 3, "critique_after_attempt": 2},
            validator=validator,
            critique_fn=critique_fn,
        )

        assert svc is not None
        assert svc._critique_fn is critique_fn
        assert svc._critique_after_attempt == 2

    def test_create_service_no_critique_by_default(self):
        """Without critique_fn, RepromptService has no critique."""
        from agent_actions.processing.recovery.reprompt import (
            create_reprompt_service_from_config,
        )

        validator = _StubValidator([True])
        svc = create_reprompt_service_from_config(
            {"max_attempts": 2},
            validator=validator,
        )

        assert svc is not None
        assert svc._critique_fn is None
