"""Union type declarations (``type: ["string", "null"]``) are legal JSON Schema
and must validate member-wise — at the top level, in properties, and in
list-style fields — instead of crashing an unhashable membership check.
"""

from agent_actions.validation.static_analyzer.schema_structure_validator import (
    SchemaStructureValidator,
)


def _validate(schema):
    return SchemaStructureValidator().validate_schema(schema, "producer", "schema")


class TestUnionTypesAccepted:
    def test_top_level_union_type_no_error(self):
        schema = {"type": ["object", "null"], "properties": {"status": {"type": "string"}}}
        assert _validate(schema) == []

    def test_property_union_type_no_error(self):
        schema = {"type": "object", "properties": {"status": {"type": ["string", "null"]}}}
        assert _validate(schema) == []

    def test_fields_style_union_type_no_error(self):
        schema = {"fields": [{"id": "status", "type": ["string", "null"]}]}
        assert _validate(schema) == []


class TestInvalidTypesStillRejected:
    def test_union_with_unknown_member_is_error(self):
        schema = {"type": "object", "properties": {"status": {"type": ["string", "bogus"]}}}
        errors = _validate(schema)
        assert len(errors) == 1
        assert "status" in errors[0].message

    def test_top_level_union_with_unknown_member_is_error(self):
        schema = {"type": ["object", "bogus"], "properties": {"status": {"type": "string"}}}
        errors = _validate(schema)
        assert len(errors) == 1

    def test_non_string_non_list_type_is_error(self):
        schema = {"type": "object", "properties": {"status": {"type": 42}}}
        errors = _validate(schema)
        assert len(errors) == 1
        assert "status" in errors[0].message
