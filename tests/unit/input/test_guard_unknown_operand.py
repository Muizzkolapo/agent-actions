"""An unresolvable operand is UNKNOWN, and the other side may still decide.

Guards are SQL-style, so they follow SQL's three-valued logic: a field that
cannot be resolved is UNKNOWN rather than an immediate failure.  ``UNKNOWN OR
true`` is true and ``UNKNOWN AND false`` is false, because in both the surviving
operand alone determines the result.  Everything else still raises — the answer
really is unknown.

Before this, the left operand was evaluated outside any try/except, so a typo in
the left half of an OR discarded a true right half and the record was silently
filtered while the run exited 0.
"""

import logging

import pytest

from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    MissingFieldError,
    evaluate_node,
)

DATA = {"real": {"field": "medium"}}  # 'broken' is absent entirely


def _eq(path: str, value: str) -> ComparisonNode:
    return ComparisonNode(
        left=FieldNode(field_path=path),
        operator=ComparisonOperator.EQ,
        right=LiteralNode(value=value),
    )


BROKEN = lambda: _eq("broken.field", "high")  # noqa: E731 - unresolvable
TRUE = lambda: _eq("real.field", "medium")  # noqa: E731
FALSE = lambda: _eq("real.field", "no-such-value")  # noqa: E731


def _logical(left, op, right):
    return LogicalNode(left=left(), operator=op, right=right())


class TestTheSurvivingOperandDecides:
    def test_unknown_or_true_is_true(self):
        """The reported bug: a typo on the left discarded a true right half."""
        node = _logical(BROKEN, LogicalOperator.OR, TRUE)
        assert evaluate_node(node, DATA, None) is True

    def test_unknown_and_false_is_false(self):
        """The AND sibling — same defect, confirmed by measurement."""
        node = _logical(BROKEN, LogicalOperator.AND, FALSE)
        assert evaluate_node(node, DATA, None) is False


class TestAGenuinelyUnknownResultStillRaises:
    """Only the cases where the surviving operand cannot decide."""

    def test_unknown_or_false_raises(self):
        node = _logical(BROKEN, LogicalOperator.OR, FALSE)
        with pytest.raises(MissingFieldError):
            evaluate_node(node, DATA, None)

    def test_unknown_and_true_raises(self):
        node = _logical(BROKEN, LogicalOperator.AND, TRUE)
        with pytest.raises(MissingFieldError):
            evaluate_node(node, DATA, None)

    def test_a_broken_right_operand_that_decides_nothing_raises(self):
        node = _logical(TRUE, LogicalOperator.AND, BROKEN)
        with pytest.raises(MissingFieldError):
            evaluate_node(node, DATA, None)


class TestShortCircuitingIsUnchanged:
    """The left operand already decided; the right is never evaluated."""

    def test_true_or_unknown_is_true(self):
        node = _logical(TRUE, LogicalOperator.OR, BROKEN)
        assert evaluate_node(node, DATA, None) is True

    def test_false_and_unknown_is_false(self):
        node = _logical(FALSE, LogicalOperator.AND, BROKEN)
        assert evaluate_node(node, DATA, None) is False


class TestOrdinaryConditionsAreUntouched:
    """A blanket 'swallow errors' fix must fail these."""

    def test_true_or_false_is_true(self):
        assert evaluate_node(_logical(TRUE, LogicalOperator.OR, FALSE), DATA, None) is True

    def test_false_or_false_is_false(self):
        assert evaluate_node(_logical(FALSE, LogicalOperator.OR, FALSE), DATA, None) is False

    def test_true_and_true_is_true(self):
        assert evaluate_node(_logical(TRUE, LogicalOperator.AND, TRUE), DATA, None) is True

    def test_true_and_false_is_false(self):
        assert evaluate_node(_logical(TRUE, LogicalOperator.AND, FALSE), DATA, None) is False


class TestAnUnresolvableOperandIsAlwaysAnnounced:
    """Silently returning the right answer still hides a broken config."""

    def test_it_warns_when_the_other_operand_decides(self, caplog):
        node = _logical(BROKEN, LogicalOperator.OR, TRUE)
        with caplog.at_level(logging.WARNING):
            evaluate_node(node, DATA, None)
        assert any("broken.field" in r.message % r.args for r in caplog.records), (
            "an unresolvable guard operand must name the field at WARNING level"
        )

    def test_a_clean_condition_warns_about_nothing(self, caplog):
        with caplog.at_level(logging.WARNING):
            evaluate_node(_logical(TRUE, LogicalOperator.OR, FALSE), DATA, None)
        assert caplog.records == []
