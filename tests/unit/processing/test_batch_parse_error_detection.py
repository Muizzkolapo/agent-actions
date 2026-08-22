"""Tests for batch parse error detection in ValidationStrategy.

Batch parse error reprompt detection (R4).

When a batch LLM response fails JSON parsing (_parse_error present or
content is a string in json_mode), the record must be explicitly classified
as a parse error before the UDF runs.
"""

from unittest.mock import MagicMock

from agent_actions.processing.evaluation.loop import EvaluationLoop
from agent_actions.processing.evaluation.strategies.validation import (
    ValidationStrategy,
    detect_parse_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    custom_id: str,
    content=None,
    success: bool = True,
    recovery_metadata=None,
) -> MagicMock:
    result = MagicMock()
    result.custom_id = custom_id
    result.content = content
    result.success = success
    result.recovery_metadata = recovery_metadata
    result.error = None if success else "API error"
    return result


def _always_pass(response):
    """UDF that accepts everything — a 'loose' validator."""
    return True


def _always_fail(response):
    return False


# ---------------------------------------------------------------------------
# detect_parse_error helper tests
# ---------------------------------------------------------------------------


class TestDetectParseError:
    def test_string_content_json_mode(self):
        """String content in json_mode → parse error."""
        assert detect_parse_error("not json", json_mode=True) is not None

    def test_string_content_non_json_mode(self):
        """String content in non-json_mode → NOT a parse error (legitimate text)."""
        assert detect_parse_error("plain text response", json_mode=False) is None

    def test_dict_with_parse_error_key(self):
        """Dict containing _parse_error → always a parse error regardless of json_mode."""
        content = {"raw_response": "bad", "_parse_error": "Failed to parse JSON"}
        assert detect_parse_error(content, json_mode=False) == "Failed to parse JSON"
        assert detect_parse_error(content, json_mode=True) == "Failed to parse JSON"

    def test_dict_without_parse_error_key(self):
        """Normal dict content → not a parse error."""
        assert detect_parse_error({"answer": "ok"}, json_mode=True) is None
        assert detect_parse_error({"answer": "ok"}, json_mode=False) is None

    def test_list_with_parse_error_at_index_0(self):
        """Online-path format: list with _parse_error at index 0."""
        content = [{"_parse_error": "bad json", "raw_response": ""}]
        assert detect_parse_error(content, json_mode=False) == "bad json"

    def test_list_without_parse_error(self):
        """Normal list content → not a parse error."""
        assert detect_parse_error([{"value": 10}], json_mode=True) is None

    def test_empty_parse_error_string_returns_none(self):
        """Empty _parse_error value is not treated as a parse error."""
        assert detect_parse_error({"_parse_error": ""}, json_mode=True) is None

    def test_none_content(self):
        """None content → not a parse error."""
        assert detect_parse_error(None, json_mode=True) is None

    def test_schema_echo_detected(self):
        """Schema-echo dict (LLM returned schema definition) → parse error."""
        content = {
            "title": "InlineSchema",
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        }
        error = detect_parse_error(content, json_mode=True)
        assert error is not None
        assert "Schema-echo" in error

    def test_named_schema_echo_detected(self):
        """Named schema echo (not InlineSchema) also detected."""
        content = {
            "title": "QuizOutput",
            "type": "object",
            "properties": {"score": {"type": "number"}},
        }
        error = detect_parse_error(content, json_mode=True)
        assert error is not None
        assert "Schema-echo" in error

    def test_schema_echo_detected_non_json_mode(self):
        """Schema echo detected even in non-json mode."""
        content = {
            "title": "InlineSchema",
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        assert detect_parse_error(content, json_mode=False) is not None


# ---------------------------------------------------------------------------
# ValidationStrategy.evaluate() parse error detection
# ---------------------------------------------------------------------------


class TestParseErrorDetectionInEvaluate:
    """Spec verification test 1: Parse error detected before UDF."""

    def test_batch_parse_error_detected_before_udf(self):
        """String content in json_mode fails with failure_type='parse_error', UDF never called."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return True

        strategy = ValidationStrategy(
            validation_func=tracking_validate,
            feedback_message="fix",
            json_mode=True,
        )
        result = _make_result("r1", content="not valid json")
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "parse_error"
        assert call_log == [], "UDF should NOT have been called"

    def test_parse_error_dict_detected_before_udf(self):
        """Pre-wrapped _parse_error dict fails with failure_type='parse_error'."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return True

        strategy = ValidationStrategy(
            validation_func=tracking_validate,
            feedback_message="fix",
            json_mode=True,
        )
        content = {"raw_response": "bad", "_parse_error": "Failed to parse JSON"}
        result = _make_result("r1", content=content)
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "parse_error"
        assert call_log == []

    def test_loose_udf_does_not_pass_parse_error(self):
        """Spec test 3: UDF that always returns True still fails on parse error."""
        strategy = ValidationStrategy(
            validation_func=_always_pass,
            feedback_message="fix",
            json_mode=True,
        )
        result = _make_result("r1", content="unparsed string response")
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "parse_error"

    def test_normal_dict_passes_to_udf(self):
        """Spec test 4: Valid dict content without _parse_error calls UDF normally."""
        received = []

        def capture_validate(response):
            received.append(response)
            return True

        strategy = ValidationStrategy(
            validation_func=capture_validate,
            feedback_message="fix",
            json_mode=True,
        )
        content = {"answer": "correct"}
        result = _make_result("r1", content=content)
        outcome = strategy.evaluate(result)

        assert outcome.passed is True
        assert received == [content]

    def test_udf_failure_classified_as_udf_fail(self):
        """UDF rejection returns failure_type='udf_fail'."""
        strategy = ValidationStrategy(
            validation_func=_always_fail,
            feedback_message="fix",
            json_mode=True,
        )
        result = _make_result("r1", content={"answer": "wrong"})
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "udf_fail"

    def test_api_error_classified_as_api_error(self):
        """API failure returns failure_type='api_error'."""
        strategy = ValidationStrategy(
            validation_func=_always_pass,
            feedback_message="fix",
            json_mode=True,
        )
        result = _make_result("r1", success=False)
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "api_error"

    def test_schema_echo_detected_before_udf(self):
        """Schema-echo content fails with failure_type='parse_error', UDF never called."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return True

        strategy = ValidationStrategy(
            validation_func=tracking_validate,
            feedback_message="fix",
            json_mode=True,
        )
        content = {
            "title": "InlineSchema",
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        }
        result = _make_result("r1", content=content)
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "parse_error"
        assert call_log == [], "UDF should NOT have been called"

    def test_non_json_mode_string_content_reaches_udf(self):
        """In non-json-mode, string content is NOT a parse error — UDF is called."""
        received = []

        def capture_validate(response):
            received.append(response)
            return True

        strategy = ValidationStrategy(
            validation_func=capture_validate,
            feedback_message="fix",
            json_mode=False,
        )
        result = _make_result("r1", content="plain text response")
        outcome = strategy.evaluate(result)

        assert outcome.passed is True
        assert received == ["plain text response"]


# ---------------------------------------------------------------------------
# build_feedback parse-error-specific feedback
# ---------------------------------------------------------------------------


class TestParseErrorFeedback:
    def test_parse_error_gets_json_feedback(self):
        """Parse error should get JSON-specific feedback, not generic UDF feedback."""
        strategy = ValidationStrategy(
            validation_func=_always_fail,
            feedback_message="Field 'name' is required",
            json_mode=True,
        )
        result = _make_result("r1", content="not valid json")
        feedback = strategy.build_feedback(result)

        assert "valid JSON" in feedback
        assert "Field 'name' is required" not in feedback

    def test_udf_failure_gets_normal_feedback(self):
        """UDF failure should get the normal validation feedback."""
        strategy = ValidationStrategy(
            validation_func=_always_fail,
            feedback_message="Field 'name' is required",
            json_mode=True,
        )
        result = _make_result("r1", content={"incomplete": True})
        feedback = strategy.build_feedback(result)

        assert "Field 'name' is required" in feedback


# ---------------------------------------------------------------------------
# EvaluationLoop.split() failure_types dict
# ---------------------------------------------------------------------------


class TestSplitFailureTypes:
    def test_failure_types_returned(self):
        """split() returns failure_types dict classifying each failure."""
        strategy = ValidationStrategy(
            validation_func=_always_fail,
            feedback_message="fix",
            json_mode=True,
        )
        loop = EvaluationLoop(strategy)

        results = [
            _make_result("parse_err", content="not json"),
            _make_result("udf_fail", content={"answer": "wrong"}),
            _make_result("pass_ok", content={"answer": "right"}),
        ]
        # Override UDF to pass the "right" answer
        strategy._validation_func = lambda r: r.get("answer") == "right"

        graduated, failing, failure_types = loop.split(results)

        assert len(graduated) == 1
        assert graduated[0].custom_id == "pass_ok"
        assert len(failing) == 2
        assert failure_types["parse_err"] == "parse_error"
        assert failure_types["udf_fail"] == "udf_fail"

    def test_parse_error_and_udf_fail_counted_separately(self):
        """Spec test 2: parse errors and UDF failures have distinct types."""
        strategy = ValidationStrategy(
            validation_func=lambda r: r.get("valid", False),
            feedback_message="fix",
            json_mode=True,
        )
        loop = EvaluationLoop(strategy)

        results = [
            _make_result("pe1", content="unparsed string"),
            _make_result("uf1", content={"valid": False}),
        ]

        _, failing, failure_types = loop.split(results)

        parse_errors = [cid for cid, ft in failure_types.items() if ft == "parse_error"]
        udf_fails = [cid for cid, ft in failure_types.items() if ft == "udf_fail"]

        assert parse_errors == ["pe1"]
        assert udf_fails == ["uf1"]
