import pytest
from agent_actions.core.parser.where_parser import WhereClauseParser


class TestWhereClauseEdgeCases:
    """Test edge cases and error scenarios for WHERE clause parsing"""

    def test_empty_and_whitespace_clauses(self):
        test_cases = ['', '   ', '\t\n', None]
        for clause in test_cases:
            if clause is None:
                with pytest.raises((TypeError, AttributeError)):
                    WhereClauseParser.parse(clause)
            else:
                conditions = WhereClauseParser.parse(clause)
                assert conditions == []

    def test_malformed_clauses(self):
        malformed_clauses = [
            'field ==',
            '== "value"',
            'field "value"',
            'field == == "value"',
            'field == "unclosed string',
            'field IN [unclosed array',
            'field > '
        ]
        for clause in malformed_clauses:
            conditions = WhereClauseParser.parse(clause)
            assert isinstance(conditions, list)

    def test_special_characters_in_values(self):
        special_cases = [
            ('field == "value with spaces"', "value with spaces"),
            ('field == "value\nwith\nnewlines"', "value\nwith\nnewlines"),
            ('field == "value\twith\ttabs"', "value\twith\ttabs"),
            ('field == "value with \"quotes\""', 'value with "quotes"'),
            ('field == "value with \'apostrophes\'"', "value with 'apostrophes'"),
            ('field == "unicode: 中文 🚀 émojis"', "unicode: 中文 🚀 émojis"),
        ]
        for clause, expected_value in special_cases:
            conditions = WhereClauseParser.parse(clause)
            if conditions:
                assert conditions[0].value == expected_value

    def test_extremely_nested_field_access(self):
        deep_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "value": "deep_value"
                            }
                        }
                    }
                }
            }
        }
        conditions = WhereClauseParser.parse('level1.level2.level3.level4.level5.value == "deep_value"')
        result = WhereClauseParser.evaluate(deep_data, conditions)
        assert result is True

    def test_field_names_with_special_characters(self):
        special_field_data = {
            "field-with-hyphens": "value1",
            "field_with_underscores": "value2",
            "field.with.dots": "value3",
            "field with spaces": "value4",
            "123numeric_start": "value5",
        }
        conditions = WhereClauseParser.parse('field_with_underscores == "value2"')
        result = WhereClauseParser.evaluate(special_field_data, conditions)
        assert result is True

    def test_case_sensitivity(self):
        data = {
            "Field": "Value",
            "field": "value",
            "FIELD": "VALUE"
        }
        conditions = WhereClauseParser.parse('field == "value"')
        assert WhereClauseParser.evaluate(data, conditions) is True
        conditions = WhereClauseParser.parse('Field == "value"')
        assert WhereClauseParser.evaluate(data, conditions) is False
        conditions = WhereClauseParser.parse('field == "VALUE"')
        assert WhereClauseParser.evaluate(data, conditions) is False

    def test_numeric_edge_cases(self):
        edge_data = {
            "zero": 0,
            "negative": -42,
            "float": 3.14159,
            "scientific": 1e10,
            "infinity": float('inf'),
            "negative_infinity": float('-inf'),
        }
        test_cases = [
            ('zero == 0', True),
            ('zero > -1', True),
            ('negative < 0', True),
            ('float >= 3.14', True),
            ('scientific > 1000000000', True),
        ]
        for clause, expected in test_cases:
            conditions = WhereClauseParser.parse(clause)
            result = WhereClauseParser.evaluate(edge_data, conditions)
            assert result == expected

    def test_boolean_edge_cases(self):
        boolean_data = {
            "true_bool": True,
            "false_bool": False,
            "true_string": "true",
            "false_string": "false",
            "zero": 0,
            "one": 1,
            "empty_string": "",
            "none_value": None
        }
        conditions = WhereClauseParser.parse('true_bool == true')
        assert WhereClauseParser.evaluate(boolean_data, conditions) is True
        conditions = WhereClauseParser.parse('false_bool == false')
        assert WhereClauseParser.evaluate(boolean_data, conditions) is True
        conditions = WhereClauseParser.parse('true_string == true')
        assert WhereClauseParser.evaluate(boolean_data, conditions) is False

    def test_array_edge_cases(self):
        array_data = {
            "empty_array": [],
            "mixed_array": [1, "two", 3.0, True, None],
            "nested_array": [[1, 2], [3, 4]],
            "string_value": "not_an_array"
        }
        conditions = WhereClauseParser.parse('value IN []')
        result = WhereClauseParser.evaluate({"value": "anything"}, conditions)
        assert result is False
        conditions = WhereClauseParser.parse('mixed_item IN [1, "two", true]')
        test_cases = [
            ({"mixed_item": 1}, True),
            ({"mixed_item": "two"}, True),
            ({"mixed_item": True}, True),
            ({"mixed_item": "one"}, False),
        ]
        for data, expected in test_cases:
            result = WhereClauseParser.evaluate(data, conditions)
            assert result == expected

    def test_null_and_none_handling(self):
        null_data = {
            "null_field": None,
            "zero_field": 0,
            "empty_string": "",
            "false_field": False,
            "existing_field": "value"
        }
        test_cases = [
            ('null_field IS NULL', True),
            ('null_field IS NOT NULL', False),
            ('zero_field IS NULL', False),
            ('empty_string IS NULL', False),
            ('false_field IS NULL', False),
            ('nonexistent_field IS NULL', True),
            ('existing_field IS NOT NULL', True),
        ]
        for clause, expected in test_cases:
            conditions = WhereClauseParser.parse(clause)
            result = WhereClauseParser.evaluate(null_data, conditions)
            assert result == expected

    def test_string_operation_edge_cases(self):
        string_data = {
            "empty_string": "",
            "whitespace": "   ",
            "multiline": "line1\nline2\nline3",
            "unicode": "Hello 世界 🌍",
            "numeric_string": "12345",
            "none_value": None,
            "number": 42
        }
        test_cases = [
            ('empty_string CONTAINS ""', True),
            ('whitespace CONTAINS " "', True),
            ('multiline CONTAINS "line2"', True),
            ('unicode CONTAINS "世界"', True),
            ('numeric_string CONTAINS "234"', True),
            ('none_value CONTAINS "test"', False),
            ('number CONTAINS "4"', True),
        ]
        for clause, expected in test_cases:
            conditions = WhereClauseParser.parse(clause)
            result = WhereClauseParser.evaluate(string_data, conditions)
            assert result == expected

    def test_operator_precedence_and_parsing(self):
        test_cases = [
            ('field != "value"', '!='),
            ('field >= 50', '>='),
            ('field <= 50', '<='),
            ('field NOT IN ["a"]', 'NOT IN'),
            ('field NOT CONTAINS "test"', 'NOT CONTAINS'),
        ]
        for clause, expected_operator in test_cases:
            conditions = WhereClauseParser.parse(clause)
            assert len(conditions) == 1
            assert conditions[0].operator == expected_operator

    def test_memory_with_large_strings(self):
        large_string = "x" * 10000
        huge_string = "y" * 100000
        large_data = {
            "large_field": large_string,
            "huge_field": huge_string
        }
        conditions = WhereClauseParser.parse(f'large_field == "{large_string[:100]}..."')
        result = WhereClauseParser.evaluate(large_data, conditions)
        assert isinstance(result, bool)
        conditions = WhereClauseParser.parse('huge_field CONTAINS "yyy"')
        result = WhereClauseParser.evaluate(large_data, conditions)
        assert result is True

    def test_circular_reference_protection(self):
        circular_data = {"level1": {}}
        circular_data["level1"]["back_ref"] = circular_data
        conditions = WhereClauseParser.parse('level1.back_ref.level1.value == "test"')
        try:
            result = WhereClauseParser.evaluate(circular_data, conditions)
            assert isinstance(result, bool)
        except RecursionError:
            pytest.fail("Should handle circular references without recursion error")
