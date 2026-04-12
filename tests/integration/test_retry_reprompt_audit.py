"""Comprehensive retry & reprompt audit tests.

Tests every combination of:
- retry × reprompt (independent and composed)
- online × batch mode
- on_exhausted: return_last vs raise
- guard skip interactions
- metadata correctness
- event logging
"""

from unittest.mock import Mock, patch

import pytest

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.logging.events.validation_events import (
    RepromptValidationFailedEvent,
    RetryExhaustedEvent,
)
from agent_actions.processing.recovery.reprompt import (
    RepromptService,
    create_reprompt_service_from_config,
)
from agent_actions.processing.recovery.response_validator import (
    ComposedValidator,
    build_validation_feedback,
)
from agent_actions.processing.recovery.retry import (
    RetryResult,
    RetryService,
    classify_error,
    create_retry_service_from_config,
    is_retriable_error,
)
from agent_actions.processing.recovery.validation import (
    _VALIDATION_REGISTRY,
    get_validation_function,
    reprompt_validation,
)
from agent_actions.processing.types import (
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubValidator:
    """Minimal ResponseValidator for tests that need a pre-built validator."""

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


class _RaisingValidator:
    """Validator that raises on validate()."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def validate(self, response):
        raise self._exc

    @property
    def feedback_message(self) -> str:
        return "raising"

    @property
    def name(self) -> str:
        return "raising_validator"


def _llm_op_factory(responses: list[tuple], *, capture_prompts: list | None = None):
    """Return a callable that yields successive (response, executed) tuples.

    If *capture_prompts* is provided, each prompt is appended so callers can
    inspect what the reprompt loop sent.
    """
    it = iter(responses)

    def op(prompt: str):
        if capture_prompts is not None:
            capture_prompts.append(prompt)
        return next(it)

    return op


# ---------------------------------------------------------------------------
# TestRetryService
# ---------------------------------------------------------------------------


class TestRetryService:
    """Verify retry behaviour for transport-layer errors."""

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_retries_on_network_error(self, mock_sleep):
        """NetworkError triggers retry; success on second attempt returns response."""
        svc = RetryService(max_attempts=3, base_delay=1.0)
        op = Mock(side_effect=[NetworkError("conn reset"), "ok"])

        result = svc.execute(op)

        assert result.response == "ok"
        assert result.attempts == 2
        assert result.exhausted is False
        assert result.reason == "network_error"
        assert result.needed_retry is True
        mock_sleep.assert_called_once()

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep):
        """RateLimitError triggers retry."""
        svc = RetryService(max_attempts=3, base_delay=1.0)
        op = Mock(side_effect=[RateLimitError("429"), "ok"])

        result = svc.execute(op)

        assert result.response == "ok"
        assert result.attempts == 2
        assert result.reason == "rate_limit"
        assert result.exhausted is False

    @pytest.mark.parametrize(
        "exc",
        [ValueError("bad input"), VendorAPIError("invalid key")],
        ids=["ValueError", "VendorAPIError"],
    )
    def test_no_retry_on_non_retriable_error(self, exc):
        """Non-retriable errors raise immediately with no retry."""
        svc = RetryService(max_attempts=3)
        op = Mock(side_effect=exc)

        with pytest.raises(type(exc)):
            svc.execute(op)

        assert op.call_count == 1

    @patch("agent_actions.processing.recovery.retry.random.uniform", side_effect=lambda a, b: b)
    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_exponential_backoff_formula(self, mock_sleep, _mock_rand):
        """Backoff delay = min(base_delay * 2^(attempt-1), max_delay), jitter upper bound."""
        svc = RetryService(max_attempts=4, base_delay=0.5, max_delay=10.0)
        op = Mock(
            side_effect=[
                NetworkError("1"),
                NetworkError("2"),
                NetworkError("3"),
                "ok",
            ]
        )

        svc.execute(op)

        # Delays: 0.5*2^0=0.5, 0.5*2^1=1.0, 0.5*2^2=2.0
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == pytest.approx([0.5, 1.0, 2.0])

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_backoff_capped_at_max_delay(self, mock_sleep):
        """Backoff never exceeds max_delay."""
        svc = RetryService(max_attempts=5, base_delay=10.0, max_delay=15.0)
        # Force jitter to return the full delay
        with patch(
            "agent_actions.processing.recovery.retry.random.uniform",
            side_effect=lambda a, b: b,
        ):
            op = Mock(
                side_effect=[
                    NetworkError("1"),
                    NetworkError("2"),
                    NetworkError("3"),
                    NetworkError("4"),
                    "ok",
                ]
            )
            svc.execute(op)

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert all(d <= 15.0 for d in delays)

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    @patch("agent_actions.processing.recovery.retry.fire_event")
    def test_exhaustion_return_last(self, mock_fire, mock_sleep):
        """When all attempts fail with retriable errors, result is exhausted."""
        svc = RetryService(max_attempts=2)
        op = Mock(side_effect=[NetworkError("a"), NetworkError("b")])

        result = svc.execute(op)

        assert result.response is None
        assert result.attempts == 2
        assert result.exhausted is True
        assert result.reason == "network_error"
        assert result.last_error is not None
        assert result.needed_retry is True

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    @patch("agent_actions.processing.recovery.retry.fire_event")
    def test_exhaustion_raise_not_applicable(self, mock_fire, mock_sleep):
        """RetryService itself does not have on_exhausted=raise — it always returns.
        The caller decides what to do with exhaustion."""
        svc = RetryService(max_attempts=1)
        op = Mock(side_effect=NetworkError("fail"))

        result = svc.execute(op)

        assert result.exhausted is True
        assert result.response is None

    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_metadata_attempts_match_actual(self, mock_sleep):
        """RetryResult.attempts exactly equals the number of operation() calls."""
        svc = RetryService(max_attempts=5)
        op = Mock(
            side_effect=[
                NetworkError("1"),
                NetworkError("2"),
                NetworkError("3"),
                "ok",
            ]
        )

        result = svc.execute(op)

        assert result.attempts == 4
        assert op.call_count == 4

    def test_success_first_attempt_no_retry_metadata(self):
        """When first attempt succeeds, needed_retry is False."""
        svc = RetryService(max_attempts=3)
        result = svc.execute(lambda: "ok")

        assert result.response == "ok"
        assert result.attempts == 1
        assert result.needed_retry is False
        assert result.reason is None
        assert result.exhausted is False

    def test_max_attempts_validation(self):
        """max_attempts < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RetryService(max_attempts=0)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (RateLimitError("429"), "rate_limit"),
            (NetworkError("connection refused"), "network_error"),
            (NetworkError("timeout occurred"), "timeout"),
            (VendorAPIError("bad key"), "api_error"),
            (ValueError("misc"), "unknown"),
        ],
        ids=["rate_limit", "network", "timeout", "vendor_api", "unknown"],
    )
    def test_classify_error(self, error, expected):
        assert classify_error(error) == expected

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (NetworkError("x"), True),
            (RateLimitError("x"), True),
            (VendorAPIError("x"), False),
            (ValueError("x"), False),
        ],
        ids=["network", "rate_limit", "vendor_api", "value_error"],
    )
    def test_is_retriable_error(self, error, expected):
        assert is_retriable_error(error) is expected


# ---------------------------------------------------------------------------
# TestRetryServiceFactory
# ---------------------------------------------------------------------------


class TestRetryServiceFactory:
    """Verify create_retry_service_from_config edge cases."""

    def test_none_config_returns_none(self):
        assert create_retry_service_from_config(None) is None

    def test_disabled_returns_none(self):
        assert create_retry_service_from_config({"enabled": False}) is None

    def test_enabled_default(self):
        svc = create_retry_service_from_config({})
        assert svc is not None
        assert svc.max_attempts == 3

    def test_custom_params(self):
        svc = create_retry_service_from_config(
            {"max_attempts": 5, "base_delay": 2.0, "max_delay": 30.0}
        )
        assert svc.max_attempts == 5
        assert svc.base_delay == 2.0
        assert svc.max_delay == 30.0


# ---------------------------------------------------------------------------
# TestRepromptService
# ---------------------------------------------------------------------------


class TestRepromptService:
    """Verify reprompt validation loop behaviour."""

    def test_pass_on_first_attempt(self):
        """Valid response on first attempt — no reprompt, attempts=1."""
        validator = _StubValidator([True])
        svc = RepromptService(validator=validator, max_attempts=3)

        result = svc.execute(
            llm_operation=_llm_op_factory([({"answer": "good"}, True)]),
            original_prompt="test prompt",
        )

        assert result.passed is True
        assert result.attempts == 1
        assert result.exhausted is False
        assert result.executed is True

    def test_pass_after_multiple_attempts(self):
        """Fails first, passes second — attempts=2, passed=True."""
        validator = _StubValidator([False, True], feedback="fix it")
        svc = RepromptService(validator=validator, max_attempts=3)

        result = svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"answer": "bad"}, True),
                    ({"answer": "good"}, True),
                ]
            ),
            original_prompt="test prompt",
        )

        assert result.passed is True
        assert result.attempts == 2
        assert result.exhausted is False

    def test_feedback_appended_to_prompt(self):
        """On failure, feedback is appended to original_prompt for next call."""
        validator = _StubValidator([False, True], feedback="wrong format")
        svc = RepromptService(validator=validator, max_attempts=3)
        captured = []

        svc.execute(
            llm_operation=_llm_op_factory(
                [({"bad": True}, True), ({"good": True}, True)],
                capture_prompts=captured,
            ),
            original_prompt="original",
        )

        assert len(captured) == 2
        assert captured[0] == "original"
        assert "wrong format" in captured[1]
        assert captured[1].startswith("original\n\n---")

    def test_feedback_rebuilds_from_original_each_time(self):
        """Each reprompt appends to original_prompt, not accumulated prompt."""
        validator = _StubValidator([False, False, True], feedback="fix")
        svc = RepromptService(validator=validator, max_attempts=3)
        captured = []

        svc.execute(
            llm_operation=_llm_op_factory(
                [({"v1": True}, True), ({"v2": True}, True), ({"v3": True}, True)],
                capture_prompts=captured,
            ),
            original_prompt="base",
        )

        # Both reprompted prompts start with "base\n\n---"
        assert captured[1].startswith("base\n\n---")
        assert captured[2].startswith("base\n\n---")
        # Second reprompt feedback is about v2, not v1
        assert '"v2"' in captured[2]

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_exhaustion_return_last(self, mock_fire):
        """on_exhausted=return_last: returns last failed response, passed=False."""
        validator = _StubValidator([False, False], feedback="bad")
        svc = RepromptService(validator=validator, max_attempts=2, on_exhausted="return_last")

        result = svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"v1": True}, True),
                    ({"v2": True}, True),
                ]
            ),
            original_prompt="p",
        )

        assert result.passed is False
        assert result.exhausted is True
        assert result.response == {"v2": True}
        assert result.attempts == 2

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_exhaustion_raise(self, mock_fire):
        """on_exhausted=raise: raises RuntimeError after exhaustion."""
        validator = _StubValidator([False, False], feedback="bad")
        svc = RepromptService(validator=validator, max_attempts=2, on_exhausted="raise")

        with pytest.raises(RuntimeError, match="Reprompt validation exhausted"):
            svc.execute(
                llm_operation=_llm_op_factory(
                    [
                        ({"v1": True}, True),
                        ({"v2": True}, True),
                    ]
                ),
                original_prompt="p",
            )

    def test_exhaustion_raise_via_execute_override(self):
        """on_exhausted can be overridden per-call via execute() parameter."""
        validator = _StubValidator([False], feedback="bad")
        svc = RepromptService(validator=validator, max_attempts=1, on_exhausted="return_last")

        with patch("agent_actions.processing.recovery.reprompt.fire_event"):
            with pytest.raises(RuntimeError, match="Reprompt validation exhausted"):
                svc.execute(
                    llm_operation=_llm_op_factory([({"v": True}, True)]),
                    original_prompt="p",
                    on_exhausted="raise",
                )

    def test_guard_skip_bypasses_validation(self):
        """When LLM returns executed=False, no validation runs."""
        validator = _StubValidator([])  # Should never be called
        svc = RepromptService(validator=validator, max_attempts=3)

        result = svc.execute(
            llm_operation=_llm_op_factory([({"passthrough": True}, False)]),
            original_prompt="p",
        )

        assert result.executed is False
        assert result.attempts == 0
        assert result.passed is True
        assert result.exhausted is False

    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, TypeError, KeyError, IndexError],
        ids=["ValueError", "TypeError", "KeyError", "IndexError"],
    )
    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_validator_exception_treated_as_failure(self, _fire, exc_type):
        """ValueError/TypeError/LookupError from validator → treated as failure, not crash."""
        validator = _RaisingValidator(exc_type("boom"))
        svc = RepromptService(validator=validator, max_attempts=1, on_exhausted="return_last")

        result = svc.execute(
            llm_operation=_llm_op_factory([({"r": True}, True)]),
            original_prompt="p",
        )

        assert result.passed is False
        assert result.exhausted is True

    def test_non_handled_exception_propagates(self):
        """Exceptions outside ValueError/TypeError/LookupError propagate."""
        validator = _RaisingValidator(AttributeError("boom"))
        svc = RepromptService(validator=validator, max_attempts=2)

        with pytest.raises(AttributeError, match="boom"):
            svc.execute(
                llm_operation=_llm_op_factory([({"r": True}, True)]),
                original_prompt="p",
            )

    def test_metadata_passed_reflects_outcome_true(self):
        """RepromptResult.passed is True when validation passes."""
        validator = _StubValidator([True])
        svc = RepromptService(validator=validator, max_attempts=2)

        result = svc.execute(
            llm_operation=_llm_op_factory([({"ok": True}, True)]),
            original_prompt="p",
        )

        assert result.passed is True

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_metadata_passed_reflects_outcome_false(self, _fire):
        """RepromptResult.passed is False when validation fails and exhausted."""
        validator = _StubValidator([False])
        svc = RepromptService(validator=validator, max_attempts=1, on_exhausted="return_last")

        result = svc.execute(
            llm_operation=_llm_op_factory([({"bad": True}, True)]),
            original_prompt="p",
        )

        assert result.passed is False

    def test_invalid_on_exhausted_init(self):
        """Invalid on_exhausted at init raises ValueError."""
        with pytest.raises(ValueError, match="on_exhausted must be one of"):
            RepromptService(validator=_StubValidator([True]), on_exhausted="ignore")

    def test_invalid_on_exhausted_execute(self):
        """Invalid on_exhausted at execute() raises ValueError."""
        svc = RepromptService(validator=_StubValidator([True]), max_attempts=1)

        with pytest.raises(ValueError, match="on_exhausted must be one of"):
            svc.execute(
                llm_operation=_llm_op_factory([({"r": True}, True)]),
                original_prompt="p",
                on_exhausted="ignore",
            )

    def test_empty_validation_name_requires_validator(self):
        """Empty validation_name without validator raises ValueError."""
        with pytest.raises(ValueError, match="validation_name cannot be empty"):
            RepromptService(validation_name="", max_attempts=2)

    def test_max_attempts_validation(self):
        """max_attempts < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RepromptService(validator=_StubValidator([True]), max_attempts=0)


# ---------------------------------------------------------------------------
# TestRepromptServiceFactory
# ---------------------------------------------------------------------------


class TestRepromptServiceFactory:
    """Verify create_reprompt_service_from_config edge cases."""

    def setup_method(self):
        _VALIDATION_REGISTRY.clear()

    def teardown_method(self):
        _VALIDATION_REGISTRY.clear()

    def test_none_config_no_validator_returns_none(self):
        assert create_reprompt_service_from_config(None) is None

    def test_none_config_with_validator_returns_service(self):
        svc = create_reprompt_service_from_config(None, validator=_StubValidator([True]))
        assert svc is not None

    def test_config_missing_validation_no_validator_raises(self):
        with pytest.raises(ValueError, match="missing required 'validation'"):
            create_reprompt_service_from_config({"max_attempts": 2})

    def test_config_with_validation_name(self):
        @reprompt_validation("test feedback")
        def my_check(response):
            return True

        svc = create_reprompt_service_from_config({"validation": "my_check"})
        assert svc is not None
        assert svc.validation_name == "my_check"

    def test_config_with_validator_override(self):
        svc = create_reprompt_service_from_config(
            {"max_attempts": 5}, validator=_StubValidator([True])
        )
        assert svc is not None
        assert svc.max_attempts == 5


# ---------------------------------------------------------------------------
# TestComposedValidation
# ---------------------------------------------------------------------------


class TestComposedValidation:
    """Verify composed validator chaining and short-circuit behaviour."""

    def test_schema_plus_udf_short_circuits(self):
        """First failure stops chain — second validator not called."""
        first = Mock()
        first.validate = Mock(return_value=False)
        first.feedback_message = "first failed"
        first.name = "first"

        second = Mock()
        second.validate = Mock(return_value=True)
        second.feedback_message = "second ok"
        second.name = "second"

        composed = ComposedValidator([first, second])
        assert composed.validate({"x": 1}) is False
        second.validate.assert_not_called()
        assert composed.feedback_message == "first failed"

    def test_all_pass(self):
        """Both validators pass → composed passes."""
        v1 = _StubValidator([True])
        v2 = _StubValidator([True])
        composed = ComposedValidator([v1, v2])

        assert composed.validate({"x": 1}) is True
        assert composed.feedback_message == ""

    def test_composed_name_joins(self):
        """Name joins sub-validator names with +."""
        v1 = _StubValidator([True])
        v2 = _StubValidator([True])
        composed = ComposedValidator([v1, v2])

        assert composed.name == "stub_validator+stub_validator"

    def test_empty_validators_raises(self):
        """ComposedValidator requires at least one validator."""
        with pytest.raises(ValueError, match="at least one"):
            ComposedValidator([])

    def test_retry_wraps_reprompt(self):
        """When retry wraps reprompt, both layers contribute metadata correctly.

        Simulates: retry fails once → succeeds → reprompt validates → passes.
        """
        retry_svc = RetryService(max_attempts=3, base_delay=0.0, max_delay=0.0)
        validator = _StubValidator([True])
        reprompt_svc = RepromptService(validator=validator, max_attempts=2)

        # Track calls across both retry and reprompt layers
        inner_call_count = 0

        def llm_with_retry(prompt):
            nonlocal inner_call_count

            def operation():
                nonlocal inner_call_count
                inner_call_count += 1
                if inner_call_count == 1:
                    raise NetworkError("transient")
                return ({"result": "ok"}, True)

            with patch("agent_actions.processing.recovery.retry.time.sleep"):
                retry_result = retry_svc.execute(operation)

            if retry_result.exhausted:
                return None, False
            return retry_result.response

        result = reprompt_svc.execute(
            llm_operation=llm_with_retry,
            original_prompt="test",
        )

        assert result.passed is True
        assert result.executed is True
        assert inner_call_count == 2  # 1 failure + 1 success

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_retry_exhaustion_inside_reprompt(self, _fire):
        """When retry exhausts inside reprompt, reprompt sees (None, False) and guard-skips."""
        retry_svc = RetryService(max_attempts=2, base_delay=0.0, max_delay=0.0)
        validator = _StubValidator([True])  # Would pass if reached
        reprompt_svc = RepromptService(
            validator=validator, max_attempts=2, on_exhausted="return_last"
        )

        def llm_with_retry(prompt):
            def operation():
                raise NetworkError("down")

            with patch("agent_actions.processing.recovery.retry.time.sleep"):
                with patch("agent_actions.processing.recovery.retry.fire_event"):
                    retry_result = retry_svc.execute(operation)

            if retry_result.exhausted:
                return None, False
            return retry_result.response

        result = reprompt_svc.execute(
            llm_operation=llm_with_retry,
            original_prompt="test",
        )

        # Retry exhausted → (None, False) → reprompt sees executed=False → guard-skip
        assert result.executed is False
        assert result.attempts == 0
        assert result.passed is True  # Guard-skip treated as pass
        assert result.exhausted is False

    def test_guard_skip_during_retry_plus_reprompt(self):
        """Guard-skip propagates correctly through retry+reprompt combined path."""
        retry_svc = RetryService(max_attempts=3, base_delay=0.0, max_delay=0.0)
        validator = _StubValidator([])  # Should never be called
        reprompt_svc = RepromptService(validator=validator, max_attempts=2)

        def llm_with_retry(prompt):
            def operation():
                return ({"passthrough": True}, False)  # Guard skipped

            with patch("agent_actions.processing.recovery.retry.time.sleep"):
                retry_result = retry_svc.execute(operation)

            if retry_result.exhausted:
                return None, False
            return retry_result.response

        result = reprompt_svc.execute(
            llm_operation=llm_with_retry,
            original_prompt="test",
        )

        assert result.executed is False
        assert result.attempts == 0
        assert result.passed is True


# ---------------------------------------------------------------------------
# TestEventLogging
# ---------------------------------------------------------------------------


class TestEventLogging:
    """Verify events are fired at the correct moments."""

    @patch("agent_actions.processing.recovery.retry.fire_event")
    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_retry_exhausted_event_fired(self, mock_sleep, mock_fire):
        """RetryExhaustedEvent fires when all retry attempts fail."""
        svc = RetryService(max_attempts=2)
        op = Mock(side_effect=[NetworkError("a"), NetworkError("b")])

        svc.execute(op)

        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert isinstance(event, RetryExhaustedEvent)
        assert event.attempt == 2
        assert event.max_attempts == 2
        assert event.reason == "network_error"

    @patch("agent_actions.processing.recovery.retry.fire_event")
    @patch("agent_actions.processing.recovery.retry.time.sleep")
    def test_retry_event_not_fired_on_success(self, mock_sleep, mock_fire):
        """No event when retry succeeds."""
        svc = RetryService(max_attempts=3)
        op = Mock(side_effect=[NetworkError("a"), "ok"])

        svc.execute(op)

        mock_fire.assert_not_called()

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_reprompt_failed_event_fired(self, mock_fire):
        """RepromptValidationFailedEvent fires when reprompt exhausted."""
        validator = _StubValidator([False, False])
        svc = RepromptService(validator=validator, max_attempts=2, on_exhausted="return_last")

        svc.execute(
            llm_operation=_llm_op_factory(
                [
                    ({"v1": True}, True),
                    ({"v2": True}, True),
                ]
            ),
            original_prompt="p",
            context="action=test",
        )

        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert isinstance(event, RepromptValidationFailedEvent)
        assert event.action_name == "action=test"
        assert event.attempt == 2

    @patch("agent_actions.processing.recovery.reprompt.fire_event")
    def test_reprompt_event_not_fired_on_success(self, mock_fire):
        """No event when reprompt validation passes."""
        validator = _StubValidator([True])
        svc = RepromptService(validator=validator, max_attempts=2)

        svc.execute(
            llm_operation=_llm_op_factory([({"ok": True}, True)]),
            original_prompt="p",
        )

        mock_fire.assert_not_called()

    def test_data_validation_events_per_attempt(self):
        """UDF decorator fires DataValidationStartedEvent and outcome events per call."""
        _VALIDATION_REGISTRY.clear()
        try:

            @reprompt_validation("check failed")
            def audit_check(response):
                return response.get("valid", False)

            events_fired = []

            def capture_event(event):
                events_fired.append(type(event).__name__)

            with patch(
                "agent_actions.logging.core.manager.fire_event",
                side_effect=capture_event,
            ):
                audit_check({"valid": True})
                audit_check({"valid": False})

            assert events_fired == [
                "DataValidationStartedEvent",
                "DataValidationPassedEvent",
                "DataValidationStartedEvent",
                "DataValidationFailedEvent",
            ]
        finally:
            _VALIDATION_REGISTRY.clear()


# ---------------------------------------------------------------------------
# TestBatchRetry
# ---------------------------------------------------------------------------


class TestBatchRetry:
    """Verify batch metadata serialization, exhaustion markers, and round-trips."""

    def test_metadata_serialization_roundtrip(self):
        """BatchResult with RecoveryMetadata survives serialize → deserialize."""
        original = BatchResult(
            custom_id="rec_001",
            content={"answer": "42"},
            success=True,
            metadata={"model": "gpt-4"},
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(
                    attempts=3,
                    failures=2,
                    succeeded=True,
                    reason="network_error",
                    timestamp="2024-01-13T12:00:00",
                ),
                reprompt=RepromptMetadata(
                    attempts=2,
                    passed=True,
                    validation="check_format",
                ),
            ),
        )

        serialized = serialize_results([original])
        deserialized = deserialize_results(serialized)

        assert len(deserialized) == 1
        r = deserialized[0]

        assert r.custom_id == "rec_001"
        assert r.content == {"answer": "42"}
        assert r.success is True
        assert r.metadata == {"model": "gpt-4"}

        assert r.recovery_metadata is not None
        assert r.recovery_metadata.retry is not None
        assert r.recovery_metadata.retry.attempts == 3
        assert r.recovery_metadata.retry.failures == 2
        assert r.recovery_metadata.retry.succeeded is True
        assert r.recovery_metadata.retry.reason == "network_error"
        assert r.recovery_metadata.retry.timestamp == "2024-01-13T12:00:00"

        assert r.recovery_metadata.reprompt is not None
        assert r.recovery_metadata.reprompt.attempts == 2
        assert r.recovery_metadata.reprompt.passed is True
        assert r.recovery_metadata.reprompt.validation == "check_format"

    def test_roundtrip_retry_only(self):
        """Serialization round-trip with only retry metadata."""
        original = BatchResult(
            custom_id="rec_002",
            content="data",
            success=True,
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="rate_limit")
            ),
        )

        deserialized = deserialize_results(serialize_results([original]))
        r = deserialized[0]

        assert r.recovery_metadata.retry is not None
        assert r.recovery_metadata.retry.reason == "rate_limit"
        assert r.recovery_metadata.reprompt is None

    def test_roundtrip_reprompt_only(self):
        """Serialization round-trip with only reprompt metadata."""
        original = BatchResult(
            custom_id="rec_003",
            content="data",
            success=True,
            recovery_metadata=RecoveryMetadata(
                reprompt=RepromptMetadata(attempts=1, passed=True, validation="my_udf")
            ),
        )

        deserialized = deserialize_results(serialize_results([original]))
        r = deserialized[0]

        assert r.recovery_metadata.reprompt is not None
        assert r.recovery_metadata.reprompt.validation == "my_udf"
        assert r.recovery_metadata.retry is None

    def test_roundtrip_no_recovery(self):
        """BatchResult without recovery_metadata round-trips cleanly."""
        original = BatchResult(custom_id="rec_004", content="data", success=True)

        deserialized = deserialize_results(serialize_results([original]))
        assert deserialized[0].recovery_metadata is None

    def test_exhausted_records_marked_failed(self):
        """RecoveryMetadata with succeeded=False signals exhaustion."""
        meta = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="missing",
                timestamp="2024-01-13T12:00:00",
            )
        )

        assert meta.retry.succeeded is False
        assert meta.retry.failures == meta.retry.attempts
        assert not meta.is_empty()

        d = meta.to_dict()
        assert d["retry"]["succeeded"] is False
        assert d["retry"]["failures"] == 3

    def test_recovery_metadata_is_empty(self):
        """is_empty() returns True when both retry and reprompt are None."""
        assert RecoveryMetadata().is_empty() is True
        assert RecoveryMetadata(retry=RetryMetadata(1, 0, True, "ok")).is_empty() is False

    def test_serialization_preserves_multiple_results(self):
        """Serialization handles a list of mixed results correctly."""
        results = [
            BatchResult(
                custom_id="a",
                content="data_a",
                success=True,
                recovery_metadata=RecoveryMetadata(retry=RetryMetadata(2, 1, True, "rate_limit")),
            ),
            BatchResult(custom_id="b", content="data_b", success=True),
            BatchResult(
                custom_id="c",
                content="data_c",
                success=False,
                error="timeout",
                recovery_metadata=RecoveryMetadata(retry=RetryMetadata(3, 3, False, "timeout")),
            ),
        ]

        deserialized = deserialize_results(serialize_results(results))

        assert len(deserialized) == 3
        assert deserialized[0].recovery_metadata.retry.reason == "rate_limit"
        assert deserialized[1].recovery_metadata is None
        assert deserialized[2].recovery_metadata.retry.succeeded is False

    def test_failed_result_error_field_roundtrip(self):
        """BatchResult with success=False and error message survives serialization."""
        original = BatchResult(
            custom_id="err_001",
            content=None,
            success=False,
            error="API timeout after 30s",
            recovery_metadata=RecoveryMetadata(retry=RetryMetadata(3, 3, False, "timeout")),
        )

        serialized = serialize_results([original])
        deserialized = deserialize_results(serialized)
        r = deserialized[0]

        assert r.success is False
        assert r.content is None
        assert r.recovery_metadata.retry.succeeded is False
        assert r.recovery_metadata.retry.reason == "timeout"


# ---------------------------------------------------------------------------
# TestBuildValidationFeedback
# ---------------------------------------------------------------------------


class TestBuildValidationFeedback:
    """Verify feedback string construction."""

    def test_basic_feedback(self):
        feedback = build_validation_feedback({"key": "val"}, "wrong format")
        assert "wrong format" in feedback
        assert '"key"' in feedback
        assert "Please correct and respond again" in feedback

    def test_non_serializable_response_fallback(self):
        """Non-JSON-serializable response uses str() fallback."""

        class Custom:
            def __str__(self):
                return "custom_repr"

        feedback = build_validation_feedback(Custom(), "bad")
        assert "custom_repr" in feedback

    def test_feedback_starts_with_delimiter(self):
        feedback = build_validation_feedback({}, "msg")
        assert feedback.startswith("---")


# ---------------------------------------------------------------------------
# TestUDFRegistry
# ---------------------------------------------------------------------------


class TestUDFRegistry:
    """Verify UDF registration and retrieval."""

    def setup_method(self):
        _VALIDATION_REGISTRY.clear()

    def test_register_and_retrieve(self):
        @reprompt_validation("test feedback")
        def my_validator(response):
            return True

        func, msg = get_validation_function("my_validator")
        assert msg == "test feedback"
        assert func({"x": 1}) is True

    def test_missing_udf_raises(self):
        with pytest.raises(ValueError, match="not found"):
            get_validation_function("nonexistent")

    def test_overwrite_warns(self):
        @reprompt_validation("v1")
        def dup_check(response):
            return True

        with patch("agent_actions.processing.recovery.validation.logger") as mock_logger:

            @reprompt_validation("v2")
            def dup_check(response):  # noqa: F811
                return False

        mock_logger.warning.assert_called_once()
        assert "Overwriting" in mock_logger.warning.call_args[0][0]

    def test_decorator_preserves_function_behavior(self):
        @reprompt_validation("msg")
        def check_positive(response):
            return response.get("value", 0) > 0

        with patch("agent_actions.logging.core.manager.fire_event"):
            assert check_positive({"value": 5}) is True
            assert check_positive({"value": -1}) is False

    def test_udf_exception_propagates(self):
        """UDF exceptions propagate through the decorator (re-raised)."""

        @reprompt_validation("msg")
        def bad_udf(response):
            raise TypeError("intentional")

        with patch("agent_actions.logging.core.manager.fire_event"):
            with pytest.raises(TypeError, match="intentional"):
                bad_udf({})

    def test_udf_exception_fires_failed_event(self):
        """When a UDF raises, DataValidationFailedEvent fires before the exception propagates."""

        @reprompt_validation("msg")
        def crashing_udf(response):
            raise ValueError("bad data")

        events_fired = []

        def capture(event):
            events_fired.append(type(event).__name__)

        with patch("agent_actions.logging.core.manager.fire_event", side_effect=capture):
            with pytest.raises(ValueError, match="bad data"):
                crashing_udf({})

        assert "DataValidationStartedEvent" in events_fired
        assert "DataValidationFailedEvent" in events_fired
        assert "DataValidationPassedEvent" not in events_fired

    def teardown_method(self):
        _VALIDATION_REGISTRY.clear()


# ---------------------------------------------------------------------------
# TestRetryResultProperties
# ---------------------------------------------------------------------------


class TestRetryResultProperties:
    """Verify RetryResult dataclass semantics."""

    def test_needed_retry_true_when_attempts_gt_1(self):
        r = RetryResult(response="ok", attempts=2)
        assert r.needed_retry is True

    def test_needed_retry_true_when_exhausted(self):
        r = RetryResult(response=None, attempts=1, exhausted=True)
        assert r.needed_retry is True

    def test_needed_retry_false_first_attempt_success(self):
        r = RetryResult(response="ok", attempts=1)
        assert r.needed_retry is False


# ---------------------------------------------------------------------------
# TestRecoveryMetadataTypes
# ---------------------------------------------------------------------------


class TestRecoveryMetadataTypes:
    """Verify metadata type serialization and field semantics."""

    def test_retry_metadata_to_dict(self):
        m = RetryMetadata(
            attempts=3,
            failures=2,
            succeeded=True,
            reason="rate_limit",
            timestamp="2024-01-13T12:00:00",
        )
        d = m.to_dict()
        assert d == {
            "attempts": 3,
            "failures": 2,
            "succeeded": True,
            "reason": "rate_limit",
            "timestamp": "2024-01-13T12:00:00",
        }

    def test_retry_metadata_no_timestamp(self):
        m = RetryMetadata(attempts=1, failures=0, succeeded=True, reason="ok")
        d = m.to_dict()
        assert "timestamp" not in d

    def test_reprompt_metadata_to_dict(self):
        m = RepromptMetadata(attempts=2, passed=False, validation="my_check")
        d = m.to_dict()
        assert d == {"attempts": 2, "passed": False, "validation": "my_check"}

    def test_recovery_metadata_to_dict_both(self):
        m = RecoveryMetadata(
            retry=RetryMetadata(2, 1, True, "rate_limit"),
            reprompt=RepromptMetadata(1, True, "check"),
        )
        d = m.to_dict()
        assert "retry" in d
        assert "reprompt" in d
        assert d["retry"]["reason"] == "rate_limit"
        assert d["reprompt"]["validation"] == "check"

    def test_recovery_metadata_to_dict_empty(self):
        m = RecoveryMetadata()
        assert m.to_dict() == {}
        assert m.is_empty() is True
