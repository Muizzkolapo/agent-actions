"""Tests for the EvaluationLoop graduated pool mechanism."""

from unittest.mock import MagicMock

from agent_actions.processing.evaluation.loop import EvaluationLoop
from agent_actions.processing.types import (
    EvaluationMetadata,
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)


def _make_result(custom_id: str, recovery_metadata: RecoveryMetadata | None = None) -> MagicMock:
    """Create a mock BatchResult with typed RecoveryMetadata."""
    result = MagicMock()
    result.custom_id = custom_id
    result.recovery_metadata = recovery_metadata
    return result


def _make_strategy(evaluate_fn=None, name="test", max_attempts=3, on_exhausted="keep"):
    """Create a mock EvaluationStrategy."""
    strategy = MagicMock()
    strategy.name = name
    strategy.max_attempts = max_attempts
    strategy.on_exhausted = on_exhausted
    strategy.evaluate = evaluate_fn or (lambda r: True)
    strategy.build_feedback.return_value = "Please fix this."
    return strategy


class TestSplit:
    def test_all_pass(self):
        strategy = _make_strategy(evaluate_fn=lambda r: True)
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2")]

        graduated, failing = loop.split(results)

        assert len(graduated) == 2
        assert len(failing) == 0
        assert graduated[0].custom_id == "r1"
        assert graduated[1].custom_id == "r2"

    def test_all_fail(self):
        strategy = _make_strategy(evaluate_fn=lambda r: False)
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2")]

        graduated, failing = loop.split(results)

        assert len(graduated) == 0
        assert len(failing) == 2
        assert failing[0].custom_id == "r1"
        assert failing[1].custom_id == "r2"

    def test_mixed(self):
        def evaluate(r):
            return r.custom_id == "r1"

        strategy = _make_strategy(evaluate_fn=evaluate)
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2"), _make_result("r3")]

        graduated, failing = loop.split(results)

        assert [r.custom_id for r in graduated] == ["r1"]
        assert [r.custom_id for r in failing] == ["r2", "r3"]

    def test_already_graduated_skipped(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        already_done = _make_result(
            "r1",
            recovery_metadata=RecoveryMetadata(
                evaluation=EvaluationMetadata(passed=True, strategy_name="test"),
            ),
        )
        fresh = _make_result("r2")

        graduated, failing = loop.split([already_done, fresh])

        assert len(graduated) == 2
        assert graduated[0].custom_id == "r1"
        assert graduated[1].custom_id == "r2"

    def test_empty_input(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)

        graduated, failing = loop.split([])

        assert graduated == []
        assert failing == []

    def test_missing_recovery_metadata(self):
        """Result with no recovery_metadata attribute is treated as not graduated."""
        strategy = _make_strategy(evaluate_fn=lambda r: False)
        loop = EvaluationLoop(strategy)
        result = MagicMock(spec=[])
        result.custom_id = "r1"

        _, failing = loop.split([result])

        assert len(failing) == 1
        assert failing[0].custom_id == "r1"

    def test_graduated_not_re_evaluated(self):
        call_log = []

        def tracking_evaluate(r):
            call_log.append(r.custom_id)
            return True

        strategy = _make_strategy(evaluate_fn=tracking_evaluate)
        loop = EvaluationLoop(strategy)
        already_done = _make_result(
            "r1",
            recovery_metadata=RecoveryMetadata(
                evaluation=EvaluationMetadata(passed=True, strategy_name="test"),
            ),
        )
        fresh = _make_result("r2")

        loop.split([already_done, fresh])

        assert "r1" not in call_log
        assert "r2" in call_log

    def test_none_recovery_metadata(self):
        strategy = _make_strategy(evaluate_fn=lambda r: True)
        loop = EvaluationLoop(strategy)
        result = _make_result("r1", recovery_metadata=None)
        result.recovery_metadata = None

        graduated, _ = loop.split([result])

        assert len(graduated) == 1

    def test_evaluation_false_not_graduated(self):
        """evaluation.passed=False means not graduated — must be re-evaluated."""
        call_log = []

        def tracking_evaluate(r):
            call_log.append(r.custom_id)
            return False

        strategy = _make_strategy(evaluate_fn=tracking_evaluate)
        loop = EvaluationLoop(strategy)
        result = _make_result(
            "r1",
            recovery_metadata=RecoveryMetadata(
                evaluation=EvaluationMetadata(passed=False, strategy_name="test"),
            ),
        )

        _, failing = loop.split([result])

        assert "r1" in call_log
        assert len(failing) == 1


class TestTagGraduated:
    def test_sets_passed_true(self):
        strategy = _make_strategy(name="validation")
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")

        loop.tag_graduated([result])

        assert isinstance(result.recovery_metadata, RecoveryMetadata)
        assert result.recovery_metadata.evaluation.passed is True

    def test_sets_strategy_name(self):
        strategy = _make_strategy(name="my_strategy")
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")

        loop.tag_graduated([result])

        assert result.recovery_metadata.evaluation.strategy_name == "my_strategy"

    def test_creates_metadata_if_missing(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        result = MagicMock(spec=[])
        result.custom_id = "r1"
        result.recovery_metadata = None

        loop.tag_graduated([result])

        assert isinstance(result.recovery_metadata, RecoveryMetadata)
        assert result.recovery_metadata.evaluation.passed is True

    def test_preserves_existing_retry_metadata(self):
        """tag_graduated must not destroy retry metadata."""
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        retry = RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout")
        result = _make_result("r1", recovery_metadata=RecoveryMetadata(retry=retry))

        loop.tag_graduated([result])

        assert result.recovery_metadata.retry is retry
        assert result.recovery_metadata.retry.attempts == 2
        assert result.recovery_metadata.evaluation.passed is True

    def test_preserves_existing_reprompt_metadata(self):
        """tag_graduated must not destroy reprompt metadata."""
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        reprompt = RepromptMetadata(attempts=3, passed=True, validation="schema_check")
        result = _make_result("r1", recovery_metadata=RecoveryMetadata(reprompt=reprompt))

        loop.tag_graduated([result])

        assert result.recovery_metadata.reprompt is reprompt
        assert result.recovery_metadata.reprompt.attempts == 3
        assert result.recovery_metadata.reprompt.validation == "schema_check"
        assert result.recovery_metadata.evaluation.passed is True

    def test_multiple_results(self):
        strategy = _make_strategy(name="test")
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2"), _make_result("r3")]

        loop.tag_graduated(results)

        for r in results:
            assert isinstance(r.recovery_metadata, RecoveryMetadata)
            assert r.recovery_metadata.evaluation.passed is True
            assert r.recovery_metadata.evaluation.strategy_name == "test"


class TestBuildResubmission:
    def test_appends_feedback(self):
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "Fix the format."
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")
        context_map = {"r1": {"user_content": "original prompt"}}

        submissions = loop.build_resubmission([result], context_map)

        assert len(submissions) == 1
        assert submissions[0]["custom_id"] == "r1"
        assert submissions[0]["feedback"] == "Fix the format."
        assert "original prompt" in submissions[0]["user_content"]
        assert "Fix the format." in submissions[0]["user_content"]

    def test_uses_context_map(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")
        context_map = {
            "r1": {"user_content": "hello", "extra_field": "value"},
        }

        submissions = loop.build_resubmission([result], context_map)

        assert submissions[0]["context"] == context_map["r1"]

    def test_empty_failed_list(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)

        submissions = loop.build_resubmission([], {"r1": {}})

        assert submissions == []

    def test_missing_context_key(self):
        """Result not in context_map gets empty context dict."""
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "feedback"
        loop = EvaluationLoop(strategy)
        result = _make_result("r_missing")

        submissions = loop.build_resubmission([result], {})

        assert len(submissions) == 1
        assert submissions[0]["context"] == {}
        assert submissions[0]["custom_id"] == "r_missing"

    def test_does_not_mutate_original_result(self):
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "feedback"
        loop = EvaluationLoop(strategy)
        retry = RetryMetadata(attempts=1, failures=0, succeeded=True, reason="timeout")
        result = _make_result("r1", recovery_metadata=RecoveryMetadata(retry=retry))

        loop.build_resubmission([result], {"r1": {"user_content": "prompt"}})

        assert result.recovery_metadata.retry is retry

    def test_does_not_mutate_context_map(self):
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "feedback"
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")
        context_map = {"r1": {"user_content": "original"}}
        original_context = dict(context_map["r1"])

        loop.build_resubmission([result], context_map)

        assert context_map["r1"] == original_context

    def test_feedback_appended_after_user_content(self):
        """Feedback is separated from original content by double newline."""
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "FEEDBACK"
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")
        context_map = {"r1": {"user_content": "ORIGINAL"}}

        submissions = loop.build_resubmission([result], context_map)

        assert submissions[0]["user_content"] == "ORIGINAL\n\nFEEDBACK"

    def test_multiple_results_preserves_order(self):
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "fix"
        loop = EvaluationLoop(strategy)
        results = [_make_result("r3"), _make_result("r1"), _make_result("r2")]
        context_map = {
            "r3": {"user_content": "c3"},
            "r1": {"user_content": "c1"},
            "r2": {"user_content": "c2"},
        }

        submissions = loop.build_resubmission(results, context_map)

        assert [s["custom_id"] for s in submissions] == ["r3", "r1", "r2"]


class TestSplitThenTagRoundtrip:
    """Test the full split → tag → re-split cycle."""

    def test_graduated_survive_second_split(self):
        """Records tagged as graduated in cycle 1 are skipped in cycle 2."""
        strategy = _make_strategy(evaluate_fn=lambda r: True)
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2")]

        graduated, _ = loop.split(results)
        loop.tag_graduated(graduated)

        # Second cycle: make strategy reject everything — graduated should still pass
        loop.strategy.evaluate = lambda r: False
        graduated2, failing2 = loop.split(results)

        assert [r.custom_id for r in graduated2] == ["r1", "r2"]
        assert failing2 == []

    def test_failing_then_passing(self):
        """Records that fail in cycle 1 can graduate in cycle 2."""
        attempt = [0]

        def evaluate_second_time(r):
            attempt[0] += 1
            return attempt[0] > 1

        strategy = _make_strategy(evaluate_fn=evaluate_second_time)
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")

        _, failing = loop.split([result])
        assert len(failing) == 1

        graduated, _ = loop.split([result])
        assert len(graduated) == 1


class TestTypedMetadataRoundtrip:
    """Regression tests for the tag_graduated type mismatch bug.

    Before the fix, tag_graduated replaced RecoveryMetadata with a raw dict,
    destroying retry/reprompt metadata. _is_already_graduated checked
    isinstance(meta, dict) which never matched a RecoveryMetadata dataclass.
    """

    def test_tag_graduated_preserves_recovery_metadata_type(self):
        """tag_graduated must produce RecoveryMetadata, not a raw dict."""
        strategy = _make_strategy(name="validation")
        loop = EvaluationLoop(strategy)
        result = _make_result("r1", recovery_metadata=RecoveryMetadata())

        loop.tag_graduated([result])

        assert isinstance(result.recovery_metadata, RecoveryMetadata)
        assert isinstance(result.recovery_metadata.evaluation, EvaluationMetadata)

    def test_tag_graduated_preserves_retry_metadata(self):
        """Existing retry metadata must survive tag_graduated."""
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        retry = RetryMetadata(attempts=3, failures=2, succeeded=True, reason="timeout")
        result = _make_result("r1", recovery_metadata=RecoveryMetadata(retry=retry))

        loop.tag_graduated([result])

        assert result.recovery_metadata.retry is retry
        assert result.recovery_metadata.retry.attempts == 3
        assert result.recovery_metadata.retry.failures == 2

    def test_is_already_graduated_with_typed_metadata(self):
        """_is_already_graduated must detect typed EvaluationMetadata, not only raw dicts."""
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        meta = RecoveryMetadata(
            evaluation=EvaluationMetadata(passed=True, strategy_name="test"),
        )
        result = _make_result("r1", recovery_metadata=meta)

        assert loop._is_already_graduated(result) is True

    def test_is_already_graduated_false_when_not_passed(self):
        """evaluation.passed=False means not graduated."""
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        meta = RecoveryMetadata(
            evaluation=EvaluationMetadata(passed=False, strategy_name="test"),
        )
        result = _make_result("r1", recovery_metadata=meta)

        assert loop._is_already_graduated(result) is False

    def test_tag_then_split_with_typed_metadata(self):
        """Full roundtrip: tag → split correctly skips graduated with typed metadata."""
        strategy = _make_strategy(evaluate_fn=lambda r: True)
        loop = EvaluationLoop(strategy)
        retry = RetryMetadata(attempts=1, failures=0, succeeded=True, reason="timeout")
        result = _make_result("r1", recovery_metadata=RecoveryMetadata(retry=retry))

        graduated, _ = loop.split([result])
        loop.tag_graduated(graduated)

        # Change strategy to reject everything — graduated should still be detected
        loop.strategy.evaluate = lambda r: False
        graduated2, failing2 = loop.split([result])

        assert len(graduated2) == 1
        assert len(failing2) == 0
        # Retry metadata survived the entire roundtrip
        assert result.recovery_metadata.retry.attempts == 1

    def test_evaluation_metadata_serializes(self):
        """RecoveryMetadata.to_dict() includes evaluation when present."""
        meta = RecoveryMetadata(
            retry=RetryMetadata(attempts=1, failures=0, succeeded=True, reason="ok"),
            evaluation=EvaluationMetadata(passed=True, strategy_name="validation"),
        )
        d = meta.to_dict()

        assert d["retry"]["attempts"] == 1
        assert d["evaluation"]["passed"] is True
        assert d["evaluation"]["strategy_name"] == "validation"

    def test_recovery_metadata_not_empty_with_evaluation(self):
        """is_empty() returns False when only evaluation is set."""
        meta = RecoveryMetadata(
            evaluation=EvaluationMetadata(passed=True, strategy_name="test"),
        )

        assert meta.is_empty() is False
