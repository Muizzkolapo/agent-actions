"""Tests for widened Any parameter guards in validation modules.

Verifies that isinstance guards return False/early for non-dict/non-str inputs,
covering the branches that motivated the type: ignore[unreachable] removal.
"""

from agent_actions.validation.config_validator import ConfigValidator
from agent_actions.validation.schema_validator import SchemaValidator


class TestIsValidJsonSchemaStructureNonDict:
    """_is_valid_json_schema_structure returns False for non-dict inputs."""

    def test_none_returns_false(self):
        assert SchemaValidator._is_valid_json_schema_structure(None) is False

    def test_list_returns_false(self):
        assert SchemaValidator._is_valid_json_schema_structure([1, 2]) is False

    def test_string_returns_false(self):
        assert SchemaValidator._is_valid_json_schema_structure("not a schema") is False

    def test_int_returns_false(self):
        assert SchemaValidator._is_valid_json_schema_structure(42) is False

    def test_valid_dict_returns_true(self):
        assert SchemaValidator._is_valid_json_schema_structure({"type": "object"}) is True


class TestValidatePropertyTypeNonStr:
    """_validate_property_type returns False for non-str inputs."""

    def test_none_returns_false(self):
        cv = ConfigValidator()
        assert cv._validate_property_type(None) is False

    def test_int_returns_false(self):
        cv = ConfigValidator()
        assert cv._validate_property_type(123) is False

    def test_list_returns_false(self):
        cv = ConfigValidator()
        assert cv._validate_property_type(["string"]) is False

    def test_valid_string_returns_true(self):
        cv = ConfigValidator()
        assert cv._validate_property_type("string") is True
