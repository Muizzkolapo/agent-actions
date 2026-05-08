"""Tests for guard evaluation on empty/null upstream namespaces (spec 126).

When an upstream action fails (e.g., prompt too long), its namespace is an
empty dict {}. When an upstream action is guard-skipped, its namespace is
None.  In both cases, guard conditions referencing fields in that namespace
should evaluate to None (falsy) instead of raising MissingFieldError.
"""

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

# ── Empty namespace (upstream failed) ────────────────────────────────


class TestEmptyNamespace:
    """Guard references field in empty namespace (upstream ran but failed)."""

    def test_dotted_field_returns_none(self):
        """ns.field where ns={} returns None, no MissingFieldError."""
        node = FieldNode("upstream.exam_density")
        data = {"upstream": {}, "source": {"text": "hello"}}
        assert evaluate_node(node, data) is None

    def test_eq_comparison_returns_false(self):
        """ns.field == 'value' where ns={} evaluates to False."""
        node = ComparisonNode(
            FieldNode("upstream.exam_density"),
            ComparisonOperator.EQ,
            LiteralNode("high"),
        )
        data = {"upstream": {}, "source": {"text": "hello"}}
        assert evaluate_node(node, data) is False

    def test_is_null_returns_true(self):
        """ns.field IS NULL where ns={} returns True."""
        node = ComparisonNode(
            FieldNode("upstream.exam_density"),
            ComparisonOperator.IS_NULL,
        )
        data = {"upstream": {}}
        assert evaluate_node(node, data) is True

    def test_is_not_null_returns_false(self):
        """ns.field IS NOT NULL where ns={} returns False."""
        node = ComparisonNode(
            FieldNode("upstream.exam_density"),
            ComparisonOperator.IS_NOT_NULL,
        )
        data = {"upstream": {}}
        assert evaluate_node(node, data) is False

    def test_or_with_two_empty_fields_returns_false(self):
        """ns.a == 'x' OR ns.b == 'y' where ns={} evaluates to False."""
        node = LogicalNode(
            LogicalOperator.OR,
            ComparisonNode(
                FieldNode("upstream.a"),
                ComparisonOperator.EQ,
                LiteralNode("x"),
            ),
            ComparisonNode(
                FieldNode("upstream.b"),
                ComparisonOperator.EQ,
                LiteralNode("y"),
            ),
        )
        data = {"upstream": {}}
        assert evaluate_node(node, data) is False

    def test_multiple_fields_all_return_none(self):
        """Multiple field accesses on empty namespace all return None."""
        data = {"upstream": {}}
        assert evaluate_node(FieldNode("upstream.a"), data) is None
        assert evaluate_node(FieldNode("upstream.b"), data) is None
        assert evaluate_node(FieldNode("upstream.c"), data) is None


# ── Null namespace (guard-skipped/filtered) ──────────────────────────


class TestNullNamespace:
    """Guard references field in null namespace (guard-skipped upstream)."""

    def test_dotted_field_returns_none(self):
        """ns.field where ns=None returns None, no MissingFieldError."""
        node = FieldNode("skipped.status")
        data = {"skipped": None, "source": {"text": "hello"}}
        assert evaluate_node(node, data) is None

    def test_eq_comparison_returns_false(self):
        """ns.field == 'value' where ns=None evaluates to False."""
        node = ComparisonNode(
            FieldNode("skipped.status"),
            ComparisonOperator.EQ,
            LiteralNode("active"),
        )
        data = {"skipped": None}
        assert evaluate_node(node, data) is False

    def test_is_null_returns_true(self):
        """ns.field IS NULL where ns=None returns True."""
        node = ComparisonNode(
            FieldNode("skipped.status"),
            ComparisonOperator.IS_NULL,
        )
        data = {"skipped": None}
        assert evaluate_node(node, data) is True


# ── Strict behavior preserved ────────────────────────────────────────


class TestStrictBehaviorPreserved:
    """MissingFieldError still raised for actual config errors."""

    def test_non_empty_namespace_missing_field_raises(self):
        """ns.nonexistent where ns has data → MissingFieldError (likely typo)."""
        node = FieldNode("upstream.nonexistent")
        data = {"upstream": {"actual_field": "value"}}
        with pytest.raises(MissingFieldError, match="does not exist"):
            evaluate_node(node, data)

    def test_absent_namespace_raises(self):
        """ghost.field where ghost is not in data → MissingFieldError."""
        node = FieldNode("ghost.field")
        data = {"source": {"text": "hello"}}
        with pytest.raises(MissingFieldError, match="does not exist"):
            evaluate_node(node, data)

    def test_non_dotted_missing_field_raises(self):
        """Plain field (no dot) missing → MissingFieldError (existing behavior)."""
        node = FieldNode("nonexistent")
        data = {"name": "Alice"}
        with pytest.raises(MissingFieldError, match="does not exist"):
            evaluate_node(node, data)

    def test_non_empty_namespace_preserves_suggestions(self):
        """Flat field that exists as sub-field still gets 'Did you mean' suggestion."""
        node = FieldNode("severity")
        data = {"assess_severity": {"severity": "high"}}
        with pytest.raises(MissingFieldError, match="Did you mean"):
            evaluate_node(node, data)


# ── Mixed namespaces ─────────────────────────────────────────────────


class TestMixedNamespaces:
    """One namespace is empty/null, another has data."""

    def test_present_namespace_works_empty_returns_none(self):
        """Normal namespace resolves; empty namespace returns None."""
        data = {
            "present": {"score": 95},
            "failed": {},
        }
        assert evaluate_node(FieldNode("present.score"), data) == 95
        assert evaluate_node(FieldNode("failed.score"), data) is None

    def test_guard_or_mixed_namespaces(self):
        """present.score > 50 OR failed.status == 'ok' — left is True, right is None."""
        node = LogicalNode(
            LogicalOperator.OR,
            ComparisonNode(
                FieldNode("present.score"),
                ComparisonOperator.GT,
                LiteralNode(50),
            ),
            ComparisonNode(
                FieldNode("failed.status"),
                ComparisonOperator.EQ,
                LiteralNode("ok"),
            ),
        )
        data = {"present": {"score": 95}, "failed": {}}
        assert evaluate_node(node, data) is True

    def test_guard_and_with_empty_right_returns_false(self):
        """present.score > 50 AND failed.status == 'ok' — left True, right False."""
        node = LogicalNode(
            LogicalOperator.AND,
            ComparisonNode(
                FieldNode("present.score"),
                ComparisonOperator.GT,
                LiteralNode(50),
            ),
            ComparisonNode(
                FieldNode("failed.status"),
                ComparisonOperator.EQ,
                LiteralNode("ok"),
            ),
        )
        data = {"present": {"score": 95}, "failed": {}}
        assert evaluate_node(node, data) is False


# ── Reproduction case from spec 126 ─────────────────────────────────


class TestSpec126Reproduction:
    """Exact reproduction of the production scenario from spec 126.

    Guard condition: summarize_page_content.exam_density == "high" or
                     summarize_page_content.exam_density == "medium"
    Upstream: summarize_page_content failed → empty namespace {}
    Expected: condition evaluates to False → on_false: filter applies
    """

    def test_production_guard_condition_on_empty_namespace(self):
        node = LogicalNode(
            LogicalOperator.OR,
            ComparisonNode(
                FieldNode("summarize_page_content.exam_density"),
                ComparisonOperator.EQ,
                LiteralNode("high"),
            ),
            ComparisonNode(
                FieldNode("summarize_page_content.exam_density"),
                ComparisonOperator.EQ,
                LiteralNode("medium"),
            ),
        )
        data = {
            "summarize_page_content": {},
            "source": {"page_content": "some text"},
            "version": {"iteration": 1},
            "i": 1,
            "idx": 0,
        }
        assert evaluate_node(node, data) is False

    def test_production_guard_condition_on_present_namespace(self):
        """Same condition with present data evaluates correctly."""
        node = LogicalNode(
            LogicalOperator.OR,
            ComparisonNode(
                FieldNode("summarize_page_content.exam_density"),
                ComparisonOperator.EQ,
                LiteralNode("high"),
            ),
            ComparisonNode(
                FieldNode("summarize_page_content.exam_density"),
                ComparisonOperator.EQ,
                LiteralNode("medium"),
            ),
        )
        data = {
            "summarize_page_content": {"exam_density": "high", "summary": "..."},
            "source": {"page_content": "some text"},
        }
        assert evaluate_node(node, data) is True
