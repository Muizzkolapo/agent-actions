"""Tests for SchemaValidator to improve coverage."""

import json
from pathlib import Path

import pytest
import yaml

from agent_actions.validation.schema_validator import (
    SchemaValidator,
    _collect_all_keys,
    _find_refs,
)


@pytest.fixture
def validator():
    """Create a SchemaValidator with events disabled."""
    return SchemaValidator(fire_events=False)


# ---------------------------------------------------------------------------
# Module-level helpers: _find_refs, _collect_all_keys
# ---------------------------------------------------------------------------


class TestFindRefs:
    """Test recursive $ref extraction."""

    def test_no_refs(self):
        assert _find_refs({"type": "string"}) == set()

    def test_single_ref(self):
        assert _find_refs({"$ref": "#/definitions/Foo"}) == {"#/definitions/Foo"}

    def test_nested_refs(self):
        schema = {
            "properties": {
                "a": {"$ref": "#/definitions/A"},
                "b": {"$ref": "#/definitions/B"},
            }
        }
        assert _find_refs(schema) == {"#/definitions/A", "#/definitions/B"}

    def test_refs_in_list(self):
        schema = [{"$ref": "#/definitions/X"}, {"type": "string"}]
        assert _find_refs(schema) == {"#/definitions/X"}

    def test_non_string_ref_ignored(self):
        assert _find_refs({"$ref": 42}) == set()


class TestCollectAllKeys:
    """Test recursive key collection."""

    def test_flat_dict(self):
        keys = _collect_all_keys({"type": "object", "required": []})
        assert keys == {"type", "required"}

    def test_nested_dict(self):
        # Child names of "properties" are skipped (user field names, not schema
        # keywords) but sub-schema values ARE recursed so typos are detectable.
        keys = _collect_all_keys({"properties": {"name": {"type": "string"}}})
        assert "properties" in keys
        assert "name" not in keys
        assert "type" in keys  # sub-schema {"type": "string"} is still visited

    def test_list_of_dicts(self):
        keys = _collect_all_keys([{"a": 1}, {"b": 2}])
        assert keys == {"a", "b"}

    def test_empty(self):
        assert _collect_all_keys({}) == set()
        assert _collect_all_keys([]) == set()


# ---------------------------------------------------------------------------
# _is_valid_json_schema_structure
# ---------------------------------------------------------------------------


class TestIsValidJsonSchemaStructure:
    """Test schema structure detection."""

    def test_has_type(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({"type": "object"}) is True

    def test_has_properties(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({"properties": {}}) is True

    def test_has_items(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({"items": {}}) is True

    def test_has_schema_keyword(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({"$schema": "..."}) is True

    def test_no_schema_keywords(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({"foo": "bar"}) is False

    def test_empty_dict(self, validator):
        assert SchemaValidator._is_valid_json_schema_structure({}) is False


# ---------------------------------------------------------------------------
# _check_common_schema_issues_static
# ---------------------------------------------------------------------------


class TestCheckCommonSchemaIssuesStatic:
    """Test common schema issue detection."""

    def test_missing_root_type(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"properties": {"a": {"type": "string"}}}, "test_schema"
        )
        assert any("Missing 'type'" in i for i in issues)

    def test_object_without_properties(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"type": "object"}, "test_schema"
        )
        assert any("no defined 'properties'" in i for i in issues)

    def test_object_with_valid_properties(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"type": "object", "properties": {"name": {"type": "string"}}},
            "test_schema",
        )
        type_issues = [i for i in issues if "no defined 'properties'" in i]
        assert type_issues == []

    def test_required_not_in_properties(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a", "b"],
            },
            "test_schema",
        )
        assert any("required properties not defined" in i for i in issues)

    def test_array_without_items(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"type": "array"}, "test_schema"
        )
        assert any("'items' is not defined" in i for i in issues)

    def test_unused_definitions(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {
                "type": "object",
                "properties": {},
                "definitions": {"Unused": {"type": "string"}},
            },
            "test_schema",
        )
        assert any("unused definitions" in i.lower() for i in issues)

    def test_used_definitions_no_warning(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {
                "type": "object",
                "properties": {"a": {"$ref": "#/definitions/Used"}},
                "definitions": {"Used": {"type": "string"}},
            },
            "test_schema",
        )
        unused_issues = [i for i in issues if "unused definitions" in i.lower()]
        assert unused_issues == []

    def test_suspicious_keys(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"type": "object", "properties": {}, "typo_key": "value"},
            "test_schema",
        )
        assert any("unknown/typo" in i.lower() for i in issues)

    def test_acceptable_custom_keys_no_warning(self, validator):
        issues = SchemaValidator._check_common_schema_issues_static(
            {"type": "object", "properties": {}, "deprecated": True},
            "test_schema",
        )
        suspicious_issues = [i for i in issues if "unknown/typo" in i.lower()]
        assert suspicious_issues == []

    def test_clean_schema_no_issues(self, validator):
        # Use reserved keywords as property names to avoid suspicious-key issues
        issues = SchemaValidator._check_common_schema_issues_static(
            {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
            "test_schema",
        )
        assert issues == []


# ---------------------------------------------------------------------------
# _process_schema_file
# ---------------------------------------------------------------------------


class TestProcessSchemaFile:
    """Test individual schema file processing."""

    def test_file_not_found(self, validator, tmp_path):
        validator._process_schema_file(
            tmp_path / "missing.json", "missing.json", "agent1"
        )
        assert validator.has_errors()
        assert any("not found" in e for e in validator.get_errors())

    def test_path_is_directory(self, validator, tmp_path):
        validator._process_schema_file(tmp_path, "dir_schema", "agent1")
        assert validator.has_errors()
        assert any("not a file" in e for e in validator.get_errors())

    def test_invalid_json(self, validator, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json!!}")
        validator._process_schema_file(f, "bad.json", "agent1")
        assert validator.has_errors()
        assert any("invalid schema" in e.lower() for e in validator.get_errors())

    def test_valid_schema_file_no_structural_errors(self, validator, tmp_path):
        """Verify a well-formed schema produces no JSON-parse or meta-schema errors."""
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
        f = tmp_path / "good.json"
        f.write_text(json.dumps(schema))
        validator._process_schema_file(f, "good.json", "agent1")
        # "title" is a reserved JSON Schema keyword, so no suspicious-key error
        assert not validator.has_errors()

    def test_schema_without_type(self, validator, tmp_path):
        """Schema missing root type should produce an issue."""
        schema = {"properties": {"a": {"type": "string"}}}
        f = tmp_path / "notype.json"
        f.write_text(json.dumps(schema))
        validator._process_schema_file(f, "notype.json", "agent1")
        assert validator.has_errors()

    def test_agent_name_none(self, validator, tmp_path):
        """Passing agent_name=None should still work (no crash)."""
        schema = {
            "type": "object",
            "properties": {"description": {"type": "string"}},
        }
        f = tmp_path / "schema.json"
        f.write_text(json.dumps(schema))
        validator._process_schema_file(f, "schema.json", None)
        # "description" is a reserved keyword, so no suspicious-key error
        assert not validator.has_errors()


# ---------------------------------------------------------------------------
# _check_type_compatibility
# ---------------------------------------------------------------------------


class TestCheckTypeCompatibility:
    """Test type compatibility checking between schemas."""

    def test_same_types(self, validator):
        issues = validator._check_type_compatibility(
            {"type": "object"}, {"type": "object"}, "s1", "s2"
        )
        assert issues == []

    def test_different_types(self, validator):
        issues = validator._check_type_compatibility(
            {"type": "object"}, {"type": "array"}, "s1", "s2"
        )
        assert len(issues) == 1
        assert "mismatch" in issues[0].lower()


# ---------------------------------------------------------------------------
# _check_object_compatibility
# ---------------------------------------------------------------------------


class TestCheckObjectCompatibility:
    """Test object schema compatibility checking."""

    def test_compatible_objects(self, validator):
        s1 = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
        }
        s2 = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        }
        issues = validator._check_object_compatibility(s1, s2, "s1", "s2")
        assert issues == []

    def test_missing_required_property(self, validator):
        s1 = {"type": "object", "properties": {"a": {"type": "string"}}}
        s2 = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
            "required": ["b"],
        }
        issues = validator._check_object_compatibility(s1, s2, "s1", "s2")
        assert any("requires properties" in i.lower() for i in issues)

    def test_type_mismatch_on_property(self, validator):
        s1 = {"type": "object", "properties": {"a": {"type": "string"}}}
        s2 = {"type": "object", "properties": {"a": {"type": "number"}}}
        issues = validator._check_object_compatibility(s1, s2, "s1", "s2")
        assert any("type mismatch" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# check_schema_compatibility
# ---------------------------------------------------------------------------


class TestCheckSchemaCompatibility:
    """Test the public compatibility-check method."""

    def test_compatible_schemas(self, validator):
        s1 = {"type": "object", "properties": {"a": {"type": "string"}}}
        s2 = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = validator.check_schema_compatibility(s1, s2)
        assert result is True
        assert not validator.has_errors()

    def test_incompatible_types(self, validator):
        s1 = {"type": "object", "properties": {}}
        s2 = {"type": "array", "items": {"type": "string"}}
        result = validator.check_schema_compatibility(s1, s2, "output", "input")
        assert result is False
        assert validator.has_errors()

    def test_non_object_types_skip_property_check(self, validator):
        s1 = {"type": "string"}
        s2 = {"type": "string"}
        result = validator.check_schema_compatibility(s1, s2)
        assert result is True


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


class TestValidateMethod:
    """Test the public validate() entry point."""

    def test_non_dict_data(self, validator):
        result = validator.validate("not a dict")
        assert result is False

    def test_missing_agent_name(self, validator):
        result = validator.validate({"schema_dir": Path("/tmp"), "schema_files": []})
        assert result is False
        assert any("agent_name" in e for e in validator.get_errors())

    def test_missing_schema_dir(self, validator):
        result = validator.validate({"agent_name": "test"})
        assert result is False
        assert any("schema_dir" in e for e in validator.get_errors())

    def test_schema_dir_not_a_path(self, validator):
        result = validator.validate(
            {"agent_name": "test", "schema_dir": "/some/string/path"}
        )
        assert result is False

    def test_schema_files_invalid_type(self, validator):
        result = validator.validate(
            {
                "agent_name": "test",
                "schema_dir": Path("/tmp"),
                "schema_files": "not_a_list",
            }
        )
        assert result is False

    def test_schema_dir_does_not_exist(self, validator, tmp_path):
        result = validator.validate(
            {
                "agent_name": "test",
                "schema_dir": tmp_path / "nonexistent",
            }
        )
        assert result is False

    def test_schema_dir_is_file(self, validator, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = validator.validate(
            {"agent_name": "test", "schema_dir": f}
        )
        assert result is False

    def test_no_json_files_in_dir(self, validator, tmp_path):
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True  # passes with warning
        assert len(validator.get_warnings()) > 0

    def test_validates_json_files_in_dir(self, validator, tmp_path):
        # Use reserved JSON Schema keywords as property names to avoid
        # false "suspicious key" errors from recursive key collection.
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
        (tmp_path / "out.json").write_text(json.dumps(schema))
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True

    def test_validates_specific_schema_files(self, validator, tmp_path):
        schema = {
            "type": "object",
            "properties": {"description": {"type": "string"}},
        }
        (tmp_path / "output.json").write_text(json.dumps(schema))
        result = validator.validate(
            {
                "agent_name": "test",
                "schema_dir": tmp_path,
                "schema_files": ["output.json"],
            }
        )
        assert result is True

    @pytest.mark.parametrize("ext", [".yml", ".yaml"])
    def test_validates_yaml_files_in_dir(self, validator, tmp_path, ext):
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
        (tmp_path / f"out{ext}").write_text(yaml.dump(schema))
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True

    def test_validates_schemas_in_subdirectory(self, validator, tmp_path):
        """Schemas in a nested subdirectory are discovered via rglob."""
        sub = tmp_path / "agent_name"
        sub.mkdir()
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
        (sub / "out.yml").write_text(yaml.dump(schema))
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True
        assert len(validator.get_warnings()) == 0

    def test_fields_format_schema_skips_json_schema_checks(self, validator, tmp_path):
        """Fields-format schemas are valid and skip JSON Schema meta-validation."""
        schema_content = (
            "name: score_quality\n"
            "fields:\n"
            "  - id: score\n"
            "    type: number\n"
            "    description: Quality score\n"
        )
        (tmp_path / "score.yml").write_text(schema_content)
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True
        assert not validator.has_errors()

    def test_json_schema_format_still_validated(self, validator, tmp_path):
        """JSON Schema format schemas still go through meta-validation."""
        bad_schema = {"type": "object", "properties": "not_a_dict"}
        (tmp_path / "bad.json").write_text(json.dumps(bad_schema))
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is False

    def test_invalid_yaml_schema_reports_error(self, validator, tmp_path):
        (tmp_path / "bad.yml").write_text(":\n  :\n    - ][")
        result = validator.validate(
            {
                "agent_name": "test",
                "schema_dir": tmp_path,
                "schema_files": ["bad.yml"],
            }
        )
        assert result is False

    def test_no_schema_files_warns(self, validator, tmp_path):
        """Empty dir with no .json, .yml, or .yaml files emits warning."""
        result = validator.validate(
            {"agent_name": "test", "schema_dir": tmp_path}
        )
        assert result is True
        warnings = validator.get_warnings()
        assert len(warnings) > 0
        assert "No schema files" in str(warnings[0])


# ---------------------------------------------------------------------------
# Regression B-4/D-1: user field names not treated as schema keywords
# ---------------------------------------------------------------------------


class TestCollectAllKeysPropertySkipping:
    """User-defined field names inside 'properties' must not be flagged as unknown keys."""

    def test_user_field_names_not_collected(self):
        schema = {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        keys = _collect_all_keys(schema)
        assert "customer_id" not in keys
        assert "email" not in keys
        assert "properties" in keys
        assert "type" in keys

    def test_defs_field_names_not_collected(self):
        schema = {
            "$defs": {
                "Address": {"type": "object", "properties": {"street": {"type": "string"}}}
            }
        }
        keys = _collect_all_keys(schema)
        assert "Address" not in keys
        assert "street" not in keys
        assert "$defs" in keys

    def test_definitions_field_names_not_collected(self):
        schema = {
            "definitions": {
                "MyType": {"type": "string", "description": "a custom type"}
            }
        }
        keys = _collect_all_keys(schema)
        assert "MyType" not in keys
        assert "definitions" in keys

    def test_pattern_properties_field_names_not_collected(self):
        schema = {
            "patternProperties": {
                "^S_": {"type": "string"},
                "^I_": {"type": "integer"},
            }
        }
        keys = _collect_all_keys(schema)
        assert "^S_" not in keys
        assert "^I_" not in keys
        assert "patternProperties" in keys

    def test_items_keywords_are_descended(self):
        # items is NOT in _SCHEMA_CONTENT_KEYS — schema keywords inside it are visible
        # so typos like {"tpye": "string"} inside items will still be flagged.
        schema = {"type": "array", "items": {"type": "string", "tpye": "oops"}}
        keys = _collect_all_keys(schema)
        assert "tpye" in keys  # typo is detectable
        assert "items" in keys

    def test_all_of_keywords_are_descended(self):
        # allOf is NOT in _SCHEMA_CONTENT_KEYS — keywords inside it are visible.
        schema = {"allOf": [{"type": "string"}, {"tpye": "oops"}]}
        keys = _collect_all_keys(schema)
        assert "tpye" in keys  # typo inside allOf is detectable
        assert "allOf" in keys

    def test_real_schema_with_user_fields_produces_zero_suspicious_warnings(self):
        schema = {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "email": {"type": "string"},
                "order_count": {"type": "integer"},
            },
            "required": ["customer_id", "email"],
        }
        issues = SchemaValidator._check_common_schema_issues_static(schema, "customer_schema")
        suspicious = [i for i in issues if "unknown/typo" in i.lower()]
        assert suspicious == [], f"False-positive suspicious key warnings: {suspicious}"
