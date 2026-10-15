"""A negative comparison on a skipped upstream's field is not true.

A guard-skipped upstream leaves its namespace null; a failed one leaves it
empty. A field read through either has no value, and under SQL semantics
``NULL != 'x'`` is not true. Evaluating it as ``None != 'x'`` scheduled the
action on records the guard was written to exclude, and the prompt then failed
to render against the null namespace the guard had just walked past.
"""

import pytest

from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    evaluate_node,
)

NULL_NAMESPACE = {"challenge_decision": None, "source": {"text": "hello"}}
EMPTY_NAMESPACE = {"challenge_decision": {}, "source": {"text": "hello"}}
LIVE_NAMESPACE = {"challenge_decision": {"verdict": "disagree"}, "source": {"text": "hello"}}


def _cmp(op: ComparisonOperator, literal=None) -> ComparisonNode:
    return ComparisonNode(FieldNode("challenge_decision.verdict"), op, LiteralNode(literal))


NEGATIVE_OPERATORS = [
    (ComparisonOperator.NE, "agree"),
    (ComparisonOperator.NOT_IN, ["agree", "partial"]),
    (ComparisonOperator.NOT_CONTAINS, "agree"),
    (ComparisonOperator.NOT_LIKE, "agr%"),
    (ComparisonOperator.NOT_BETWEEN, [1, 5]),
]


@pytest.mark.parametrize("data", [NULL_NAMESPACE, EMPTY_NAMESPACE], ids=["null", "empty"])
@pytest.mark.parametrize(("op", "literal"), NEGATIVE_OPERATORS, ids=lambda v: str(v))
def test_negative_comparison_on_a_field_with_no_value_is_not_true(data, op, literal):
    assert evaluate_node(_cmp(op, literal), data) is False


def test_the_issue_guard_does_not_run_the_action_for_a_skipped_upstream():
    guard = _cmp(ComparisonOperator.NE, "agree")
    assert evaluate_node(guard, NULL_NAMESPACE) is False
    assert evaluate_node(guard, LIVE_NAMESPACE) is True


def test_negative_comparison_still_decides_a_live_namespace_both_ways():
    guard = _cmp(ComparisonOperator.NE, "agree")
    assert evaluate_node(guard, {"challenge_decision": {"verdict": "agree"}}) is False
    assert evaluate_node(guard, {"challenge_decision": {"verdict": "reject"}}) is True


def test_a_literal_null_field_in_a_live_namespace_is_unchanged():
    data = {"challenge_decision": {"verdict": None}}
    assert evaluate_node(_cmp(ComparisonOperator.NE, "agree"), data) is True


def test_is_null_and_is_not_null_still_see_the_skipped_upstream():
    data = NULL_NAMESPACE
    assert evaluate_node(_cmp(ComparisonOperator.IS_NULL), data) is True
    assert evaluate_node(_cmp(ComparisonOperator.IS_NOT_NULL), data) is False


def test_the_null_namespace_may_be_the_right_operand():
    node = ComparisonNode(
        FieldNode("source.text"), ComparisonOperator.NE, FieldNode("challenge_decision.verdict")
    )
    assert evaluate_node(node, NULL_NAMESPACE) is False


def test_and_with_a_skipped_upstream_negative_comparison_is_false():
    node = LogicalNode(
        LogicalOperator.AND,
        ComparisonNode(FieldNode("source.text"), ComparisonOperator.EQ, LiteralNode("hello")),
        _cmp(ComparisonOperator.NE, "agree"),
    )
    assert evaluate_node(node, NULL_NAMESPACE) is False
    assert evaluate_node(node, LIVE_NAMESPACE) is True
