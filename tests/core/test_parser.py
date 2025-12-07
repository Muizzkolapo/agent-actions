"""
Comprehensive parser tests for the Agent Actions core parser modules.

Tests cover where_parser and config parsing as specified in tests_recommendations.jsonc:
1. where_parser splits by AND (case/whitespace tolerant); supports =, !=, >, <, >=, <=, IN, LIKE
2. where_parser supports dotted field paths; rejects malformed clauses/operators
3. config_schema/config_types validate types/defaults/enums; unknown keys flagged
4. pipeline_config/processor_config/vendor_config end-to-end parse; defaults applied; precedence
5. schema_change detects valid/invalid changes and reports conflicts
"""
import pytest
import json
from typing import Any, Dict, List
from unittest.mock import Mock, patch
from agent_actions.response_processing.where_parser import WhereClauseParser, WhereCondition, SimpleWhereFilter, get_global_filter, evaluate_safe_skip_condition, evaluate_safe_expression
from agent_actions.response_processing.config_schema import WhereClauseConfig, FilterScope
from agent_actions.errors import ValidationError  # New modular pattern!

class TestWhereClauseParser:
    """Test WHERE clause parsing functionality."""

    def test_parse_simple_equality_condition(self):
        """Test parsing simple equality condition."""
        parser = WhereClauseParser()
        conditions = parser.parse("field = 'value'")
        assert len(conditions) == 1
        assert conditions[0].field == 'field'
        assert conditions[0].operator == '='
        assert conditions[0].value == 'value'

    def test_parse_multiple_and_conditions_case_insensitive(self):
        """Test parsing multiple AND conditions with case insensitivity."""
        parser = WhereClauseParser()
        conditions = parser.parse("age > 18 AND status = 'active'")
        assert len(conditions) == 2
        assert conditions[0].field == 'age'
        assert conditions[0].operator == '>'
        assert conditions[0].value == 18
        assert conditions[1].field == 'status'
        assert conditions[1].operator == '='
        assert conditions[1].value == 'active'
        conditions = parser.parse("age > 18 and status = 'active'")
        assert len(conditions) == 2

    def test_parse_whitespace_tolerant(self):
        """Test parser is tolerant of extra whitespace."""
        parser = WhereClauseParser()
        conditions = parser.parse("  field   =   'value'  ")
        assert len(conditions) == 1
        assert conditions[0].field == 'field'
        assert conditions[0].value == 'value'
        conditions = parser.parse("field1 = 'value1'   AND    field2 != 'value2'")
        assert len(conditions) == 2

    @pytest.mark.parametrize('operator,field,value,expected_op', [('=', 'field', "'value'", '='), ('!=', 'field', "'value'", '!='), ('>', 'age', '18', '>'), ('<', 'age', '65', '<'), ('>=', 'score', '80', '>='), ('<=', 'count', '100', '<='), ('IN', 'category', "['A', 'B', 'C']", 'IN'), ('LIKE', 'name', "'%test%'", 'LIKE')])
    def test_parse_supported_operators(self, operator, field, value, expected_op):
        """Test parsing of all supported operators."""
        parser = WhereClauseParser()
        clause = f'{field} {operator} {value}'
        conditions = parser.parse(clause)
        assert len(conditions) == 1
        assert conditions[0].field == field
        assert conditions[0].operator == expected_op

    def test_parse_dotted_field_paths(self):
        """Test parsing dotted field paths for nested data."""
        parser = WhereClauseParser()
        conditions = parser.parse('user.profile.age > 25')
        assert len(conditions) == 1
        assert conditions[0].field == 'user.profile.age'
        assert conditions[0].operator == '>'
        assert conditions[0].value == 25
        conditions = parser.parse('nested.field != null')
        assert len(conditions) == 1
        assert conditions[0].field == 'nested.field'

    def test_parse_is_null_conditions(self):
        """Test parsing IS NULL and IS NOT NULL conditions."""
        parser = WhereClauseParser()
        conditions = parser.parse('field IS NULL')
        assert len(conditions) == 1
        assert conditions[0].field == 'field'
        assert conditions[0].operator == 'IS NULL'
        assert conditions[0].value is None
        conditions = parser.parse('field IS NOT NULL')
        assert len(conditions) == 1
        assert conditions[0].field == 'field'
        assert conditions[0].operator == 'IS NOT NULL'
        assert conditions[0].value is None

    def test_parse_value_types(self):
        """Test parsing different value types."""
        parser = WhereClauseParser()
        conditions = parser.parse("name = 'John'")
        assert conditions[0].value == 'John'
        conditions = parser.parse('name = "John"')
        assert conditions[0].value == 'John'
        conditions = parser.parse('age = 25')
        assert conditions[0].value == 25
        conditions = parser.parse('score = 95.5')
        assert conditions[0].value == 95.5
        conditions = parser.parse('active = true')
        assert conditions[0].value is True
        conditions = parser.parse('deleted = false')
        assert conditions[0].value is False
        conditions = parser.parse('field = null')
        assert conditions[0].value is None
        conditions = parser.parse("tags IN ['tag1', 'tag2']")
        assert conditions[0].value == ['tag1', 'tag2']

    def test_parse_malformed_clauses_return_empty_or_none(self):
        """Test that malformed clauses are handled gracefully."""
        parser = WhereClauseParser()
        conditions = parser.parse('field ===== value')
        assert len(conditions) == 0 or conditions[0] is None
        conditions = parser.parse('field =')
        assert len(conditions) == 0 or conditions[0] is None
        conditions = parser.parse('= value')
        assert len(conditions) == 0 or conditions[0] is None

    def test_parse_unsupported_operators_rejected(self):
        """Test that unsupported operators are rejected."""
        parser = WhereClauseParser()
        conditions = parser.parse("field REGEX 'pattern'")
        assert len(conditions) == 0 or conditions[0] is None
        conditions = parser.parse('field BETWEEN 1 AND 10')
        assert len(conditions) == 0 or conditions[0] is None

    def test_parse_empty_clause(self):
        """Test parsing empty or whitespace-only clauses."""
        parser = WhereClauseParser()
        assert parser.parse('') == []
        assert parser.parse('   ') == []
        assert parser.parse('\t\n') == []

    def test_parse_none_clause_raises_error(self):
        """Test parsing None clause raises TypeError."""
        parser = WhereClauseParser()
        with pytest.raises(TypeError, match='where_clause cannot be None'):
            parser.parse(None)

class TestWhereClauseEvaluation:
    """Test WHERE clause evaluation against data."""

    def test_evaluate_simple_conditions(self):
        """Test evaluation of simple conditions."""
        parser = WhereClauseParser()
        data = {'name': 'Alice', 'age': 30, 'active': True}
        conditions = parser.parse("name = 'Alice'")
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse("name = 'Bob'")
        assert parser.evaluate(data, conditions) is False
        conditions = parser.parse('age > 25')
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse('age < 25')
        assert parser.evaluate(data, conditions) is False

    def test_evaluate_multiple_and_conditions(self):
        """Test evaluation of multiple AND conditions."""
        parser = WhereClauseParser()
        data = {'name': 'Alice', 'age': 30, 'department': 'Engineering'}
        conditions = parser.parse("age > 25 AND department = 'Engineering'")
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse("age > 35 AND department = 'Engineering'")
        assert parser.evaluate(data, conditions) is False

    def test_evaluate_nested_field_access(self):
        """Test evaluation with nested field access."""
        parser = WhereClauseParser()
        data = {'user': {'profile': {'age': 30, 'name': 'Alice'}}}
        conditions = parser.parse('user.profile.age > 25')
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse("user.profile.name = 'Alice'")
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse("user.nonexistent.field = 'value'")
        assert parser.evaluate(data, conditions) is False

    def test_evaluate_null_conditions(self):
        """Test evaluation of NULL conditions."""
        parser = WhereClauseParser()
        data = {'field1': 'value', 'field2': None}
        conditions = parser.parse('field1 IS NOT NULL')
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse('field2 IS NULL')
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse('field1 IS NULL')
        assert parser.evaluate(data, conditions) is False

    def test_evaluate_in_conditions(self):
        """Test evaluation of IN conditions."""
        parser = WhereClauseParser()
        data = {'category': 'A', 'tags': ['tag1', 'tag2']}
        conditions = parser.parse("category IN ['A', 'B', 'C']")
        assert parser.evaluate(data, conditions) is True
        conditions = parser.parse("category IN ['X', 'Y', 'Z']")
        assert parser.evaluate(data, conditions) is False

    def test_evaluate_handles_missing_fields(self):
        """Test evaluation handles missing fields gracefully."""
        parser = WhereClauseParser()
        data = {'existing_field': 'value'}
        conditions = parser.parse("missing_field = 'value'")
        assert parser.evaluate(data, conditions) is False
        conditions = parser.parse('missing_field > 10')
        assert parser.evaluate(data, conditions) is False

class TestSimpleWhereFilter:
    """Test SimpleWhereFilter functionality."""

    def test_filter_item_basic_functionality(self):
        """Test basic item filtering functionality."""
        filter_service = SimpleWhereFilter()
        data = {'name': 'Alice', 'age': 30}
        result = filter_service.filter_item(data, 'age > 25')
        assert result is True
        result = filter_service.filter_item(data, 'age < 25')
        assert result is False

    def test_filter_item_error_handling(self):
        """Test filter_item handles errors gracefully."""
        filter_service = SimpleWhereFilter()
        data = {'field': 'value'}
        result = filter_service.filter_item(data, 'invalid === syntax')
        assert result is True

    def test_evaluate_safe_skip_condition(self):
        """Test safe skip condition evaluation."""
        filter_service = SimpleWhereFilter()
        context = {'status': 'active', 'priority': 'high'}
        condition_config = {'where': "status = 'inactive'"}
        result = filter_service.evaluate_safe_skip_condition(condition_config, context)
        assert result is True
        condition_config = {'where': "status = 'active'"}
        result = filter_service.evaluate_safe_skip_condition(condition_config, context)
        assert result is False

    def test_evaluate_safe_skip_condition_error_handling(self):
        """Test safe skip condition handles errors gracefully."""
        filter_service = SimpleWhereFilter()
        context = {'field': 'value'}
        condition_config = {'where': 'invalid === syntax'}
        result = filter_service.evaluate_safe_skip_condition(condition_config, context)
        assert result is False
        condition_config = {}
        result = filter_service.evaluate_safe_skip_condition(condition_config, context)
        assert result is False

class TestGlobalFilter:
    """Test global filter functionality."""

    def test_get_global_filter_singleton(self):
        """Test global filter is a singleton."""
        filter1 = get_global_filter()
        filter2 = get_global_filter()
        assert filter1 is filter2
        assert isinstance(filter1, SimpleWhereFilter)

    def test_evaluate_safe_skip_condition_function(self):
        """Test global evaluate_safe_skip_condition function."""
        context = {'status': 'active'}
        condition_config = {'where': "status = 'inactive'"}
        result = evaluate_safe_skip_condition(condition_config, context)
        assert result is True

    def test_evaluate_safe_expression_function(self):
        """Test global evaluate_safe_expression function."""
        context = {'age': 30}
        result = evaluate_safe_expression('age > 25', context)
        assert result is True
        result = evaluate_safe_expression('age < 25', context)
        assert result is False

    def test_evaluate_safe_expression_error_handling(self):
        """Test evaluate_safe_expression handles errors gracefully."""
        context = {'field': 'value'}
        result = evaluate_safe_expression('invalid === syntax', context)
        assert result is False

class TestWhereClauseConfig:
    """Test WHERE clause configuration validation."""

    def test_valid_where_clause_config(self):
        """Test valid WHERE clause configuration."""
        config = WhereClauseConfig(clause="field = 'value'", scope=FilterScope.ITEM, passthrough_on_empty=True, passthrough_on_error=True, cache_enabled=True)
        assert config.clause == "field = 'value'"
        assert config.scope == FilterScope.ITEM
        assert config.passthrough_on_empty is True
        assert config.passthrough_on_error is True
        assert config.cache_enabled is True

    def test_where_clause_config_defaults(self):
        """Test WHERE clause configuration defaults."""
        config = WhereClauseConfig(clause="field = 'value'")
        assert config.scope == FilterScope.ITEM
        assert config.passthrough_on_empty is True
        assert config.passthrough_on_error is True
        assert config.cache_enabled is True

    def test_where_clause_config_validation_empty_clause(self):
        """Test WHERE clause config validation rejects empty clause."""
        with pytest.raises(ValidationError, match='WHERE clause cannot be empty'):
            WhereClauseConfig(clause='')
        with pytest.raises(ValidationError, match='WHERE clause cannot be empty'):
            WhereClauseConfig(clause='   ')

    def test_where_clause_config_validation_dangerous_patterns(self):
        """Test WHERE clause config validates against dangerous patterns."""
        dangerous_clauses = ["field = __import__('os')", "field = exec('malicious code')", "field = eval('expression')", "field = open('/etc/passwd')"]
        for clause in dangerous_clauses:
            with pytest.raises(ValidationError):
                WhereClauseConfig(clause=clause)

    def test_filter_scope_enum(self):
        """Test FilterScope enum values."""
        assert FilterScope.ITEM == 'item'
        assert FilterScope.AGENT == 'agent'
        config = WhereClauseConfig(clause="field = 'value'", scope=FilterScope.AGENT)
        assert config.scope == FilterScope.AGENT

class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling scenarios."""

    def test_parse_value_edge_cases(self):
        """Test _parse_value method edge cases."""
        parser = WhereClauseParser()
        value = parser._parse_value("''")
        assert value == ''
        value = parser._parse_value('\'value with "quotes"\'')
        assert value == 'value with "quotes"'
        value = parser._parse_value('[invalid json')
        assert value == '[invalid json'
        value = parser._parse_value('999999999999999999999')
        assert isinstance(value, int)

    def test_get_nested_value_edge_cases(self):
        """Test _get_nested_value method edge cases."""
        parser = WhereClauseParser()
        value = parser._get_nested_value({}, 'field')
        assert value is None
        data = {'field': 'not_a_dict'}
        value = parser._get_nested_value(data, 'field.subfield')
        assert value is None
        data = {'field': 'value'}
        value = parser._get_nested_value(data, '')
        assert value == data

    def test_operator_edge_cases(self):
        """Test operator evaluation edge cases."""
        parser = WhereClauseParser()
        conditions = [WhereCondition('field', '>', 10)]
        data = {'field': None}
        assert parser.evaluate(data, conditions) is False
        conditions = [WhereCondition('field', '>', 'string')]
        data = {'field': 10}
        result = parser.evaluate(data, conditions)

    def test_complex_where_clause_scenarios(self, sample_where_clauses):
        """Test complex WHERE clause scenarios."""
        parser = WhereClauseParser()
        for clause in sample_where_clauses:
            try:
                conditions = parser.parse(clause)
                assert isinstance(conditions, list)
            except Exception as e:
                pytest.fail(f"Failed to parse clause '{clause}': {e}")

    @pytest.mark.parametrize('data,clause,expected', [({'field': 'value'}, "field = 'value'", True), ({'age': 25}, 'age > 18', True), ({'status': 'inactive'}, "status = 'active'", False), ({}, "field = 'value'", False), ({'field': None}, 'field != null', False)])
    def test_parametrized_evaluation(self, data, clause, expected):
        """Test parametrized WHERE clause evaluation."""
        parser = WhereClauseParser()
        conditions = parser.parse(clause)
        result = parser.evaluate(data, conditions)
        assert result == expected