"""Tests for preflight guard condition AST validation."""

from agent_actions.workflow.coordinator import (
    _check_bare_identifier_rhs,
    _find_comparison_nodes,
    validate_guard_conditions,
)


class TestFindComparisonNodes:
    """_find_comparison_nodes() recursively collects ComparisonNode instances."""

    def test_simple_comparison(self):
        """Single comparison returns one node."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse('status == "active"')
        assert result.success
        nodes = _find_comparison_nodes(result.ast.root)
        assert len(nodes) == 1

    def test_logical_and_with_two_comparisons(self):
        """AND expression returns both comparisons."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse('a == "x" AND b >= 5')
        assert result.success
        nodes = _find_comparison_nodes(result.ast.root)
        assert len(nodes) == 2

    def test_bare_truthy_check_returns_empty(self):
        """Standalone field (no comparison) returns no ComparisonNodes."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse("passes_filter")
        assert result.success
        nodes = _find_comparison_nodes(result.ast.root)
        assert len(nodes) == 0


class TestCheckBareIdentifierRhs:
    """_check_bare_identifier_rhs() detects unquoted string literals."""

    def test_bare_identifier_detected(self):
        """'status == approved' should flag 'approved' as bare identifier."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse("status == approved")
        errors = _check_bare_identifier_rhs(result.ast.root, "status == approved", "test_action")
        assert len(errors) == 1
        assert '"approved"' in errors[0]
        assert "quote it" in errors[0].lower()

    def test_quoted_string_passes(self):
        """'status == \"approved\"' should not flag anything."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        clause = 'status == "approved"'
        result = parser.parse(clause)
        errors = _check_bare_identifier_rhs(result.ast.root, clause, "test_action")
        assert errors == []

    def test_number_rhs_passes(self):
        """'score >= 6' should not flag anything."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse("score >= 6")
        errors = _check_bare_identifier_rhs(result.ast.root, "score >= 6", "test_action")
        assert errors == []

    def test_boolean_rhs_passes(self):
        """'flag == true' should not flag — true is a keyword (LiteralNode)."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        result = parser.parse("flag == true")
        errors = _check_bare_identifier_rhs(result.ast.root, "flag == true", "test_action")
        assert errors == []

    def test_nested_in_logical_expression(self):
        """Bare identifier nested inside AND/OR is still detected."""
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parser = WhereClauseParser()
        clause = 'a == "ok" AND b == unquoted'
        result = parser.parse(clause)
        errors = _check_bare_identifier_rhs(result.ast.root, clause, "test_action")
        assert len(errors) == 1
        assert "unquoted" in errors[0]


class TestValidateGuardConditions:
    """validate_guard_conditions() integration with bare-identifier detection."""

    def test_bare_identifier_returns_error(self):
        configs = {
            "my_action": {
                "guard": {
                    "clause": "hitl_status == approved",
                    "scope": "item",
                    "behavior": "filter",
                }
            }
        }
        errors = validate_guard_conditions(configs)
        assert len(errors) == 1
        assert "approved" in errors[0]
        assert "quote" in errors[0].lower()

    def test_all_example_conditions_pass(self):
        """All existing example guard conditions must pass validation."""
        configs = {
            "incident": {"guard": {"clause": 'severity == "SEV1" or severity == "SEV2"'}},
            "review": {"guard": {"clause": "consensus_score >= 6"}},
            "product": {"guard": {"clause": "compliance_passed == true"}},
            "support": {"guard": {"clause": 'severity != "low"'}},
        }
        errors = validate_guard_conditions(configs)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_no_guard_passes(self):
        """Actions without guards produce no errors."""
        configs = {"my_action": {"prompt": "do stuff"}}
        errors = validate_guard_conditions(configs)
        assert errors == []

    def test_syntax_error_still_reported(self):
        """Existing syntax error detection still works."""
        configs = {"my_action": {"guard": {"clause": "a ==== b"}}}
        errors = validate_guard_conditions(configs)
        assert len(errors) == 1
        assert "invalid guard condition" in errors[0].lower() or "parse" in errors[0].lower()
