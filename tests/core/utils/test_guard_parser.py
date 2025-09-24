"""Tests for guard expression parser."""

import pytest
from agent_actions.core.utils.guard_parser import GuardParser, GuardType, GuardExpression, parse_guard


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
        guard = 'udf:topic_to_quiz_pipeline.get_answer_length_flag_value'
        result = GuardParser.parse(guard)

        assert result.type == GuardType.UDF
        assert result.expression == 'topic_to_quiz_pipeline.get_answer_length_flag_value'
        assert result.original == guard

    def test_parse_udf_guard_with_whitespace(self):
        """Test parsing UDF guard with extra whitespace."""
        guard = '  udf:  module.function  '
        result = GuardParser.parse(guard)

        assert result.type == GuardType.UDF
        assert result.expression == 'module.function'
        assert result.original == guard

    def test_parse_complex_sql_guard(self):
        """Test parsing complex SQL-like expressions."""
        guard = 'questionable == "High Value" AND confidence > 0.8'
        result = GuardParser.parse(guard)

        assert result.type == GuardType.SQL
        assert result.expression == guard
        assert result.original == guard

    def test_parse_empty_guard_raises_error(self):
        """Test that empty guard raises ValueError."""
        with pytest.raises(ValueError, match="Guard expression must be a non-empty string"):
            GuardParser.parse("")

        with pytest.raises(ValueError, match="Guard expression must be a non-empty string"):
            GuardParser.parse(None)

    def test_parse_empty_udf_expression_raises_error(self):
        """Test that UDF with empty expression raises ValueError."""
        with pytest.raises(ValueError, match="UDF guard expression cannot be empty"):
            GuardParser.parse("udf:")

        with pytest.raises(ValueError, match="UDF guard expression cannot be empty"):
            GuardParser.parse("udf:   ")

    def test_validate_udf_expression_valid_patterns(self):
        """Test valid UDF expression patterns."""
        valid_expressions = [
            'module.function',
            'my_module.my_function',
            'package.submodule.function',
            'deep.package.submodule.function_name',
            'topic_to_quiz_pipeline.get_answer_length_flag_value'
        ]

        for expr in valid_expressions:
            # Should not raise
            GuardParser._validate_udf_expression(expr)

    def test_validate_udf_expression_invalid_patterns(self):
        """Test invalid UDF expression patterns."""
        invalid_expressions = [
            'function',  # No module
            '.function',  # Starts with dot
            'module.',   # Ends with dot
            'module..function',  # Double dot
            'module.123function',  # Function starts with number
            'module.func-tion',   # Contains hyphen
            'module.func tion',   # Contains space
        ]

        for expr in invalid_expressions:
            with pytest.raises(ValueError, match="Invalid UDF expression format"):
                GuardParser._validate_udf_expression(expr)

    def test_validate_udf_expression_dangerous_patterns(self):
        """Test that dangerous patterns in UDF expressions raise ValueError."""
        dangerous_expressions = [
            'module.__import__',
            'package.exec',
            'my_module.eval_something',
            'test.compile_code',
            'utils.open_file',
        ]

        for expr in dangerous_expressions:
            with pytest.raises(ValueError, match="potentially dangerous pattern"):
                GuardParser._validate_udf_expression(expr)

    def test_validate_sql_expression_dangerous_patterns(self):
        """Test that dangerous patterns in SQL expressions raise ValueError."""
        dangerous_expressions = [
            'field == "value" AND __import__("os")',
            'status != "failed" OR exec("code")',
            'eval(user_input) == True',
        ]

        for expr in dangerous_expressions:
            with pytest.raises(ValueError, match="potentially dangerous pattern"):
                GuardParser._validate_sql_expression(expr)

    def test_is_udf_guard(self):
        """Test UDF guard detection."""
        assert GuardParser.is_udf_guard('udf:module.function')
        assert GuardParser.is_udf_guard('  udf:module.function  ')
        assert not GuardParser.is_udf_guard('field != "value"')
        assert not GuardParser.is_udf_guard('')
        assert not GuardParser.is_udf_guard(None)

    def test_is_sql_guard(self):
        """Test SQL guard detection."""
        assert GuardParser.is_sql_guard('field != "value"')
        assert GuardParser.is_sql_guard('status == "active"')
        assert not GuardParser.is_sql_guard('udf:module.function')
        assert not GuardParser.is_sql_guard('')
        assert not GuardParser.is_sql_guard(None)

    def test_parse_guard_convenience_function(self):
        """Test the convenience parse_guard function."""
        # SQL guard
        sql_result = parse_guard('field == "value"')
        assert sql_result.type == GuardType.SQL

        # UDF guard
        udf_result = parse_guard('udf:module.function')
        assert udf_result.type == GuardType.UDF

    def test_guard_expression_repr(self):
        """Test GuardExpression string representation."""
        expr = GuardExpression(GuardType.UDF, 'module.function', 'udf:module.function')
        repr_str = repr(expr)
        assert 'GuardExpression' in repr_str
        assert 'UDF' in repr_str
        assert 'module.function' in repr_str


class TestGuardParserIntegration:
    """Integration tests for guard parser with real-world examples."""

    def test_quiz_workflow_guard(self):
        """Test parsing a real quiz workflow guard."""
        guard = 'udf:topic_to_quiz_pipeline.get_answer_length_flag_value'
        result = GuardParser.parse(guard)

        assert result.type == GuardType.UDF
        assert result.expression == 'topic_to_quiz_pipeline.get_answer_length_flag_value'

    def test_complex_sql_guard(self):
        """Test parsing complex SQL-like guard expressions."""
        guards = [
            'questionable != "Low Value"',
            'confidence > 0.8 AND status == "active"',
            'quiz_type IN ("multiple_choice", "true_false")',
            'answer_length <= 100 OR is_code_question == True',
        ]

        for guard in guards:
            result = GuardParser.parse(guard)
            assert result.type == GuardType.SQL
            assert result.expression == guard

    def test_nested_module_udf(self):
        """Test UDF with deeply nested module paths."""
        guard = 'udf:qanalabs.tools.quiz_gen.validators.check_answer_quality'
        result = GuardParser.parse(guard)

        assert result.type == GuardType.UDF
        assert result.expression == 'qanalabs.tools.quiz_gen.validators.check_answer_quality'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])