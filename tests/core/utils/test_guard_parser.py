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

    def test_parse_sql_guard(self):
        """Test parsing SQL-like guard expressions."""
        guard = 'questionable != "Low Value"'
        result = GuardParser.parse(guard)
        assert result.type == GuardType.SQL
        assert result.expression == 'questionable != "Low Value"'
        assert result.original == guard

    def test_parse_udf_guard(self):
        """Test parsing UDF guard expressions."""
        guard = "udf:get_answer_length_flag_value"
        result = GuardParser.parse(guard)
        assert result.type == GuardType.UDF
        assert result.expression == "get_answer_length_flag_value"
        assert result.original == guard

    def test_parse_udf_guard_with_whitespace(self):
        """Test parsing UDF guard with extra whitespace."""
        guard = "  udf:  check_eligibility  "
        result = GuardParser.parse(guard)
        assert result.type == GuardType.UDF
        assert result.expression == "check_eligibility"
        assert result.original == guard

    def test_parse_complex_sql_guard(self):
        """Test parsing complex SQL-like expressions."""
        guard = 'questionable == "High Value" AND confidence > 0.8'
        result = GuardParser.parse(guard)
        assert result.type == GuardType.SQL
        assert result.expression == guard
        assert result.original == guard

    def test_parse_empty_guard_raises_error(self):
        """Test that empty guard raises ValidationError."""
        with pytest.raises(ValidationError, match="Guard expression must be a non-empty string"):
            GuardParser.parse("")
        with pytest.raises(ValidationError, match="Guard expression must be a non-empty string"):
            GuardParser.parse(None)

    def test_parse_empty_udf_expression_raises_error(self):
        """Test that UDF with empty expression raises ValidationError."""
        with pytest.raises(ValidationError, match="UDF guard expression cannot be empty"):
            GuardParser.parse("udf:")
        with pytest.raises(ValidationError, match="UDF guard expression cannot be empty"):
            GuardParser.parse("udf:   ")

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
