import pytest
from agent_actions.core.parser.where_parser import WhereClauseParser, WhereCondition


class TestWhereClauseParser:
    """Test suite for WHERE clause parsing functionality"""

    # Basic Parsing Tests
    def test_simple_equality_parsing(self):
        """Test parsing simple equality conditions"""
        conditions = WhereClauseParser.parse('questionable == "Low Value"')
        assert len(conditions) == 1
        assert conditions[0].field == 'questionable'
        assert conditions[0].operator == '=='
        assert conditions[0].value == "Low Value"

    def test_not_equals_parsing(self):
        """Test parsing not equals conditions"""
        conditions = WhereClauseParser.parse('status != "active"')
        assert len(conditions) == 1
        assert conditions[0].field == 'status'
        assert conditions[0].operator == '!='
        assert conditions[0].value == "active"

    def test_numeric_comparison_parsing(self):
        """Test parsing numeric comparison operators"""
        test_cases = [
            ('score > 50', '>', 50),
            ('age < 30', '<', 30),
            ('rating >= 4.5', '>=', 4.5),
            ('count <= 100', '<=', 100)
        ]

        for clause, expected_op, expected_val in test_cases:
            conditions = WhereClauseParser.parse(clause)
            assert len(conditions) == 1
            assert conditions[0].operator == expected_op
            assert conditions[0].value == expected_val

    def test_array_operations_parsing(self):
        """Test parsing IN and NOT IN operations"""
        conditions = WhereClauseParser.parse('category IN ["tech", "science"]')
        assert conditions[0].operator == 'IN'
        assert conditions[0].value == ["tech", "science"]

        conditions = WhereClauseParser.parse('status NOT IN ["deleted", "archived"]')
        assert conditions[0].operator == 'NOT IN'
        assert conditions[0].value == ["deleted", "archived"]

    def test_string_operations_parsing(self):
        """Test parsing string CONTAINS operations"""
        conditions = WhereClauseParser.parse('description CONTAINS "important"')
        assert conditions[0].operator == 'CONTAINS'
        assert conditions[0].value == "important"

        conditions = WhereClauseParser.parse('title NOT CONTAINS "spam"')
        assert conditions[0].operator == 'NOT CONTAINS'
        assert conditions[0].value == "spam"

    def test_null_operations_parsing(self):
        """Test parsing NULL check operations"""
        conditions = WhereClauseParser.parse('optional_field IS NULL')
        assert conditions[0].operator == 'IS NULL'
        assert conditions[0].value is None

        conditions = WhereClauseParser.parse('required_field IS NOT NULL')
        assert conditions[0].operator == 'IS NOT NULL'
        assert conditions[0].value is None

    def test_complex_and_parsing(self):
        """Test parsing multiple conditions with AND"""
        conditions = WhereClauseParser.parse('status == "active" AND score > 80')
        assert len(conditions) == 2
        assert conditions[0].field == 'status'
        assert conditions[1].field == 'score'

    def test_nested_field_parsing(self):
        """Test parsing nested field access with dot notation"""
        conditions = WhereClauseParser.parse('metadata.user.age >= 21')
        assert conditions[0].field == 'metadata.user.age'
        assert conditions[0].operator == '>='
        assert conditions[0].value == 21

    # Value Type Parsing Tests
    def test_string_value_parsing(self):
        """Test parsing different string value formats"""
        test_cases = [
            ('"quoted string"', "quoted string"),
            ("'single quoted'", "single quoted"),
            ('unquoted', "unquoted")
        ]

        for input_val, expected in test_cases:
            parsed = WhereClauseParser._parse_value(input_val)
            assert parsed == expected

    def test_numeric_value_parsing(self):
        """Test parsing numeric values"""
        test_cases = [
            ('42', 42),
            ('3.14', 3.14),
            ('-10', -10),
            ('0', 0)
        ]

        for input_val, expected in test_cases:
            parsed = WhereClauseParser._parse_value(input_val)
            assert parsed == expected

    def test_boolean_value_parsing(self):
        """Test parsing boolean values"""
        assert WhereClauseParser._parse_value('true') is True
        assert WhereClauseParser._parse_value('TRUE') is True
        assert WhereClauseParser._parse_value('false') is False
        assert WhereClauseParser._parse_value('FALSE') is False

    def test_null_value_parsing(self):
        """Test parsing null values"""
        assert WhereClauseParser._parse_value('null') is None
        assert WhereClauseParser._parse_value('NULL') is None

    def test_array_value_parsing(self):
        """Test parsing array values"""
        parsed = WhereClauseParser._parse_value('["a", "b", "c"]')
        assert parsed == ["a", "b", "c"]

        parsed = WhereClauseParser._parse_value('[1, 2, 3]')
        assert parsed == [1, 2, 3]

    # Evaluation Tests
    def test_equality_evaluation(self):
        """Test evaluation of equality conditions"""
        conditions = WhereClauseParser.parse('status == "active"')
        assert WhereClauseParser.evaluate({"status": "active"}, conditions) is True
        assert WhereClauseParser.evaluate({"status": "inactive"}, conditions) is False

    def test_inequality_evaluation(self):
        """Test evaluation of inequality conditions"""
        conditions = WhereClauseParser.parse('questionable != "Low Value"')
        assert WhereClauseParser.evaluate({"questionable": "High Value"}, conditions) is True
        assert WhereClauseParser.evaluate({"questionable": "Low Value"}, conditions) is False

    def test_numeric_comparison_evaluation(self):
        """Test evaluation of numeric comparisons"""
        test_cases = [
            ('score > 50', {"score": 75}, True),
            ('score > 50', {"score": 25}, False),
            ('age <= 30', {"age": 25}, True),
            ('age <= 30', {"age": 35}, False),
            ('rating >= 4.0', {"rating": 4.5}, True),
            ('rating >= 4.0', {"rating": 3.5}, False)
        ]

        for clause, data, expected in test_cases:
            conditions = WhereClauseParser.parse(clause)
            result = WhereClauseParser.evaluate(data, conditions)
            assert result == expected, f"Failed for {clause} with {data}"

    def test_array_operations_evaluation(self):
        """Test evaluation of IN and NOT IN operations"""
        conditions = WhereClauseParser.parse('category IN ["tech", "science"]')
        assert WhereClauseParser.evaluate({"category": "tech"}, conditions) is True
        assert WhereClauseParser.evaluate({"category": "art"}, conditions) is False

        conditions = WhereClauseParser.parse('status NOT IN ["deleted", "archived"]')
        assert WhereClauseParser.evaluate({"status": "active"}, conditions) is True
        assert WhereClauseParser.evaluate({"status": "deleted"}, conditions) is False

    def test_string_operations_evaluation(self):
        """Test evaluation of string CONTAINS operations"""
        conditions = WhereClauseParser.parse('title CONTAINS "Python"')
        assert WhereClauseParser.evaluate({"title": "Learning Python Programming"}, conditions) is True
        assert WhereClauseParser.evaluate({"title": "JavaScript Guide"}, conditions) is False

        conditions = WhereClauseParser.parse('content NOT CONTAINS "spam"')
        assert WhereClauseParser.evaluate({"content": "Good content here"}, conditions) is True
        assert WhereClauseParser.evaluate({"content": "This is spam content"}, conditions) is False

    def test_null_operations_evaluation(self):
        """Test evaluation of NULL operations"""
        conditions = WhereClauseParser.parse('optional_field IS NULL')
        assert WhereClauseParser.evaluate({"other_field": "value"}, conditions) is True
        assert WhereClauseParser.evaluate({"optional_field": None}, conditions) is True
        assert WhereClauseParser.evaluate({"optional_field": "value"}, conditions) is False

        conditions = WhereClauseParser.parse('required_field IS NOT NULL')
        assert WhereClauseParser.evaluate({"required_field": "value"}, conditions) is True
        assert WhereClauseParser.evaluate({"required_field": None}, conditions) is False
        assert WhereClauseParser.evaluate({"other_field": "value"}, conditions) is False

    def test_nested_field_evaluation(self):
        """Test evaluation with nested field access"""
        conditions = WhereClauseParser.parse('metadata.score >= 80')
        data = {"metadata": {"score": 85, "category": "tech"}}
        assert WhereClauseParser.evaluate(data, conditions) is True
        data["metadata"]["score"] = 75
        assert WhereClauseParser.evaluate(data, conditions) is False

    def test_multiple_conditions_evaluation(self):
        """Test evaluation of multiple AND conditions"""
        conditions = WhereClauseParser.parse('status == "active" AND score > 70')
        data = {"status": "active", "score": 80}
        assert WhereClauseParser.evaluate(data, conditions) is True
        data = {"status": "inactive", "score": 80}
        assert WhereClauseParser.evaluate(data, conditions) is False
        data = {"status": "active", "score": 60}
        assert WhereClauseParser.evaluate(data, conditions) is False

    def test_missing_field_evaluation(self):
        """Test evaluation when fields are missing"""
        conditions = WhereClauseParser.parse('nonexistent_field == "value"')
        result = WhereClauseParser.evaluate({"other_field": "data"}, conditions)
        assert result is False

    # Edge Cases and Error Handling
    def test_empty_clause_parsing(self):
        """Test parsing empty or invalid clauses"""
        assert WhereClauseParser.parse('') == []
        assert WhereClauseParser.parse('   ') == []

    def test_invalid_operator_parsing(self):
        """Test parsing with invalid operators"""
        conditions = WhereClauseParser.parse('field ~= "value"')
        assert len(conditions) == 0

    def test_malformed_clause_parsing(self):
        """Test parsing malformed clauses"""
        conditions = WhereClauseParser.parse('field ==')
        assert len(conditions) == 0
        conditions = WhereClauseParser.parse('== "value"')
        assert len(conditions) == 0

    def test_case_insensitive_operators(self):
        """Test that operators work case-insensitively"""
        conditions = WhereClauseParser.parse('field in ["a", "b"]')
        assert conditions[0].operator == 'IN'
        conditions = WhereClauseParser.parse('field Is Null')
        assert conditions[0].operator == 'IS NULL'

    def test_whitespace_handling(self):
        """Test proper handling of whitespace"""
        conditions = WhereClauseParser.parse('  field   ==   "value"  ')
        assert conditions[0].field == 'field'
        assert conditions[0].value == 'value'


class TestWhereCondition:
    """Test the WhereCondition dataclass"""

    def test_condition_creation(self):
        """Test creating WhereCondition objects"""
        condition = WhereCondition(field="test_field", operator="==", value="test_value")
        assert condition.field == "test_field"
        assert condition.operator == "=="
        assert condition.value == "test_value"

    def test_condition_equality(self):
        """Test WhereCondition equality comparison"""
        condition1 = WhereCondition("field", "==", "value")
        condition2 = WhereCondition("field", "==", "value")
        condition3 = WhereCondition("field", "!=", "value")
        assert condition1 == condition2
        assert condition1 != condition3
