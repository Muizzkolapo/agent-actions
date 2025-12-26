"""Tests for built-in constraint validators."""

import pytest
from agent_actions.reprompting.constraints import (
    ConstraintValidator,
    ConstraintResult,
    BUILTIN_CONSTRAINTS,
    _check_not_contains,
    _check_contains,
    _check_max_length,
    _check_min_length,
    _check_required_fields,
    _check_non_empty,
    _check_field_types,
    _check_regex_match,
    _check_regex_not_match,
)


class TestNotContainsConstraint:
    """Tests for not_contains constraint."""

    def test_not_contains_string_passes(self):
        """Test not_contains passes when string is absent."""
        passed, error = _check_not_contains("hello world", "maze")
        assert passed is True
        assert error == ""

    def test_not_contains_string_fails(self):
        """Test not_contains fails when string is present."""
        passed, error = _check_not_contains("navigate the maze", "maze")
        assert passed is False
        assert "maze" in error

    def test_not_contains_case_insensitive(self):
        """Test not_contains is case-insensitive."""
        passed, error = _check_not_contains("MAZE", "maze")
        assert passed is False

    def test_not_contains_list_all_absent(self):
        """Test not_contains with list of values all absent."""
        passed, error = _check_not_contains("hello world", ["foo", "bar"])
        assert passed is True

    def test_not_contains_list_one_present(self):
        """Test not_contains with list fails if any value present."""
        passed, error = _check_not_contains("hello foo world", ["foo", "bar"])
        assert passed is False
        assert "foo" in error


class TestContainsConstraint:
    """Tests for contains constraint."""

    def test_contains_string_passes(self):
        """Test contains passes when string is present."""
        passed, error = _check_contains("hello world", "world")
        assert passed is True

    def test_contains_string_fails(self):
        """Test contains fails when string is absent."""
        passed, error = _check_contains("hello world", "foo")
        assert passed is False
        assert "foo" in error

    def test_contains_case_insensitive(self):
        """Test contains is case-insensitive."""
        passed, error = _check_contains("HELLO", "hello")
        assert passed is True

    def test_contains_list_all_present(self):
        """Test contains with list passes when all present."""
        passed, error = _check_contains("hello world foo bar", ["foo", "bar"])
        assert passed is True

    def test_contains_list_one_missing(self):
        """Test contains with list fails if any value missing."""
        passed, error = _check_contains("hello foo", ["foo", "bar"])
        assert passed is False
        assert "bar" in error


class TestLengthConstraints:
    """Tests for length constraints."""

    def test_max_length_passes(self):
        """Test max_length passes when under limit."""
        passed, error = _check_max_length("hello", 10)
        assert passed is True

    def test_max_length_fails(self):
        """Test max_length fails when over limit."""
        passed, error = _check_max_length("hello world", 5)
        assert passed is False
        assert "11" in error  # Actual length
        assert "5" in error  # Max length

    def test_max_length_exact(self):
        """Test max_length passes at exact limit."""
        passed, error = _check_max_length("hello", 5)
        assert passed is True

    def test_min_length_passes(self):
        """Test min_length passes when over limit."""
        passed, error = _check_min_length("hello world", 5)
        assert passed is True

    def test_min_length_fails(self):
        """Test min_length fails when under limit."""
        passed, error = _check_min_length("hi", 5)
        assert passed is False
        assert "2" in error  # Actual length
        assert "5" in error  # Min length


class TestRequiredFieldsConstraint:
    """Tests for required_fields constraint."""

    def test_required_fields_all_present(self):
        """Test passes when all required fields present."""
        response = {"name": "test", "description": "desc"}
        passed, error = _check_required_fields(response, ["name", "description"])
        assert passed is True

    def test_required_fields_missing_one(self):
        """Test fails when one required field missing."""
        response = {"name": "test"}
        passed, error = _check_required_fields(response, ["name", "description"])
        assert passed is False
        assert "description" in error

    def test_required_fields_missing_multiple(self):
        """Test fails when multiple required fields missing."""
        response = {"other": "value"}
        passed, error = _check_required_fields(response, ["name", "description"])
        assert passed is False
        assert "name" in error
        assert "description" in error

    def test_required_fields_single_string(self):
        """Test with single string field (not list)."""
        response = {"name": "test"}
        passed, error = _check_required_fields(response, "name")
        assert passed is True

    def test_required_fields_non_dict_fails(self):
        """Test fails when response is not a dict."""
        passed, error = _check_required_fields("not a dict", ["name"])
        assert passed is False
        assert "dictionary" in error


class TestNonEmptyConstraint:
    """Tests for non_empty constraint."""

    def test_non_empty_with_values_passes(self):
        """Test passes when fields have values."""
        response = {"name": "test", "items": [1, 2, 3]}
        passed, error = _check_non_empty(response, ["name", "items"])
        assert passed is True

    def test_non_empty_with_none_fails(self):
        """Test fails when field is None."""
        response = {"name": None}
        passed, error = _check_non_empty(response, ["name"])
        assert passed is False
        assert "name" in error

    def test_non_empty_with_empty_string_fails(self):
        """Test fails when field is empty string."""
        response = {"name": ""}
        passed, error = _check_non_empty(response, ["name"])
        assert passed is False

    def test_non_empty_with_empty_list_fails(self):
        """Test fails when field is empty list."""
        response = {"items": []}
        passed, error = _check_non_empty(response, ["items"])
        assert passed is False

    def test_non_empty_with_empty_dict_fails(self):
        """Test fails when field is empty dict."""
        response = {"config": {}}
        passed, error = _check_non_empty(response, ["config"])
        assert passed is False

    def test_non_empty_non_dict_fails(self):
        """Test fails when response is not a dict."""
        passed, error = _check_non_empty("not a dict", ["name"])
        assert passed is False


class TestFieldTypesConstraint:
    """Tests for field_types constraint."""

    def test_field_types_string_passes(self):
        """Test passes when string type matches."""
        response = {"name": "test"}
        passed, error = _check_field_types(response, {"name": "string"})
        assert passed is True

    def test_field_types_int_passes(self):
        """Test passes when int type matches."""
        response = {"count": 42}
        passed, error = _check_field_types(response, {"count": "int"})
        assert passed is True

    def test_field_types_array_passes(self):
        """Test passes when array type matches."""
        response = {"items": [1, 2, 3]}
        passed, error = _check_field_types(response, {"items": "array"})
        assert passed is True

    def test_field_types_object_passes(self):
        """Test passes when object type matches."""
        response = {"config": {"key": "value"}}
        passed, error = _check_field_types(response, {"config": "object"})
        assert passed is True

    def test_field_types_mismatch_fails(self):
        """Test fails when type doesn't match."""
        response = {"count": "not a number"}
        passed, error = _check_field_types(response, {"count": "int"})
        assert passed is False
        assert "count" in error
        assert "int" in error

    def test_field_types_missing_field_skipped(self):
        """Test skips missing fields (use required_fields for that)."""
        response = {"other": "value"}
        passed, error = _check_field_types(response, {"name": "string"})
        assert passed is True

    def test_field_types_non_dict_fails(self):
        """Test fails when response is not a dict."""
        passed, error = _check_field_types("not a dict", {"name": "string"})
        assert passed is False


class TestRegexConstraints:
    """Tests for regex constraints."""

    def test_regex_match_passes(self):
        """Test regex_match passes when pattern matches."""
        passed, error = _check_regex_match("test123", r"\d+")
        assert passed is True

    def test_regex_match_fails(self):
        """Test regex_match fails when pattern doesn't match."""
        passed, error = _check_regex_match("test", r"\d+")
        assert passed is False
        assert r"\d+" in error

    def test_regex_not_match_passes(self):
        """Test regex_not_match passes when pattern doesn't match."""
        passed, error = _check_regex_not_match("test", r"\d+")
        assert passed is True

    def test_regex_not_match_fails(self):
        """Test regex_not_match fails when pattern matches."""
        passed, error = _check_regex_not_match("test123", r"\d+")
        assert passed is False


class TestConstraintValidator:
    """Tests for ConstraintValidator class."""

    def test_validate_empty_constraints_passes(self):
        """Test validation with no constraints always passes."""
        validator = ConstraintValidator()
        result = validator.validate("any response", [])
        assert result.passed is True

    def test_validate_single_passing_constraint(self):
        """Test validation with single passing constraint."""
        validator = ConstraintValidator()
        result = validator.validate("hello world", [{"not_contains": "maze"}])
        assert result.passed is True

    def test_validate_single_failing_constraint(self):
        """Test validation with single failing constraint."""
        validator = ConstraintValidator()
        result = validator.validate("navigate the maze", [{"not_contains": "maze"}])
        assert result.passed is False
        assert result.constraint_name == "not_contains"
        assert "maze" in result.error

    def test_validate_multiple_constraints_all_pass(self):
        """Test validation with multiple passing constraints."""
        validator = ConstraintValidator()
        result = validator.validate(
            {"name": "test", "description": "desc"},
            [
                {"required_fields": ["name", "description"]},
                {"non_empty": ["name"]},
            ],
        )
        assert result.passed is True

    def test_validate_multiple_constraints_first_fails(self):
        """Test validation stops at first failing constraint."""
        validator = ConstraintValidator()
        result = validator.validate(
            {"name": "test"},
            [
                {"required_fields": ["name", "description"]},
                {"non_empty": ["name"]},
            ],
        )
        assert result.passed is False
        assert result.constraint_name == "required_fields"

    def test_validate_unknown_constraint_skipped(self):
        """Test unknown constraints are skipped."""
        validator = ConstraintValidator()
        result = validator.validate("test", [{"unknown_constraint": "value"}])
        assert result.passed is True

    def test_register_custom_constraint(self):
        """Test registering and using custom constraint."""
        validator = ConstraintValidator()

        def custom_check(response, value):
            return response == value, f"Expected {value}"

        validator.register("equals", custom_check)
        result = validator.validate("test", [{"equals": "test"}])
        assert result.passed is True

        result = validator.validate("test", [{"equals": "other"}])
        assert result.passed is False

    def test_get_constraint_names(self):
        """Test getting list of registered constraint names."""
        validator = ConstraintValidator()
        names = validator.get_constraint_names()
        assert "not_contains" in names
        assert "required_fields" in names
        assert "non_empty" in names


class TestBuiltinConstraintsRegistry:
    """Tests for BUILTIN_CONSTRAINTS registry."""

    def test_all_expected_constraints_registered(self):
        """Test all expected constraints are in registry."""
        expected = [
            "not_contains",
            "contains",
            "max_length",
            "min_length",
            "required_fields",
            "non_empty",
            "field_types",
            "regex_match",
            "regex_not_match",
        ]
        for constraint in expected:
            assert constraint in BUILTIN_CONSTRAINTS, f"Missing constraint: {constraint}"
