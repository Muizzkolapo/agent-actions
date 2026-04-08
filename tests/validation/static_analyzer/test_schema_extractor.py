"""Tests for the schema extractor."""

from agent_actions.validation.static_analyzer import SchemaExtractor


class TestSchemaExtractor:
    """Tests for SchemaExtractor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = SchemaExtractor()

    def test_extract_from_inline_schema(self):
        """Test extracting schema from inline JSON schema."""
        config = {
            "name": "extractor",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "keywords": {"type": "array"},
                    "confidence": {"type": "number"},
                },
            },
        }
        schema = self.extractor.extract_schema(config)

        assert "summary" in schema.available_fields
        assert "keywords" in schema.available_fields
        assert "confidence" in schema.available_fields

    def test_output_schema_key_extracts_fields(self):
        """output_schema is a valid key — extractor reads it like schema."""
        config = {
            "name": "agent",
            "output_schema": {
                "type": "object",
                "properties": {
                    "output": {"type": "string"},
                },
            },
        }
        schema = self.extractor.extract_schema(config)

        assert "output" in schema.schema_fields
        assert not schema.is_schemaless

    def test_schemaless_agent(self):
        """Test agent without schema is marked schemaless."""
        config = {
            "name": "agent",
            "prompt": "Generate something",
            # No schema field
        }
        schema = self.extractor.extract_schema(config)

        assert schema.is_schemaless

    def test_tool_agent_schema_from_yaml(self):
        """Test tool agent extracts schema from YAML config."""
        extractor = SchemaExtractor()

        config = {
            "name": "my_tool",
            "kind": "tool",
            "impl": "my_tool_impl",
            "schema": {
                "type": "object",
                "properties": {
                    "tool_result": {"type": "string"},
                    "status": {"type": "boolean"},
                },
            },
        }
        schema = extractor.extract_schema(config)

        assert "tool_result" in schema.available_fields
        assert "status" in schema.available_fields

    def test_context_scope_observe(self):
        """Test context_scope observe adds fields."""
        config = {
            "name": "agent",
            "schema": {
                "type": "object",
                "properties": {
                    "own_field": {"type": "string"},
                },
            },
            "context_scope": {
                "observe": ["upstream.extra_field"],
            },
        }
        schema = self.extractor.extract_schema(config)

        assert "own_field" in schema.available_fields
        # observe adds to available fields
        assert "extra_field" in schema.observe_fields or "extra_field" in schema.available_fields

    def test_context_scope_drop(self):
        """Test context_scope drop removes fields."""
        config = {
            "name": "agent",
            "schema": {
                "type": "object",
                "properties": {
                    "keep_field": {"type": "string"},
                    "drop_field": {"type": "string"},
                },
            },
            "context_scope": {
                "drop": ["drop_field"],
            },
        }
        schema = self.extractor.extract_schema(config)

        assert "keep_field" in schema.available_fields
        assert "drop_field" in schema.dropped_fields

    def test_context_scope_passthrough(self):
        """Test context_scope passthrough adds fields."""
        config = {
            "name": "agent",
            "context_scope": {
                "passthrough": ["upstream.field1", "upstream.field2"],
            },
        }
        schema = self.extractor.extract_schema(config)

        # Passthrough fields should be added to passthrough_fields
        assert "field1" in schema.passthrough_fields
        assert "field2" in schema.passthrough_fields

    def test_nested_schema_properties(self):
        """Test extracting only top-level properties."""
        config = {
            "name": "agent",
            "schema": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                        },
                    },
                    "timestamp": {"type": "string"},
                },
            },
        }
        schema = self.extractor.extract_schema(config)

        # Should have top-level fields
        assert "user" in schema.available_fields
        assert "timestamp" in schema.available_fields
        # Should NOT have nested fields at top level
        assert "name" not in schema.available_fields

    def test_output_field_produces_named_field(self):
        """Test that output_field declares the named field in schema_fields."""
        config = {
            "name": "classify",
            "json_mode": False,
            "output_field": "issue_type",
            "prompt": "Classify this issue",
        }
        schema = self.extractor.extract_schema(config)

        assert "issue_type" in schema.schema_fields
        assert "issue_type" in schema.available_fields
        assert "content" in schema.available_fields
        # raw_response should NOT appear — output_field replaces it
        assert "raw_response" not in schema.available_fields

    def test_non_json_without_output_field_defaults_to_raw_response(self):
        """Regression guard: non-JSON mode without output_field still produces raw_response."""
        config = {
            "name": "agent",
            "json_mode": False,
            "prompt": "Generate something",
        }
        schema = self.extractor.extract_schema(config)

        assert "raw_response" in schema.available_fields
        assert "content" in schema.available_fields
        assert schema.is_schemaless

    def test_hitl_agent_uses_canonical_hitl_schema(self):
        """Test HITL action uses the canonical HITL output schema."""
        config = {
            "name": "review",
            "kind": "hitl",
            "model_vendor": "hitl",
        }
        schema = self.extractor.extract_schema(config)

        assert not schema.is_schemaless
        assert "hitl_status" in schema.available_fields
        assert "user_comment" in schema.available_fields
        assert "timestamp" in schema.available_fields

    def test_hitl_agent_input_schema_is_empty(self):
        """Test HITL action has no input schema (receives context_data at runtime)."""
        config = {
            "name": "review",
            "kind": "hitl",
            "model_vendor": "hitl",
        }
        input_schema = self.extractor.extract_input_schema(config)

        assert not input_schema.required_fields
        assert not input_schema.optional_fields


class TestInputSchemaExtraction:
    """Tests for input schema extraction."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = SchemaExtractor()

    def test_tool_agent_input_from_registry(self):
        """Test tool agent extracts input schema from UDF registry."""
        udf_registry = {
            "my_tool": {
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "input_field": {"type": "string"},
                        "optional_field": {"type": "number"},
                    },
                    "required": ["input_field"],
                },
            },
        }

        extractor = SchemaExtractor(udf_registry=udf_registry)

        config = {
            "name": "tool_action",
            "kind": "tool",
            "impl": "my_tool",
        }
        input_schema = extractor.extract_input_schema(config)

        assert "input_field" in input_schema.required_fields
        assert "optional_field" in input_schema.optional_fields

    def test_tool_agent_without_registry(self):
        """Test tool agent without registry has dynamic input."""
        config = {
            "name": "tool_action",
            "kind": "tool",
            "impl": "unknown_tool",
        }
        input_schema = self.extractor.extract_input_schema(config)

        assert input_schema.is_dynamic

    def test_tool_agent_with_inline_input_schema(self):
        """Test tool agent with inline input_schema."""
        config = {
            "name": "tool_action",
            "kind": "tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "data": {"type": "string"},
                },
                "required": ["data"],
            },
        }
        input_schema = self.extractor.extract_input_schema(config)

        assert "data" in input_schema.required_fields


class TestContextScopeInference:
    """Tests for inferring input schema from context_scope (new style UDFs)."""

    def test_tool_infers_input_from_context_scope_observe(self):
        """Test tool without input_type infers input from context_scope.observe."""
        # UDF registry with no input schema (new style)
        udf_registry = {
            "new_style_tool": {
                "json_schema": None,  # No input schema
            },
        }

        extractor = SchemaExtractor(udf_registry=udf_registry)

        config = {
            "name": "process_data",
            "kind": "tool",
            "impl": "new_style_tool",
            "context_scope": {
                "observe": [
                    "upstream.field1",
                    "upstream.field2",
                    "other_dep.data",
                ]
            },
        }
        input_schema = extractor.extract_input_schema(config)

        assert not input_schema.is_dynamic
        assert input_schema.derived_from_context_scope
        assert "upstream.field1" in input_schema.required_fields
        assert "upstream.field2" in input_schema.required_fields
        assert "other_dep.data" in input_schema.required_fields

    def test_tool_infers_input_from_wildcard(self):
        """Test tool handles wildcard context_scope (dep_name.*)."""
        extractor = SchemaExtractor()

        config = {
            "name": "process_all",
            "kind": "tool",
            "impl": "unknown_tool",
            "context_scope": {
                "observe": ["upstream.*"],
            },
        }
        input_schema = extractor.extract_input_schema(config)

        assert not input_schema.is_dynamic
        assert input_schema.derived_from_context_scope
        assert "upstream.*" in input_schema.required_fields

    def test_tool_infers_input_from_passthrough(self):
        """Test tool includes passthrough fields as inputs."""
        extractor = SchemaExtractor()

        config = {
            "name": "pass_through_tool",
            "kind": "tool",
            "impl": "passthrough_tool",
            "context_scope": {
                "observe": ["dep.field1"],
                "passthrough": ["dep.field2", "dep.field3"],
            },
        }
        input_schema = extractor.extract_input_schema(config)

        assert input_schema.derived_from_context_scope
        assert "dep.field1" in input_schema.required_fields
        assert "dep.field2" in input_schema.required_fields
        assert "dep.field3" in input_schema.required_fields

    def test_tool_without_context_scope_is_dynamic(self):
        """Test tool without context_scope has dynamic input."""
        extractor = SchemaExtractor()

        config = {
            "name": "dynamic_tool",
            "kind": "tool",
            "impl": "dynamic_tool",
            # No context_scope
        }
        input_schema = extractor.extract_input_schema(config)

        assert input_schema.is_dynamic
        assert not input_schema.derived_from_context_scope

    def test_explicit_input_schema_takes_precedence_over_context_scope(self):
        """Test that explicit input_schema takes precedence over context_scope inference."""
        udf_registry = {
            "explicit_tool": {
                "json_schema": {
                    "type": "object",
                    "properties": {"explicit_field": {"type": "string"}},
                    "required": ["explicit_field"],
                },
            },
        }

        extractor = SchemaExtractor(udf_registry=udf_registry)

        config = {
            "name": "explicit_tool_action",
            "kind": "tool",
            "impl": "explicit_tool",
            "context_scope": {
                "observe": ["dep.field1", "dep.field2"],
            },
        }
        input_schema = extractor.extract_input_schema(config)

        # Explicit schema takes precedence
        assert not input_schema.derived_from_context_scope
        assert "explicit_field" in input_schema.required_fields
        assert "dep.field1" not in input_schema.required_fields


class TestNullContextScopeNormalization:
    """Regression: YAML null context_scope normalized before reaching extractors.

    The normalizer (normalize_context_scope) guarantees a dict return.
    The static analyzer calls it at Step 0 before graph building.
    These tests verify the normalizer contract directly.
    """

    def test_normalize_null_returns_empty_dict(self):
        """normalize_context_scope returns {} for None input."""
        from agent_actions.input.context.normalizer import normalize_context_scope

        result = normalize_context_scope(None, {})
        assert result == {}

    def test_normalize_null_directive_becomes_empty_list(self):
        """Null list directives (passthrough: null) become []."""
        from agent_actions.input.context.normalizer import normalize_context_scope

        result = normalize_context_scope(
            {"observe": ["dep.*"], "passthrough": None}, {}
        )
        assert result["observe"] == ["dep.*"]
        assert result["passthrough"] == []

    def test_static_analyzer_handles_null_context_scope(self):
        """Static analyzer normalizes null context_scope before graph building."""
        from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
            WorkflowStaticAnalyzer,
        )

        workflow = {
            "name": "test",
            "actions": [
                {
                    "name": "broken",
                    "schema": {"type": "object", "properties": {"f": {"type": "string"}}},
                    "context_scope": None,
                }
            ],
        }
        analyzer = WorkflowStaticAnalyzer(workflow)
        # Should not crash — normalizer converts None to {}
        result = analyzer.analyze()
        # Should report missing context_scope as an error
        errors = [e for e in result.errors if "no context_scope" in e.message]
        assert len(errors) == 1
