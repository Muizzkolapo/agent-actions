"""Condition parsing and record-scoped evaluation for expression expectations."""

import pytest

from agent_actions.expectations import registry
from agent_actions.expectations.expression import (
    ExpressionParseError,
    evaluate_condition,
    parse_condition,
    referenced_field_paths,
)


def test_expression_is_a_registered_type_taking_only_condition():
    etype = registry.get("expression")
    assert etype is not None
    assert etype.params == frozenset({"condition"})
    assert etype.required == frozenset({"condition"})


def test_parse_condition_returns_an_evaluable_ast():
    ast = parse_condition("score >= 80")
    assert ast.evaluate({"score": 90}) is True
    assert ast.evaluate({"score": 12}) is False


def test_parse_condition_rejects_udf_prefix_pointing_at_the_decorator():
    with pytest.raises(ExpressionParseError, match="expectation_check"):
        parse_condition("udf:tools.checks.my_check")


def test_parse_condition_rejects_dangerous_patterns():
    with pytest.raises(ExpressionParseError):
        parse_condition("__import__('os').system('true') == 0")


def test_parse_condition_rejects_unparseable_syntax():
    with pytest.raises(ExpressionParseError, match="does not parse"):
        parse_condition("score >=")


def test_referenced_field_paths_walks_logic_comparisons_and_functions():
    ast = parse_condition('score >= 80 and (verdict != "rejected" or LENGTH(tags) > 0)')
    assert referenced_field_paths(ast.root) == ["score", "verdict", "tags"]


def test_referenced_field_paths_deduplicates():
    ast = parse_condition("score >= 0 and score <= 100")
    assert referenced_field_paths(ast.root) == ["score"]


def test_evaluate_condition_true_has_empty_detail():
    assert evaluate_condition("score >= 80", {"score": 91}) == (True, "")


def test_evaluate_condition_false_detail_names_condition_and_values():
    passed, detail = evaluate_condition(
        'score >= 80 and verdict == "approved"', {"score": 64, "verdict": "approved"}
    )
    assert passed is False
    assert "score >= 80" in detail
    assert "score=64" in detail
    assert "verdict='approved'" in detail


def test_evaluate_condition_missing_field_fails_with_the_evaluators_message():
    passed, detail = evaluate_condition("score >= 80", {"points": 90})
    assert passed is False
    assert "does not exist" in detail
    assert "points" in detail


def test_evaluate_condition_dotted_path_traverses_nested_dicts():
    assert evaluate_condition('meta.status == "ok"', {"meta": {"status": "ok"}})[0] is True
