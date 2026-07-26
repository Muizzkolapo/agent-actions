"""A flat schema's top-level ``required:`` array must be honored by every consumer.

Real project schemas declare requiredness as ``required: [a, b]`` at schema
level alongside unmarked ``fields:`` entries. With optional-by-default,
ignoring that array silently drops the author's declared constraints.
"""

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.tooling.docs.parser import extract_fields_for_docs
from agent_actions.validation.prompt_required_field_validator import (
    _optional_field_names,
)


def _schema(**overrides):
    base = {
        "name": "cd_question",
        "fields": [
            {"id": "stem", "type": "string"},
            {"id": "code", "type": "string"},
            {"id": "hint", "type": "string"},
        ],
        "required": ["stem", "code"],
    }
    base.update(overrides)
    return base


def _compiled_required(schema):
    compiled = compile_unified_schema(schema, "openai")
    assert isinstance(compiled, dict)
    inner = compiled.get("schema", compiled)
    return set(inner.get("required", []))


class TestCompileHonorsTopLevelRequired:
    def test_top_level_required_fields_in_compiled_schema(self):
        assert _compiled_required(_schema()) == {"stem", "code"}

    def test_unlisted_fields_stay_optional(self):
        required = _compiled_required(_schema())
        assert "hint" not in required

    def test_explicit_field_required_false_beats_top_level_array(self):
        schema = _schema(
            fields=[
                {"id": "stem", "type": "string", "required": False},
                {"id": "code", "type": "string"},
            ]
        )
        assert _compiled_required(schema) == {"code"}

    def test_top_level_array_combines_with_per_field_markers(self):
        schema = _schema(
            fields=[
                {"id": "stem", "type": "string"},
                {"id": "code", "type": "string"},
                {"id": "hint", "type": "string", "required": True},
            ],
            required=["stem"],
        )
        assert _compiled_required(schema) == {"stem", "hint"}

    def test_required_by_default_still_works_with_top_level_array(self):
        schema = _schema(required_by_default=True, required=["stem"])
        assert _compiled_required(schema) == {"stem", "code", "hint"}


class TestPromptValidatorHonorsTopLevelRequired:
    def test_top_level_required_fields_not_reported_optional(self):
        optional = _optional_field_names(_schema())
        assert "stem" not in optional
        assert "code" not in optional
        assert optional == {"hint"}


class TestDocsParserHonorsTopLevelRequired:
    def test_top_level_required_marked_in_docs(self):
        fields = {f["name"]: f["required"] for f in extract_fields_for_docs(_schema())}
        assert fields["stem"] is True
        assert fields["code"] is True
        assert fields["hint"] is False


class TestSchemaServiceHonorsTopLevelRequired:
    def test_field_metadata_reflects_top_level_required(self):
        from agent_actions.workflow.schema_service import WorkflowSchemaService

        extract = WorkflowSchemaService._extract_field_metadata
        schema = _schema()
        assert extract(schema, "stem")[2] is True
        assert extract(schema, "code")[2] is True
        assert extract(schema, "hint")[2] is False

    def test_field_metadata_explicit_required_false_beats_top_level(self):
        from agent_actions.workflow.schema_service import WorkflowSchemaService

        extract = WorkflowSchemaService._extract_field_metadata
        schema = _schema(
            fields=[
                {"id": "stem", "type": "string", "required": False},
                {"id": "code", "type": "string"},
            ]
        )
        assert extract(schema, "stem")[2] is False
        assert extract(schema, "code")[2] is True
