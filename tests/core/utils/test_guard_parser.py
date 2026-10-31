"""Tests for guard expression parser."""

import pytest

from agent_actions.errors import ValidationError  # New modular pattern!
from agent_actions.guards import (
    GuardParser,
    GuardType,
    parse_guard,
)


class TestGuardParser:
    """Test suite for GuardParser."""

    @pytest.mark.parametrize(
        ("guard", "guard_type", "expression"),
        [
            pytest.param(
                'questionable != "Low Value"',
                GuardType.SQL,
                'questionable != "Low Value"',
                id="sql",
            ),
            pytest.param(
                'questionable == "High Value" AND confidence > 0.8',
                GuardType.SQL,
                'questionable == "High Value" AND confidence > 0.8',
                id="sql-complex",
            ),
            pytest.param(
                "udf:get_answer_length_flag_value",
                GuardType.UDF,
                "get_answer_length_flag_value",
                id="udf",
            ),
            pytest.param(
                "  udf:  check_eligibility  ",
                GuardType.UDF,
                "check_eligibility",
                id="udf-whitespace",
            ),
        ],
    )
    def test_parse_guard_expression(self, guard, guard_type, expression):
        result = GuardParser.parse(guard)
        assert result.type == guard_type
        assert result.expression == expression
        assert result.original == guard

    @pytest.mark.parametrize(
        ("guard", "match"),
        [
            pytest.param("", "Guard expression must be a non-empty string", id="empty-string"),
            pytest.param(None, "Guard expression must be a non-empty string", id="none"),
            pytest.param("udf:", "UDF guard expression cannot be empty", id="udf-empty"),
            pytest.param("udf:   ", "UDF guard expression cannot be empty", id="udf-whitespace"),
        ],
    )
    def test_parse_empty_guard_raises_error(self, guard, match):
        with pytest.raises(ValidationError, match=match):
            GuardParser.parse(guard)

    def test_validate_udf_expression_invalid_patterns(self):
        """Test invalid UDF expression patterns."""
        invalid_expressions = [
            # A module prefix is refused rather than resolved by its last segment:
            # UDF_REGISTRY is keyed on the bare name, so two spellings answering to
            # one function would make the module half decorative (#1188).
            "module.function",
            "myproject.tools.validators.check_answer_quality",
            ".function",
            "module.",
            "123function",
            "func-tion",
            "func tion",
        ]
        for expr in invalid_expressions:
            with pytest.raises(ValidationError, match="Invalid UDF expression format"):
                GuardParser._validate_udf_expression(expr)

    def test_validate_udf_expression_dangerous_patterns(self):
        """Test that dangerous patterns in UDF expressions raise ValidationError."""
        dangerous_expressions = [
            "__import__",
            "exec",
            "eval",
            "compile",
            "open",
        ]
        for expr in dangerous_expressions:
            with pytest.raises(ValidationError, match="potentially dangerous pattern"):
                GuardParser._validate_udf_expression(expr)

    def test_validate_udf_expression_allows_legitimate_names(self):
        """Legitimate identifiers containing dangerous substrings must NOT be blocked."""
        safe_expressions = [
            "eval_something",
            "compile_code",
            "open_file",
            "execution_status",
            "file_handler",
            "directory_scanner",
        ]
        for expr in safe_expressions:
            # Should NOT raise — these are legitimate function names
            GuardParser._validate_udf_expression(expr)

    def test_validate_udf_expression_blocks_dunder_access(self):
        """Any dunder access in UDF expressions should be blocked."""
        dunder_expressions = [
            "__class__",
            "__dict__",
            "__getattribute__",
        ]
        for expr in dunder_expressions:
            with pytest.raises(ValidationError, match="potentially dangerous pattern"):
                GuardParser._validate_udf_expression(expr)

    def test_validate_sql_expression_dangerous_patterns(self):
        """Test that dangerous patterns in SQL expressions raise ValidationError."""
        dangerous_expressions = [
            'field == "value" AND __import__("os")',
            'status != "failed" OR exec("code")',
            "eval(user_input) == True",
        ]
        for expr in dangerous_expressions:
            with pytest.raises(ValidationError, match="potentially dangerous pattern"):
                GuardParser._validate_sql_expression(expr)

    def test_validate_sql_expression_allows_legitimate_names(self):
        """Legitimate field names containing dangerous substrings must NOT be blocked."""
        safe_expressions = [
            'execution_status == "complete"',
            "file_count > 0",
            'directory_path != ""',
            'compiled_output == "success"',
            "open_tickets < 10",
            'input_file == "data.csv"',
        ]
        for expr in safe_expressions:
            # Should NOT raise
            GuardParser._validate_sql_expression(expr)

    def test_parse_guard_convenience_function(self):
        """Test the convenience parse_guard function."""
        sql_result = parse_guard('field == "value"')
        assert sql_result.type == GuardType.SQL
        udf_result = parse_guard("udf:check_eligibility")
        assert udf_result.type == GuardType.UDF


class TestGuardParserIntegration:
    """Integration tests for guard parser with real-world examples."""

    def test_quiz_workflow_guard(self):
        """Test parsing a real quiz workflow guard."""
        guard = "udf:get_answer_length_flag_value"
        result = GuardParser.parse(guard)
        assert result.type == GuardType.UDF
        assert result.expression == "get_answer_length_flag_value"

    def test_complex_sql_guard(self):
        """Test parsing complex SQL-like guard expressions."""
        guards = [
            'questionable != "Low Value"',
            'confidence > 0.8 AND status == "active"',
            'quiz_type IN ("multiple_choice", "true_false")',
            "answer_length <= 100 OR is_code_question == True",
        ]
        for guard in guards:
            result = GuardParser.parse(guard)
            assert result.type == GuardType.SQL
            assert result.expression == guard

    def test_a_nested_module_path_is_refused(self):
        """It parsed before and resolved never: UDF_REGISTRY is keyed on the bare
        function name, and the static checker read the dots as an action reference, so a
        dotted guard failed preflight rather than running (#1188)."""
        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            GuardParser.parse("udf:myproject.tools.quiz_gen.validators.check_answer_quality")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
