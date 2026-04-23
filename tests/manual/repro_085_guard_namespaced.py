"""Manual repro: guard evaluation with namespaced content (spec 085).

Tests whether guards resolve dotted paths against namespaced content.
Run: python -m pytest tests/manual/repro_085_guard_namespaced.py -v
"""

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import (
    GuardFilter,
)


def _make_evaluator() -> GuardEvaluator:
    return GuardEvaluator(guard_filter=GuardFilter())


def test_scenario_1_dotted_path_pass_true():
    """Guard: validate_question_contract.pass == false on record where pass=True.

    Condition is False → guard not matched → action should be skipped/filtered.
    """
    evaluator = _make_evaluator()
    record = {
        "content": {
            "validate_question_contract": {"violations": [], "pass": True},
            "write_scenario_question": {"question": "Q?", "options": ["A", "B", "C", "D"]},
        },
        "source_guid": "sg-1",
    }
    guard_config = {
        "clause": "validate_question_contract.pass == false",
        "scope": "item",
        "behavior": "skip",
    }

    result = evaluator.evaluate_early(record, guard_config)

    # pass is True, condition says == false → not matched → should NOT execute
    assert result.should_execute is False
    assert result.behavior == "skip"


def test_scenario_2_dotted_path_pass_false():
    """Guard: validate_question_contract.pass == false on record where pass=False.

    Condition is True → guard matched → action should execute.
    """
    evaluator = _make_evaluator()
    record = {
        "content": {
            "validate_question_contract": {"violations": ["bad"], "pass": False},
            "write_scenario_question": {"question": "Q?"},
        },
        "source_guid": "sg-2",
    }
    guard_config = {
        "clause": "validate_question_contract.pass == false",
        "scope": "item",
        "behavior": "skip",
    }

    result = evaluator.evaluate_early(record, guard_config)

    # pass is False, condition says == false → matched → should execute
    assert result.should_execute is True


def test_scenario_3_cross_namespace_field():
    """Guard referencing a field from a specific namespace."""
    evaluator = _make_evaluator()
    record = {
        "content": {
            "write_scenario_question": {"question": "Q?", "question_type": "scenario"},
            "validate_question_contract": {"pass": True},
        },
        "source_guid": "sg-3",
    }
    guard_config = {
        "clause": 'write_scenario_question.question_type == "scenario"',
        "scope": "item",
        "behavior": "skip",
    }

    result = evaluator.evaluate_early(record, guard_config)

    # question_type is "scenario" → matched → should execute
    assert result.should_execute is True


def test_scenario_4_missing_namespace_no_crash():
    """Guard referencing nonexistent namespace — should not crash."""
    evaluator = _make_evaluator()
    record = {
        "content": {
            "validate_question_contract": {"pass": True},
        },
        "source_guid": "sg-4",
    }
    guard_config = {
        "clause": "nonexistent_action.field == true",
        "scope": "item",
        "behavior": "skip",
        "passthrough_on_error": False,
    }

    result = evaluator.evaluate_early(record, guard_config)

    # Field doesn't exist → should not crash, should not execute
    assert result.should_execute is False


def test_scenario_5_multiple_namespaces():
    """Guard referencing field from one of multiple namespaces."""
    evaluator = _make_evaluator()
    record = {
        "content": {
            "extract": {"entities": ["A", "B"]},
            "classify": {"topic": "science", "confidence": 0.9},
            "enrich": {"sources": ["wiki"]},
        },
        "source_guid": "sg-5",
    }
    guard_config = {
        "clause": 'classify.topic == "science"',
        "scope": "item",
        "behavior": "filter",
    }

    result = evaluator.evaluate_early(record, guard_config)

    # topic is "science" → matched → should execute
    assert result.should_execute is True


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
