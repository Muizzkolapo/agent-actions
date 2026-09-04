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
    assert etype.params == frozenset({"condition", "row_condition"})
    assert etype.required == frozenset({"condition"})


def test_parse_condition_returns_an_evaluable_ast():
    ast = parse_condition("score >= 80")
    assert ast.evaluate({"score": 90}) is True
    assert ast.evaluate({"score": 12}) is False


def test_parse_condition_rejects_udf_prefix_pointing_at_the_decorator():
    with pytest.raises(ExpressionParseError, match="expectation_check"):
        parse_condition("udf:tools.checks.my_check")


def test_parse_condition_rejects_dangerous_patterns():
    # match pins the GuardParser blocklist path specifically; the grammar's own
    # field-name pre-validation would also reject this input with a different message.
    with pytest.raises(ExpressionParseError, match="dangerous pattern"):
        parse_condition("__import__('os').system('true') == 0")


def test_parse_condition_rejects_an_empty_condition():
    with pytest.raises(ExpressionParseError):
        parse_condition("   ")


def test_parse_condition_rejects_an_overlong_condition():
    with pytest.raises(ExpressionParseError, match="does not parse"):
        parse_condition("score >= 80 and " * 700 + "score >= 80")


def test_parse_condition_rejects_unparseable_syntax():
    with pytest.raises(ExpressionParseError, match="does not parse"):
        parse_condition("score >=")


def test_parse_condition_rejects_function_call_syntax():
    # The grammar's pre-validation rejects call syntax outright, so a function
    # vocabulary is unreachable through parse; expressions inherit that.
    with pytest.raises(ExpressionParseError, match="does not parse"):
        parse_condition("LENGTH(tags) > 0")


def test_referenced_field_paths_walks_nested_logic_and_comparisons():
    ast = parse_condition('score >= 80 and (verdict != "rejected" or tags != [])')
    assert referenced_field_paths(ast.root) == ["score", "verdict", "tags"]


def test_referenced_field_paths_covers_function_nodes():
    # Unreachable via parse today, but the AST type exists; the walker must
    # not silently skip it if the grammar ever admits calls.
    from agent_actions.input.preprocessing.parsing.ast_nodes import FieldNode, FunctionNode

    node = FunctionNode("LENGTH", [FieldNode("tags")])
    assert referenced_field_paths(node) == ["tags"]


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


def test_evaluate_condition_unquoted_literal_typo_is_a_failed_outcome_with_remediation():
    # verdict == approved (unquoted) parses approved as a field; on records
    # without that key the evaluator raises its semantic error, which must be
    # a failure carrying the quote-it remediation, not a crash.
    passed, detail = evaluate_condition("verdict == approved", {"verdict": "x"})
    assert passed is False
    assert "quotes" in detail.lower()


def test_evaluate_condition_none_valued_field_is_a_clean_false():
    passed, detail = evaluate_condition("score >= 80", {"score": None})
    assert passed is False
    assert "score=None" in detail


def test_evaluate_condition_bare_field_condition_returns_a_real_bool():
    # A bare-field condition evaluates to the field value; the bool() wrapper
    # is what turns a truthy string into True rather than leaking the value.
    result = evaluate_condition("approved", {"approved": "no"})
    assert result == (True, "")


def test_evaluate_condition_false_detail_survives_an_unread_missing_field():
    # AND short-circuits, so 'b' is never read during evaluation; rendering
    # the detail must not crash on its absence.
    passed, detail = evaluate_condition("a >= 5 and b >= 5", {"a": 1})
    assert passed is False
    assert "a=1" in detail
