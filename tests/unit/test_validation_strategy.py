"""Tests for ValidationStrategy and graduated pool integration."""

from unittest.mock import MagicMock

from agent_actions.processing.evaluation.loop import EvaluationLoop, EvaluationStrategy
from agent_actions.processing.evaluation.strategies.validation import ValidationStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    custom_id: str,
    content: dict | None = None,
    success: bool = True,
    recovery_metadata=None,
) -> MagicMock:
    """Create a mock BatchResult."""
    result = MagicMock()
    result.custom_id = custom_id
    result.content = content
    result.success = success
    result.recovery_metadata = recovery_metadata
    return result


def _always_pass(response):
    return True


def _always_fail(response):
    return False


# ---------------------------------------------------------------------------
# ValidationStrategy unit tests
# ---------------------------------------------------------------------------


class TestValidationStrategyProtocol:
    def test_satisfies_evaluation_strategy_protocol(self):
        strategy = ValidationStrategy(
            validation_func=_always_pass,
            feedback_message="fix it",
        )
        assert isinstance(strategy, EvaluationStrategy)

    def test_name_is_validation(self):
        strategy = ValidationStrategy(validation_func=_always_pass, feedback_message="fix")
        assert strategy.name == "validation"

    def test_max_attempts_default(self):
        strategy = ValidationStrategy(validation_func=_always_pass, feedback_message="fix")
        assert strategy.max_attempts == 3

    def test_max_attempts_custom(self):
        strategy = ValidationStrategy(
            validation_func=_always_pass, feedback_message="fix", max_attempts=5
        )
        assert strategy.max_attempts == 5

    def test_on_exhausted_default(self):
        strategy = ValidationStrategy(validation_func=_always_pass, feedback_message="fix")
        assert strategy.on_exhausted == "return_last"

    def test_on_exhausted_custom(self):
        strategy = ValidationStrategy(
            validation_func=_always_pass, feedback_message="fix", on_exhausted="raise"
        )
        assert strategy.on_exhausted == "raise"


class TestValidationStrategyEvaluate:
    def test_passing_result(self):
        strategy = ValidationStrategy(validation_func=_always_pass, feedback_message="fix")
        result = _make_result("r1", content={"valid": True})
        assert strategy.evaluate(result) is True

    def test_failing_result(self):
        strategy = ValidationStrategy(validation_func=_always_fail, feedback_message="fix")
        result = _make_result("r1", content={"valid": False})
        assert strategy.evaluate(result) is False

    def test_success_false_fails_validation(self):
        """API-failed results fail validation without calling the UDF."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return False

        strategy = ValidationStrategy(validation_func=tracking_validate, feedback_message="fix")
        result = _make_result("r1", success=False)
        assert strategy.evaluate(result) is False
        assert call_log == []

    def test_success_false_with_content_still_fails(self):
        """API failures with partial content still fail — UDF is never called."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return True  # would pass if called

        strategy = ValidationStrategy(validation_func=tracking_validate, feedback_message="fix")
        result = _make_result("r1", content={"partial": "data"}, success=False)
        assert strategy.evaluate(result) is False
        assert call_log == []

    def test_already_passed_skips_validation(self):
        """Results with reprompt.passed=True skip validation."""
        call_log = []

        def tracking_validate(response):
            call_log.append(response)
            return False

        reprompt_meta = MagicMock()
        reprompt_meta.passed = True
        recovery = MagicMock()
        recovery.reprompt = reprompt_meta

        strategy = ValidationStrategy(validation_func=tracking_validate, feedback_message="fix")
        result = _make_result("r1", recovery_metadata=recovery)
        assert strategy.evaluate(result) is True
        assert call_log == []

    def test_exception_in_validation_returns_false(self):
        """Exceptions in validation UDF are caught as failures."""

        def raising_validate(response):
            raise ValueError("bad data")

        strategy = ValidationStrategy(validation_func=raising_validate, feedback_message="fix")
        result = _make_result("r1")
        assert strategy.evaluate(result) is False

    def test_uses_result_content(self):
        """Validation function receives result.content."""
        received = []

        def capture_validate(response):
            received.append(response)
            return True

        strategy = ValidationStrategy(validation_func=capture_validate, feedback_message="fix")
        content = {"key": "value"}
        result = _make_result("r1", content=content)
        strategy.evaluate(result)
        assert received == [content]


class TestValidationStrategyBuildFeedback:
    def test_returns_feedback_string(self):
        strategy = ValidationStrategy(
            validation_func=_always_fail, feedback_message="Field 'name' is required"
        )
        result = _make_result("r1", content={"incomplete": True})
        feedback = strategy.build_feedback(result)
        assert isinstance(feedback, str)
        assert "Field 'name' is required" in feedback

    def test_includes_failed_response(self):
        strategy = ValidationStrategy(validation_func=_always_fail, feedback_message="invalid")
        result = _make_result("r1", content={"bad": "data"})
        feedback = strategy.build_feedback(result)
        assert "bad" in feedback

    def test_api_failure_returns_api_error_feedback(self):
        """API-failed results get a feedback message about the API error, not validation."""
        strategy = ValidationStrategy(validation_func=_always_fail, feedback_message="fix")
        result = _make_result("r1", content=None, success=False)
        feedback = strategy.build_feedback(result)
        assert isinstance(feedback, str)
        assert "API error" in feedback
        assert "fix" not in feedback  # should NOT use the validation feedback message


# ---------------------------------------------------------------------------
# Graduated pool integration: ValidationStrategy + EvaluationLoop
# ---------------------------------------------------------------------------


class TestGraduatedPoolIntegration:
    """Test ValidationStrategy with EvaluationLoop — the graduated pool pattern."""

    def test_all_pass_first_attempt(self):
        strategy = ValidationStrategy(validation_func=_always_pass, feedback_message="fix")
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2")]

        graduated, failing = loop.split(results)

        assert len(graduated) == 2
        assert len(failing) == 0

    def test_partial_pass_splits_correctly(self):
        def validate(response):
            return response.get("valid", False)

        strategy = ValidationStrategy(validation_func=validate, feedback_message="fix")
        loop = EvaluationLoop(strategy)
        results = [
            _make_result("r1", content={"valid": True}),
            _make_result("r2", content={"valid": False}),
            _make_result("r3", content={"valid": True}),
        ]

        graduated, failing = loop.split(results)

        assert [r.custom_id for r in graduated] == ["r1", "r3"]
        assert [r.custom_id for r in failing] == ["r2"]

    def test_failure_set_shrinks_each_cycle(self):
        """With deterministic validation, failure set can only shrink."""
        attempt_counter = [0]

        def improving_validate(response):
            # Pass more records each cycle
            threshold = response.get("threshold", 0)
            return attempt_counter[0] >= threshold

        strategy = ValidationStrategy(validation_func=improving_validate, feedback_message="fix")
        loop = EvaluationLoop(strategy)

        results = [
            _make_result("r1", content={"threshold": 0}),  # passes cycle 0
            _make_result("r2", content={"threshold": 1}),  # passes cycle 1
            _make_result("r3", content={"threshold": 2}),  # passes cycle 2
        ]

        # Cycle 0
        attempt_counter[0] = 0
        graduated_0, failing_0 = loop.split(results)
        assert len(graduated_0) == 1
        assert len(failing_0) == 2

        # Cycle 1 — only failing records re-evaluated
        attempt_counter[0] = 1
        graduated_1, failing_1 = loop.split(failing_0)
        assert len(graduated_1) == 1
        assert len(failing_1) == 1

        # Cycle 2
        attempt_counter[0] = 2
        graduated_2, failing_2 = loop.split(failing_1)
        assert len(graduated_2) == 1
        assert len(failing_2) == 0

        total_graduated = graduated_0 + graduated_1 + graduated_2
        assert [r.custom_id for r in total_graduated] == ["r1", "r2", "r3"]

    def test_graduated_never_re_evaluated(self):
        """Once graduated, a record is never passed to evaluate() again."""
        evaluated_ids = []

        def tracking_validate(response):
            return True

        strategy = ValidationStrategy(validation_func=tracking_validate, feedback_message="fix")
        # Patch to track calls
        original_evaluate = strategy.evaluate

        def tracking_evaluate(result):
            evaluated_ids.append(result.custom_id)
            return original_evaluate(result)

        strategy.evaluate = tracking_evaluate
        loop = EvaluationLoop(strategy)

        results = [_make_result("r1"), _make_result("r2")]

        # Cycle 0 — both evaluated, both graduate
        graduated_0, _ = loop.split(results)
        assert set(evaluated_ids) == {"r1", "r2"}

        # Cycle 1 — pass same results, but since we're using the graduated pool
        # pattern correctly, only new active_results go into split.
        # Simulating: active_results would be reprompt results (empty in this case)
        evaluated_ids.clear()
        graduated_1, _ = loop.split([])
        assert evaluated_ids == []

    def test_api_failures_are_not_graduated(self):
        """Results with success=False are routed to still_failing, not graduated."""
        strategy = ValidationStrategy(validation_func=_always_fail, feedback_message="fix")
        loop = EvaluationLoop(strategy)

        results = [
            _make_result("r1", success=True),
            _make_result("r2", success=False),  # API failure
        ]

        graduated, failing = loop.split(results)

        assert [r.custom_id for r in graduated] == []
        assert [r.custom_id for r in failing] == ["r1", "r2"]

    def test_mixed_api_failures_and_validation_failures(self):
        """API failures and validation failures both end up in still_failing."""

        def validate(response):
            return response.get("valid", False)

        strategy = ValidationStrategy(validation_func=validate, feedback_message="fix")
        loop = EvaluationLoop(strategy)
        results = [
            _make_result("pass-1", content={"valid": True}, success=True),
            _make_result("api-fail", content=None, success=False),
            _make_result("val-fail", content={"valid": False}, success=True),
            _make_result("pass-2", content={"valid": True}, success=True),
        ]

        graduated, failing = loop.split(results)

        assert [r.custom_id for r in graduated] == ["pass-1", "pass-2"]
        assert [r.custom_id for r in failing] == ["api-fail", "val-fail"]

    def test_api_failure_resubmission_uses_api_error_feedback(self):
        """Resubmission of API-failed records uses API error feedback, not validation."""
        strategy = ValidationStrategy(validation_func=_always_fail, feedback_message="validate")
        loop = EvaluationLoop(strategy)
        result = _make_result("api-fail", content=None, success=False)
        context_map = {"api-fail": {"user_content": "original prompt"}}

        submissions = loop.build_resubmission([result], context_map)

        assert len(submissions) == 1
        assert "API error" in submissions[0]["feedback"]
        assert "validate" not in submissions[0]["feedback"]

    def test_build_feedback_for_failing(self):
        strategy = ValidationStrategy(
            validation_func=_always_fail, feedback_message="Missing required field"
        )
        loop = EvaluationLoop(strategy)
        result = _make_result("r1", content={"incomplete": True})
        context_map = {"r1": {"user_content": "original prompt"}}

        submissions = loop.build_resubmission([result], context_map)

        assert len(submissions) == 1
        assert "Missing required field" in submissions[0]["feedback"]
        assert "original prompt" in submissions[0]["user_content"]
