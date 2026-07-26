"""Cross-type guard comparisons must warn, not silently evaluate to not-matched.

``field == true`` against a string ``"true"`` (or ``score > 3`` against ``"5"``)
is decided by the type mismatch, not the data — every such record silently
takes the false branch. The evaluation result must stay unchanged (strict,
no coercion), but the mismatch must be announced.
"""

import logging

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter


@pytest.fixture()
def _enable_log_propagation():
    """Ensure the agent_actions logger propagates to root so caplog captures records."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


@pytest.fixture()
def _reset_mismatch_dedup():
    """Clear the warn-once state so each test observes its own warning."""
    from agent_actions.input.preprocessing.parsing import ast_nodes

    reset = getattr(ast_nodes, "_reset_type_mismatch_warnings", None)
    if reset:
        reset()
    yield
    if reset:
        reset()


def _evaluate(item, clause, behavior="filter"):
    evaluator = GuardEvaluator(GuardFilter(enable_metrics=False))
    return evaluator.evaluate(item, {"scope": "item", "clause": clause, "behavior": behavior})


def _mismatch_warnings(caplog):
    return [r for r in caplog.records if "type mismatch" in r.message]


@pytest.mark.usefixtures("_enable_log_propagation", "_reset_mismatch_dedup")
class TestEqualityTypeMismatchWarns:
    def test_string_value_vs_boolean_literal_warns_and_stays_unmatched(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _evaluate(
                {"content": {"review": {"approved": "true"}}},
                "review.approved == true",
            )

        assert result.should_execute is False  # behavior unchanged: still filtered
        warnings = _mismatch_warnings(caplog)
        assert len(warnings) == 1
        message = warnings[0].message
        assert "review.approved" in message
        assert "string" in message
        assert "boolean" in message

    def test_string_field_hint_suggests_quoting_the_literal(self, caplog):
        with caplog.at_level(logging.WARNING):
            _evaluate(
                {"content": {"review": {"approved": "true"}}},
                "review.approved == true",
            )

        message = _mismatch_warnings(caplog)[0].message
        assert '"true"' in message

    def test_string_value_vs_array_literal_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            _evaluate(
                {"content": {"assemble": {"options": "a, b"}}},
                "assemble.options != []",
            )

        warnings = _mismatch_warnings(caplog)
        assert len(warnings) == 1
        assert "assemble.options" in warnings[0].message


@pytest.mark.usefixtures("_enable_log_propagation", "_reset_mismatch_dedup")
class TestRelationalTypeMismatchWarns:
    def test_string_value_vs_number_literal_warns_and_stays_unmatched(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _evaluate(
                {"content": {"vote": {"score": "5"}}},
                "vote.score > 3",
            )

        assert result.should_execute is False
        warnings = _mismatch_warnings(caplog)
        assert len(warnings) == 1
        assert "vote.score" in warnings[0].message


@pytest.mark.usefixtures("_enable_log_propagation", "_reset_mismatch_dedup")
class TestCompatibleComparisonsStaySilent:
    def test_boolean_value_vs_boolean_literal_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _evaluate(
                {"content": {"review": {"approved": True}}},
                "review.approved == true",
            )

        assert result.should_execute is True
        assert _mismatch_warnings(caplog) == []

    def test_none_value_no_warning(self, caplog):
        """None fields come from skipped upstreams — a mismatch warning would fire
        on every legitimately skipped record."""
        with caplog.at_level(logging.WARNING):
            result = _evaluate(
                {"content": {"review": {"approved": None}}},
                "review.approved == true",
            )

        assert result.should_execute is False
        assert _mismatch_warnings(caplog) == []

    def test_boolean_value_vs_number_literal_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            _evaluate({"content": {"review": {"flag": True}}}, "review.flag == 1")

        assert _mismatch_warnings(caplog) == []

    def test_number_value_vs_number_literal_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _evaluate({"content": {"vote": {"score": 5}}}, "vote.score > 3")

        assert result.should_execute is True
        assert _mismatch_warnings(caplog) == []


@pytest.mark.usefixtures("_enable_log_propagation", "_reset_mismatch_dedup")
class TestOperandOrderAndOperatorScope:
    def test_literal_on_left_field_on_right_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            _evaluate(
                {"content": {"review": {"approved": "true"}}},
                "true == review.approved",
            )

        warnings = _mismatch_warnings(caplog)
        assert len(warnings) == 1
        assert "review.approved" in warnings[0].message

    def test_in_operator_stays_exempt(self, caplog):
        """IN compares a scalar against an array-shaped literal by design —
        a family check would flag every legitimate membership test."""
        with caplog.at_level(logging.WARNING):
            result = _evaluate(
                {"content": {"page": {"density": "high"}}},
                'page.density IN ["high", "medium"]',
            )

        assert result.should_execute is True
        assert _mismatch_warnings(caplog) == []


@pytest.mark.usefixtures("_enable_log_propagation", "_reset_mismatch_dedup")
class TestWarningDeduplication:
    def test_same_mismatch_across_records_warns_once(self, caplog):
        evaluator = GuardEvaluator(GuardFilter(enable_metrics=False))
        guard = {"scope": "item", "clause": "review.approved == true", "behavior": "filter"}
        with caplog.at_level(logging.WARNING):
            for value in ("true", "false", "true"):
                evaluator.evaluate({"content": {"review": {"approved": value}}}, guard)

        assert len(_mismatch_warnings(caplog)) == 1
