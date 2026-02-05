"""Tests for the unified ActionSchema model."""

import pytest

from agent_actions.models.action_schema import (
    ActionKind,
    ActionSchema,
    FieldInfo,
    FieldSource,
    UpstreamReference,
)


class TestFieldSource:
    """Tests for FieldSource enum."""

    def test_field_source_values(self):
        """Test FieldSource enum has expected values."""
        assert FieldSource.SCHEMA.value == "schema"
        assert FieldSource.OBSERVE.value == "observe"
        assert FieldSource.PASSTHROUGH.value == "passthrough"
        assert FieldSource.SOURCE.value == "source"
        assert FieldSource.TOOL_OUTPUT.value == "tool_output"


class TestFieldInfo:
    """Tests for FieldInfo dataclass."""

    def test_field_info_defaults(self):
        """Test FieldInfo default values."""
        field = FieldInfo(name="test", source=FieldSource.SCHEMA)
        assert field.name == "test"
        assert field.source == FieldSource.SCHEMA
        assert field.is_required is True
        assert field.is_dropped is False

    def test_field_info_to_dict(self):
        """Test FieldInfo serialization."""
        field = FieldInfo(
            name="summary",
            source=FieldSource.OBSERVE,
            is_required=False,
            is_dropped=True,
        )
        result = field.to_dict()

        assert result == {
            "name": "summary",
            "source": "observe",
            "is_required": False,
            "is_dropped": True,
        }


class TestUpstreamReference:
    """Tests for UpstreamReference dataclass."""

    def test_upstream_reference_fields(self):
        """Test UpstreamReference attributes."""
        ref = UpstreamReference(
            source_agent="extractor",
            field_name="summary",
            location="prompt",
            raw_reference="{{ action.extractor.summary }}",
        )
        assert ref.source_agent == "extractor"
        assert ref.field_name == "summary"
        assert ref.location == "prompt"
        assert ref.raw_reference == "{{ action.extractor.summary }}"

    def test_upstream_reference_to_dict(self):
        """Test UpstreamReference serialization."""
        ref = UpstreamReference(
            source_agent="parser",
            field_name="data.count",
            location="guard",
            raw_reference="{{ action.parser.data.count }}",
        )
        result = ref.to_dict()

        assert result == {
            "source_agent": "parser",
            "field_name": "data.count",
            "location": "guard",
            "raw_reference": "{{ action.parser.data.count }}",
        }


class TestActionSchema:
    """Tests for ActionSchema dataclass."""

    def test_action_schema_defaults(self):
        """Test ActionSchema default values."""
        schema = ActionSchema(name="test", kind=ActionKind.LLM)

        assert schema.name == "test"
        assert schema.kind == ActionKind.LLM
        assert schema.upstream_refs == []
        assert schema.input_fields == []
        assert schema.output_fields == []
        assert schema.dependencies == []
        assert schema.downstream == []
        assert schema.is_dynamic is False
        assert schema.is_schemaless is False
        assert schema.is_template_based is False

    def test_available_outputs_excludes_dropped(self):
        """Test available_outputs property excludes dropped fields."""
        schema = ActionSchema(
            name="processor",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="result", source=FieldSource.SCHEMA, is_dropped=False),
                FieldInfo(name="internal", source=FieldSource.SCHEMA, is_dropped=True),
                FieldInfo(name="meta", source=FieldSource.OBSERVE, is_dropped=False),
            ],
        )

        available = schema.available_outputs
        assert sorted(available) == ["meta", "result"]
        assert "internal" not in available

    def test_dropped_outputs(self):
        """Test dropped_outputs property."""
        schema = ActionSchema(
            name="processor",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="result", source=FieldSource.SCHEMA, is_dropped=False),
                FieldInfo(name="internal", source=FieldSource.SCHEMA, is_dropped=True),
                FieldInfo(name="debug", source=FieldSource.OBSERVE, is_dropped=True),
            ],
        )

        dropped = schema.dropped_outputs
        assert sorted(dropped) == ["debug", "internal"]

    def test_required_inputs(self):
        """Test required_inputs property."""
        schema = ActionSchema(
            name="tool_action",
            kind=ActionKind.TOOL,
            input_fields=[
                FieldInfo(name="text", source=FieldSource.TOOL_OUTPUT, is_required=True),
                FieldInfo(name="count", source=FieldSource.TOOL_OUTPUT, is_required=True),
                FieldInfo(name="options", source=FieldSource.TOOL_OUTPUT, is_required=False),
            ],
        )

        required = schema.required_inputs
        assert sorted(required) == ["count", "text"]

    def test_optional_inputs(self):
        """Test optional_inputs property."""
        schema = ActionSchema(
            name="tool_action",
            kind=ActionKind.TOOL,
            input_fields=[
                FieldInfo(name="text", source=FieldSource.TOOL_OUTPUT, is_required=True),
                FieldInfo(name="options", source=FieldSource.TOOL_OUTPUT, is_required=False),
                FieldInfo(name="format", source=FieldSource.TOOL_OUTPUT, is_required=False),
            ],
        )

        optional = schema.optional_inputs
        assert sorted(optional) == ["format", "options"]

    def test_uses_fields_deduplicates(self):
        """Test uses_fields property deduplicates references."""
        schema = ActionSchema(
            name="consumer",
            kind=ActionKind.LLM,
            upstream_refs=[
                UpstreamReference(
                    "extractor", "summary", "prompt", "{{ action.extractor.summary }}"
                ),
                UpstreamReference(
                    "extractor", "summary", "guard", "{{ action.extractor.summary }}"
                ),
                UpstreamReference("extractor", "facts", "prompt", "{{ action.extractor.facts }}"),
                UpstreamReference("parser", "data", "prompt", "{{ action.parser.data }}"),
            ],
        )

        uses = schema.uses_fields
        assert sorted(uses) == ["extractor.facts", "extractor.summary", "parser.data"]

    def test_action_schema_to_dict(self):
        """Test ActionSchema serialization."""
        schema = ActionSchema(
            name="extractor",
            kind=ActionKind.LLM,
            upstream_refs=[
                UpstreamReference("source", "text", "prompt", "{{ source.text }}"),
            ],
            input_fields=[],
            output_fields=[
                FieldInfo(name="summary", source=FieldSource.SCHEMA),
                FieldInfo(name="original", source=FieldSource.OBSERVE, is_dropped=True),
            ],
            dependencies=["source"],
            downstream=["summarizer"],
            is_dynamic=False,
            is_schemaless=False,
            is_template_based=True,
        )

        result = schema.to_dict()

        assert result["name"] == "extractor"
        assert result["kind"] == "llm"
        assert len(result["upstream_refs"]) == 1
        assert result["upstream_refs"][0]["source_agent"] == "source"
        assert len(result["output_fields"]) == 2
        assert result["available_outputs"] == ["summary"]
        assert result["dropped_outputs"] == ["original"]
        assert result["is_template_based"] is True

    def test_empty_schema_properties(self):
        """Test properties on empty schema."""
        schema = ActionSchema(name="empty", kind=ActionKind.LLM)

        assert schema.available_outputs == []
        assert schema.dropped_outputs == []
        assert schema.required_inputs == []
        assert schema.optional_inputs == []
        assert schema.uses_fields == []
