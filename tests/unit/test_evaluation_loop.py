"""Tests for the EvaluationLoop graduated pool mechanism."""

from unittest.mock import MagicMock

from agent_actions.processing.evaluation.loop import EvaluationLoop


def _make_result(custom_id: str, recovery_metadata: dict | None = None) -> MagicMock:
    """Create a mock BatchResult."""
    result = MagicMock()
    result.custom_id = custom_id
    result.recovery_metadata = recovery_metadata if recovery_metadata is not None else {}
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
        already_done = _make_result("r1", recovery_metadata={"evaluation": {"passed": True}})
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
        result = MagicMock(spec=[])  # no attributes at all
        result.custom_id = "r1"
        # spec=[] means no recovery_metadata attr → getattr returns None

        _, failing = loop.split([result])

        assert len(failing) == 1
        assert failing[0].custom_id == "r1"

    def test_graduated_not_re_evaluated(self):
        """Already-graduated records must not trigger strategy.evaluate()."""
        call_log = []

        def tracking_evaluate(r):
            call_log.append(r.custom_id)
            return True

        strategy = _make_strategy(evaluate_fn=tracking_evaluate)
        loop = EvaluationLoop(strategy)
        already_done = _make_result("r1", recovery_metadata={"evaluation": {"passed": True}})
        fresh = _make_result("r2")

        loop.split([already_done, fresh])

        assert "r1" not in call_log
        assert "r2" in call_log

    def test_none_recovery_metadata(self):
        """recovery_metadata=None is treated as not graduated."""
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
        result = _make_result("r1", recovery_metadata={"evaluation": {"passed": False}})

        _, failing = loop.split([result])

        assert "r1" in call_log
        assert len(failing) == 1


class TestTagGraduated:
    def test_sets_passed_true(self):
        strategy = _make_strategy(name="validation")
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")

        loop.tag_graduated([result])

        assert result.recovery_metadata["evaluation"]["passed"] is True

    def test_sets_strategy_name(self):
        strategy = _make_strategy(name="my_strategy")
        loop = EvaluationLoop(strategy)
        result = _make_result("r1")

        loop.tag_graduated([result])

        assert result.recovery_metadata["evaluation"]["strategy_name"] == "my_strategy"

    def test_creates_metadata_if_missing(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        result = MagicMock(spec=[])
        result.custom_id = "r1"
        result.recovery_metadata = None

        loop.tag_graduated([result])

        assert result.recovery_metadata["evaluation"]["passed"] is True

    def test_preserves_existing_metadata_keys(self):
        strategy = _make_strategy()
        loop = EvaluationLoop(strategy)
        result = _make_result("r1", recovery_metadata={"retry": {"attempts": 2}})

        loop.tag_graduated([result])

        assert result.recovery_metadata["retry"] == {"attempts": 2}
        assert result.recovery_metadata["evaluation"]["passed"] is True

    def test_multiple_results(self):
        strategy = _make_strategy(name="test")
        loop = EvaluationLoop(strategy)
        results = [_make_result("r1"), _make_result("r2"), _make_result("r3")]

        loop.tag_graduated(results)

        for r in results:
            assert r.recovery_metadata["evaluation"]["passed"] is True
            assert r.recovery_metadata["evaluation"]["strategy_name"] == "test"


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
        """build_resubmission must not modify the BatchResult objects."""
        strategy = _make_strategy()
        strategy.build_feedback.return_value = "feedback"
        loop = EvaluationLoop(strategy)
        result = _make_result("r1", recovery_metadata={"existing": "data"})
        original_meta = dict(result.recovery_metadata)

        loop.build_resubmission([result], {"r1": {"user_content": "prompt"}})

        assert result.recovery_metadata == original_meta

    def test_does_not_mutate_context_map(self):
        """build_resubmission must not modify the context_map dict."""
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
