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
    GuardSemanticError,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    MissingFieldError,
    _reset_type_mismatch_warnings,
    evaluate_node,
)

DATA = {"real": {"field": "medium"}}  # 'broken' is absent entirely


@pytest.fixture(autouse=True)
def _clear_warning_dedupe():
    """The warning dedupes per clause, so leakage would mask a missing warning."""
    _reset_type_mismatch_warnings()
    yield
    _reset_type_mismatch_warnings()


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
        assert any("broken.field" in r.getMessage() for r in caplog.records), (
            "an unresolvable guard operand must name the field at WARNING level"
        )

    def test_a_clean_condition_warns_about_nothing(self, caplog):
        with caplog.at_level(logging.WARNING):
            evaluate_node(_logical(TRUE, LogicalOperator.OR, FALSE), DATA, None)
        assert caplog.records == []


class TestAConfigErrorIsNotAnUnknownValue:
    """A flat field that exists inside a namespace fails for *every* record.

    guards/ARCHITECTURE.md item 8 keeps that a SEMANTIC config error so the
    guard behaviour always applies; absorbing it as UNKNOWN would let a typo
    pass records the config never meant to pass.
    """

    NAMESPACED = {"assess": {"severity": "low", "ok": "yes"}}

    def test_a_flat_reference_still_raises_even_when_the_other_side_is_true(self):
        node = LogicalNode(
            left=_eq("severity", "high"),
            operator=LogicalOperator.OR,
            right=_eq("assess.ok", "yes"),
        )
        with pytest.raises(MissingFieldError) as exc:
            evaluate_node(node, self.NAMESPACED, None)
        assert exc.value.is_config_error is True

    def test_the_same_broken_guard_classifies_the_same_for_every_record(self):
        """Config-ness must come from the reference, not from what a record holds.

        Deciding it from "does this record have the field somewhere" would make
        one misconfigured guard filter some records and pass others.
        """
        present = {"assess": {"severity": "low", "ok": "yes"}}
        absent = {"assess": {"ok": "yes"}}
        nested = {"assess": {"ok": "yes", "meta": {"severity": "low"}}}
        flags = []
        for data in (present, absent, nested):
            with pytest.raises(MissingFieldError) as exc:
                evaluate_node(_eq("severity", "high"), data, None)
            flags.append(exc.value.is_config_error)
        assert flags == [True, True, True], (
            f"same clause, three records, inconsistent classification: {flags}"
        )

    def test_a_flat_reference_stays_a_config_error_when_the_other_side_is_true(self):
        """The record that lacks the field entirely must not slip through."""
        node = LogicalNode(
            left=_eq("severity", "high"),
            operator=LogicalOperator.OR,
            right=_eq("assess.ok", "yes"),
        )
        with pytest.raises(MissingFieldError):
            evaluate_node(node, {"assess": {"ok": "yes"}}, None)

    def test_a_genuinely_missing_field_is_not_a_config_error(self):
        with pytest.raises(MissingFieldError) as exc:
            evaluate_node(_eq("broken.field", "high"), DATA, None)
        assert exc.value.is_config_error is False


class TestTheCatchStaysNarrow:
    """Only field resolution is UNKNOWN. Structural errors must still surface."""

    def test_a_semantic_error_in_an_operand_is_not_swallowed(self):
        """An unquoted RHS is broken config, not a missing value."""
        node = LogicalNode(
            left=ComparisonNode(
                left=FieldNode(field_path="real.field"),
                operator=ComparisonOperator.EQ,
                right=FieldNode(field_path="unquoted_word"),
            ),
            operator=LogicalOperator.OR,
            right=_eq("real.field", "medium"),
        )
        with pytest.raises(GuardSemanticError):
            evaluate_node(node, DATA, None)


class TestNotOfAnUnknownIsStillUnknown:
    def test_not_unknown_raises(self):
        node = LogicalNode(
            left=_eq("broken.field", "high"), operator=LogicalOperator.NOT, right=None
        )
        with pytest.raises(MissingFieldError):
            evaluate_node(node, DATA, None)


class TestTheWarningDoesNotFloodTheLog:
    def test_the_same_clause_warns_once_across_many_records(self, caplog):
        node = _logical(BROKEN, LogicalOperator.OR, TRUE)
        with caplog.at_level(logging.WARNING):
            for _ in range(50):
                evaluate_node(node, DATA, None)
        warnings = [r for r in caplog.records if "could not be resolved" in r.getMessage()]
        assert len(warnings) == 1, f"guards run per record; got {len(warnings)} warnings for 50"

    def test_it_does_not_warn_when_the_result_is_still_unknown(self, caplog):
        """The message claims the other operand decided — only say that when true."""
        node = _logical(BROKEN, LogicalOperator.OR, FALSE)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(MissingFieldError):
                evaluate_node(node, DATA, None)
        assert [r for r in caplog.records if "decided the result" in r.getMessage()] == []
