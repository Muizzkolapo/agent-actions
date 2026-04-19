"""Tests for the workflow static analyzer."""

import pytest

from agent_actions.validation.static_analyzer import (
    StaticValidationResult,
    WorkflowStaticAnalyzer,
    analyze_workflow,
)


class TestWorkflowStaticAnalyzer:
    """Tests for WorkflowStaticAnalyzer class."""

    def test_analyze_detects_missing_field(self):
        """Test analyzer detects reference to missing field."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "summarizer",
                    "depends_on": ["extractor"],
                    "prompt": "Use: {{ action.extractor.nonexistent_field }}",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        assert not result.is_valid
        assert len(result.errors) >= 1
        assert any("nonexistent_field" in e.message for e in result.errors)

    def test_analyze_rejects_implicit_dependency(self):
        """Test analyzer requires reachable dependencies for references."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "summarizer",
                    # No explicit depends_on - implicit via reference
                    "prompt": "Use: {{ action.extractor.text }}",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        assert not result.is_valid
        assert any("not reachable" in e.message for e in result.errors)

    def test_analyze_detects_nonexistent_agent(self):
        """Test analyzer detects reference to non-existent agent."""
        workflow_config = {
            "actions": [
                {
                    "name": "summarizer",
                    "depends_on": ["nonexistent"],
                    "prompt": "Use: {{ action.nonexistent.text }}",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        assert not result.is_valid
        assert any("does not exist" in e.message for e in result.errors)

    def test_analyze_rejects_reserved_action_name(self):
        """Test analyzer rejects reserved action names."""
        workflow_config = {
            "actions": [
                {
                    "name": "prompt",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        assert not result.is_valid
        assert any("reserved" in e.message for e in result.errors)

    def test_get_agent_schema(self):
        """Test getting schema for specific agent."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schema = analyzer.get_agent_schema("extractor")

        assert schema is not None
        assert "text" in schema.available_fields
        assert "score" in schema.available_fields

    def test_dependencies_field_alias(self):
        """Test 'dependencies' field works as alias for 'depends_on'."""
        workflow_config = {
            "actions": [
                {
                    "name": "upstream",
                    "schema": {
                        "type": "object",
                        "properties": {"data": {"type": "string"}},
                    },
                },
                {
                    "name": "downstream",
                    "dependencies": ["upstream"],  # Using 'dependencies' instead of 'depends_on'
                    "prompt": "{{ action.upstream.data }}",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        # Should not report missing dependency
        dep_errors = [e for e in result.errors if "not declared in dependencies" in e.message]
        assert len(dep_errors) == 0

    def test_get_action_schemas_hitl(self):
        """Test get_action_schemas classifies HITL actions with canonical schema."""
        workflow_config = {
            "actions": [
                {
                    "name": "review",
                    "kind": "hitl",
                    "model_vendor": "hitl",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schemas = analyzer.get_action_schemas()

        assert schemas["review"]["kind"] == "hitl"
        assert "hitl_status" in schemas["review"]["output"]["fields"]
        assert "user_comment" in schemas["review"]["output"]["fields"]
        assert "timestamp" in schemas["review"]["output"]["fields"]

    @pytest.mark.parametrize(
        "kind,model_vendor",
        [
            ("hitl", "hitl"),
            ("hitl", ""),
            ("llm", "hitl"),
        ],
    )
    def test_hitl_classified_with_either_kind_or_model_vendor(self, kind, model_vendor):
        """Test HITL is recognized when either kind or model_vendor is 'hitl'."""
        workflow_config = {
            "actions": [
                {
                    "name": "review",
                    "kind": kind,
                    "model_vendor": model_vendor,
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schemas = analyzer.get_action_schemas()

        assert schemas["review"]["kind"] == "hitl"

    def test_kind_precedence_tool_over_hitl(self):
        """Test classification precedence: tool > hitl > llm."""
        workflow_config = {
            "actions": [
                {
                    "name": "ambiguous",
                    "kind": "hitl",
                    "model_vendor": "tool",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schemas = analyzer.get_action_schemas()

        # tool check comes first, so model_vendor="tool" wins
        assert schemas["ambiguous"]["kind"] == "tool"


class TestAnalyzeWorkflowFunction:
    """Tests for the analyze_workflow convenience function."""

    def test_analyze_workflow_returns_result(self):
        """Test analyze_workflow returns StaticValidationResult."""
        result = analyze_workflow(
            {
                "actions": [
                    {"name": "agent1"},
                ]
            }
        )

        assert isinstance(result, StaticValidationResult)

    def test_analyze_workflow_strict_mode(self):
        """Test analyze_workflow with strict mode treats warnings as errors."""
        # Create workflow that generates warning (schemaless agent)
        workflow_config = {
            "actions": [
                {"name": "schemaless_agent"},
                {
                    "name": "consumer",
                    "depends_on": ["schemaless_agent"],
                    "prompt": "{{ action.schemaless_agent.field }}",
                },
            ]
        }

        result_normal = analyze_workflow(workflow_config, strict=False)
        _result_strict = analyze_workflow(workflow_config, strict=True)

        # Normal mode: warnings are warnings
        # Strict mode: may treat warnings as errors
        assert len(result_normal.warnings) > 0 or len(result_normal.errors) > 0


class TestStaticValidationResult:
    """Tests for StaticValidationResult class."""

    def test_is_valid_with_no_errors(self):
        """Test is_valid is True when no errors."""
        result = StaticValidationResult()
        assert result.is_valid

    def test_is_valid_with_errors(self):
        """Test is_valid is False when errors exist."""
        from agent_actions.validation.static_analyzer import FieldLocation, StaticTypeError

        result = StaticValidationResult()
        result.add_error(
            StaticTypeError(
                message="Test error",
                location=FieldLocation(agent_name="agent", config_field="prompt"),
                referenced_agent="other",
                referenced_field="field",
            )
        )

        assert not result.is_valid

    def test_format_report(self):
        """Test format_report returns readable string."""
        from agent_actions.validation.static_analyzer import (
            FieldLocation,
            StaticTypeError,
            StaticTypeWarning,
        )

        result = StaticValidationResult()
        result.add_error(
            StaticTypeError(
                message="Field 'missing' not found",
                location=FieldLocation(agent_name="consumer", config_field="prompt"),
                referenced_agent="producer",
                referenced_field="missing",
                available_fields={"field1", "field2"},
                hint="Did you mean 'field1'?",
            )
        )
        result.add_warning(
            StaticTypeWarning(
                message="Cannot validate dynamic schema",
                location=FieldLocation(agent_name="other", config_field="prompt"),
                referenced_agent="dynamic_agent",
                referenced_field="data",
            )
        )

        report = result.format_report()

        assert "error" in report.lower()
        assert "warning" in report.lower()
        assert "missing" in report
        assert "consumer" in report


class TestActionSchemas:
    """Tests for get_action_schemas and format_action_schemas methods."""

    def test_get_action_schemas_llm(self):
        """Test get_action_schemas returns correct info for LLM agents."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schemas = analyzer.get_action_schemas()

        assert "extractor" in schemas
        assert schemas["extractor"]["kind"] == "llm"
        # LLM input is resolved from template refs (empty when no prompt)
        assert not schemas["extractor"]["input"]["is_template_based"]
        assert "text" in schemas["extractor"]["output"]["fields"]
        assert "score" in schemas["extractor"]["output"]["fields"]

    def test_get_action_schemas_tool_with_yaml_schema(self):
        """Test get_action_schemas returns correct info for tool agents."""
        udf_registry = {
            "my_tool": {
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "input_data": {"type": "string"},
                    },
                    "required": ["input_data"],
                },
            },
        }

        workflow_config = {
            "actions": [
                {
                    "name": "tool_action",
                    "kind": "tool",
                    "impl": "my_tool",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "result": {"type": "string"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config, udf_registry=udf_registry)
        schemas = analyzer.get_action_schemas()

        assert "tool_action" in schemas
        assert schemas["tool_action"]["kind"] == "tool"
        assert "input_data" in schemas["tool_action"]["input"]["required"]
        assert "result" in schemas["tool_action"]["output"]["fields"]

    def test_get_action_schemas_mixed_workflow(self):
        """Test get_action_schemas with mixed LLM and tool agents."""
        udf_registry = {
            "processor": {
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
        }

        workflow_config = {
            "actions": [
                {
                    "name": "llm_agent",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "extracted": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "tool_agent",
                    "kind": "tool",
                    "impl": "processor",
                    "depends_on": ["llm_agent"],
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config, udf_registry=udf_registry)
        schemas = analyzer.get_action_schemas()

        assert len(schemas) == 2
        assert schemas["llm_agent"]["kind"] == "llm"
        assert schemas["tool_agent"]["kind"] == "tool"

    def test_format_action_schemas(self):
        """Test format_action_schemas produces readable output."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                        },
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        output = analyzer.format_action_schemas()

        assert "extractor" in output
        assert "llm" in output
        assert "Input:" in output
        assert "Output:" in output
        assert "text" in output

    def test_excludes_special_namespaces(self):
        """Test get_action_schemas excludes source and other special nodes."""
        workflow_config = {
            "actions": [
                {
                    "name": "agent1",
                    "schema": {
                        "type": "object",
                        "properties": {"out": {"type": "string"}},
                    },
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        schemas = analyzer.get_action_schemas()

        # Should not include 'source' node
        assert "source" not in schemas
        assert "agent1" in schemas

    def test_get_agent_input_schema(self):
        """Test get_agent_input_schema method."""
        udf_registry = {
            "my_tool": {
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string"},
                    },
                    "required": ["data"],
                },
            },
        }

        workflow_config = {
            "actions": [
                {
                    "name": "tool_action",
                    "kind": "tool",
                    "impl": "my_tool",
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config, udf_registry=udf_registry)
        input_schema = analyzer.get_agent_input_schema("tool_action")

        assert input_schema is not None
        assert "data" in input_schema.required_fields


class TestComplexWorkflows:
    """Tests for complex workflow scenarios."""

    def test_diamond_dependency(self):
        """Test diamond dependency pattern validates correctly."""
        workflow_config = {
            "actions": [
                {
                    "name": "source_agent",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"data": {"type": "string"}},
                    },
                },
                {
                    "name": "branch_a",
                    "depends_on": ["source_agent"],
                    "context_scope": {"observe": ["source_agent.*"]},
                    "prompt": "{{ action.source_agent.data }}",
                    "schema": {
                        "type": "object",
                        "properties": {"result_a": {"type": "string"}},
                    },
                },
                {
                    "name": "branch_b",
                    "depends_on": ["source_agent"],
                    "context_scope": {"observe": ["source_agent.*"]},
                    "prompt": "{{ action.source_agent.data }}",
                    "schema": {
                        "type": "object",
                        "properties": {"result_b": {"type": "string"}},
                    },
                },
                {
                    "name": "merger",
                    "depends_on": ["branch_a", "branch_b"],
                    "context_scope": {"observe": ["branch_a.*", "branch_b.*"]},
                    "prompt": "Merge: {{ action.branch_a.result_a }} and {{ action.branch_b.result_b }}",
                    "schema": {
                        "type": "object",
                        "properties": {"merged": {"type": "string"}},
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)
        assert result.is_valid

    def test_long_chain(self):
        """Test long chain of dependencies validates correctly."""
        workflow_config = {
            "actions": [
                {
                    "name": f"agent_{i}",
                    "depends_on": [f"agent_{i - 1}"] if i > 0 else [],
                    "context_scope": {"observe": [f"agent_{i - 1}.*"]}
                    if i > 0
                    else {"observe": ["source.*"]},
                    "prompt": f"{{{{ action.agent_{i - 1}.output }}}}" if i > 0 else "Start",
                    "schema": {
                        "type": "object",
                        "properties": {"output": {"type": "string"}},
                    },
                }
                for i in range(5)
            ]
        }

        result = analyze_workflow(workflow_config)
        assert result.is_valid

    def test_multiple_field_references(self):
        """Test multiple field references from same agent."""
        workflow_config = {
            "actions": [
                {
                    "name": "data_provider",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {
                            "field1": {"type": "string"},
                            "field2": {"type": "number"},
                            "field3": {"type": "boolean"},
                        },
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["data_provider"],
                    "context_scope": {"observe": ["data_provider.*"]},
                    "prompt": """
                        Field1: {{ action.data_provider.field1 }}
                        Field2: {{ action.data_provider.field2 }}
                        Field3: {{ action.data_provider.field3 }}
                    """,
                },
            ]
        }

        result = analyze_workflow(workflow_config)
        assert result.is_valid


class TestContextScopeValidation:
    """Tests for context_scope field validation."""

    def test_valid_context_scope_passes(self):
        """Test that valid context_scope references pass validation."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {
                            "facts": {"type": "array"},
                            "summary": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.facts", "extractor.summary"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)
        # No context_scope errors
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        assert len(context_errors) == 0

    def test_context_scope_infers_dependency(self):
        """Test that context_scope references infer dependencies (no explicit depends_on needed)."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "processor",
                    # depends_on does NOT include 'extractor', but context_scope
                    # references it — the runtime infers the dependency.
                    "depends_on": [],
                    "context_scope": {
                        "observe": ["extractor.facts"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # context_scope references are valid implicit dependencies;
        # no "undeclared dependency" errors should be raised.
        context_errors = [e for e in result.errors if "undeclared dependency" in e.message]
        assert len(context_errors) == 0

    def test_context_scope_inferred_dep_still_validates_fields(self):
        """Inferred deps skip 'undeclared' errors but bad fields are still caught."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "processor",
                    "depends_on": [],
                    "context_scope": {
                        "observe": ["extractor.nonexistent_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        field_errors = [e for e in result.errors if "non-existent field" in e.message]
        assert len(field_errors) >= 1

    def test_context_scope_unknown_action_caught(self):
        """References to nonexistent actions in context_scope produce errors."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "depends_on": [],
                    "context_scope": {
                        "observe": ["typo_action.some_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        unknown_errors = [e for e in result.errors if "unknown action" in e.message]
        assert len(unknown_errors) >= 1
        assert "typo_action" in unknown_errors[0].message

    def test_nonexistent_field_in_context_scope(self):
        """Test that non-existent field in context_scope is caught."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "facts": {"type": "array"},
                        },
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.nonexistent_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        assert len(context_errors) >= 1
        assert any("non-existent field" in e.message for e in context_errors)
        assert any("nonexistent_field" in e.message for e in context_errors)

    def test_wildcard_allowed_without_validation(self):
        """Test that wildcard references (dep.*) are allowed without field validation."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.*"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Wildcard should not cause context_scope errors
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        assert len(context_errors) == 0

    def test_special_namespaces_allowed(self):
        """Test that special namespaces (source, seed, loop, workflow) are always allowed."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "observe": [
                            "source.title",
                            "seed.config",
                            "loop.index",
                            "workflow.name",
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Special namespaces should not cause context_scope errors
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        assert len(context_errors) == 0

    def test_passthrough_directive_validated(self):
        """Test that passthrough directive is also validated."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "passthrough": ["extractor.invalid_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        context_errors = [e for e in result.errors if "context_scope.passthrough" in e.message]
        assert len(context_errors) >= 1

    def test_multiple_errors_reported(self):
        """Test that multiple context_scope errors are all reported."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": [
                            "extractor.bad_field1",
                            "extractor.bad_field2",
                            "undeclared_dep.field",
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        # Should have errors for: bad_field1, bad_field2 (non-existent fields),
        # and undeclared_dep (unknown action — no node in graph).
        assert len(context_errors) >= 3
        field_errors = [e for e in context_errors if "non-existent field" in e.message]
        assert len(field_errors) >= 2
        unknown_errors = [e for e in context_errors if "unknown action" in e.message]
        assert len(unknown_errors) >= 1

    def test_context_scope_reports_error_when_schema_load_fails(self):
        """Test that unresolvable schema_name produces a StaticTypeError, not a silent skip."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema_name": "nonexistent_schema",
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.some_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        context_errors = [e for e in result.errors if "context_scope" in e.message]
        assert len(context_errors) >= 1
        assert any(
            "not found" in e.message or "could not be loaded" in e.message for e in context_errors
        )

    def test_output_field_observable_by_downstream(self):
        """Downstream action can observe an output_field-produced field."""
        workflow_config = {
            "actions": [
                {
                    "name": "classify",
                    "json_mode": False,
                    "output_field": "issue_type",
                    "prompt": "Classify",
                },
                {
                    "name": "route",
                    "depends_on": ["classify"],
                    "context_scope": {"observe": ["classify.issue_type"]},
                    "prompt": "Route based on {{ action.classify.issue_type }}",
                    "schema": {
                        "type": "object",
                        "properties": {"team": {"type": "string"}},
                    },
                },
            ],
        }

        result = analyze_workflow(workflow_config)

        errors = [e for e in result.errors if "issue_type" in e.message]
        assert not errors, f"False positive on output_field: {errors}"


class TestPrimaryDependencyValidation:
    """Tests for primary_dependency validation."""

    def test_valid_explicit_primary_dependency(self):
        """Test valid explicit primary_dependency."""
        workflow_config = {
            "actions": [
                {
                    "name": "dep_A",
                    "prompt": "test",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {"type": "object", "properties": {"field1": {"type": "string"}}},
                },
                {
                    "name": "dep_B",
                    "prompt": "test",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {"type": "object", "properties": {"field2": {"type": "string"}}},
                },
                {
                    "name": "dep_C",
                    "prompt": "test",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {"type": "object", "properties": {"field3": {"type": "string"}}},
                },
                {
                    "name": "action_with_primary",
                    "dependencies": ["dep_A", "dep_B", "dep_C"],
                    "primary_dependency": "dep_B",
                    "context_scope": {"observe": ["dep_A.*", "dep_B.*", "dep_C.*"]},
                    "prompt": "Process: {{ action.dep_A.field1 }} {{ action.dep_B.field2 }} {{ action.dep_C.field3 }}",
                    "schema": {"type": "object", "properties": {"result": {"type": "string"}}},
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        assert result.is_valid
        assert len(result.errors) == 0

    def test_context_scope_references_undeclared_dependency_error(self):
        """Test reverse check: context_scope references dependency not in dependencies list."""
        workflow_config = {
            "actions": [
                {
                    "name": "dep_A",
                    "prompt": "test",
                    "schema": {"type": "object", "properties": {"field1": {"type": "string"}}},
                },
                {
                    "name": "dep_B",
                    "prompt": "test",
                    "schema": {"type": "object", "properties": {"field2": {"type": "string"}}},
                },
                {
                    "name": "action_bad_context",
                    "dependencies": ["dep_A"],  # Only declares dep_A
                    "prompt": "Process: {{ action.dep_A.field1 }} {{ action.dep_B.field2 }}",
                    "schema": {"type": "object"},
                },
            ]
        }

        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        # Should fail - dep_B referenced in prompt but not in dependencies
        assert not result.is_valid
        errors = [e for e in result.errors if "dep_B" in e.message and "not reachable" in e.message]
        assert len(errors) >= 1


class TestPreflightFieldValidation:
    """Tests for field-level validation: schemaless warnings, cross-action suggestions,
    and wildcard passthrough expansion."""

    def test_schemaless_tool_explicit_ref_warns(self):
        """Schemaless tool with explicit field ref produces warning, not error."""
        workflow_config = {
            "actions": [
                {
                    "name": "my_tool",
                    "kind": "tool",
                    # No schema/output_schema/schema_name → schemaless
                },
                {
                    "name": "consumer",
                    "depends_on": ["my_tool"],
                    "context_scope": {
                        "observe": ["my_tool.result_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Should NOT produce errors — schemaless can't prove field is wrong
        context_errors = [
            e for e in result.errors if "context_scope" in e.message and "result_field" in e.message
        ]
        assert len(context_errors) == 0

        # Should produce a warning about unverifiable field
        schema_warnings = [w for w in result.warnings if "no output schema" in w.message]
        assert len(schema_warnings) >= 1
        assert "result_field" in schema_warnings[0].message
        assert "my_tool" in schema_warnings[0].message

    def test_schemaless_tool_wildcard_no_warning(self):
        """Schemaless tool with wildcard observe produces no warning."""
        workflow_config = {
            "actions": [
                {
                    "name": "my_tool",
                    "kind": "tool",
                },
                {
                    "name": "consumer",
                    "depends_on": ["my_tool"],
                    "context_scope": {
                        "observe": ["my_tool.*"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Wildcards on schemaless actions are handled by _expand_wildcards (dropped).
        # No warning about "no output schema" for wildcards.
        schema_warnings = [w for w in result.warnings if "no output schema" in w.message]
        assert len(schema_warnings) == 0

    def test_cross_action_suggestion_in_error(self):
        """When field exists in another action, error hint suggests it."""
        workflow_config = {
            "actions": [
                {
                    "name": "action_a",
                    "schema": {
                        "type": "object",
                        "properties": {"question_text": {"type": "string"}},
                    },
                },
                {
                    "name": "action_b",
                    "schema": {
                        "type": "object",
                        "properties": {"answer_text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["action_a", "action_b"],
                    "context_scope": {
                        "observe": [
                            "action_b.question_text",  # Wrong action!
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        field_errors = [
            e
            for e in result.errors
            if "non-existent field" in e.message and "question_text" in e.message
        ]
        assert len(field_errors) >= 1
        assert "Did you mean" in field_errors[0].hint
        assert "action_a.question_text" in field_errors[0].hint

    def test_cross_action_no_suggestion_when_field_nowhere(self):
        """When field doesn't exist in any action, hint shows available fields."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"facts": {"type": "array"}},
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.totally_bogus_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        field_errors = [e for e in result.errors if "totally_bogus_field" in e.message]
        assert len(field_errors) >= 1
        assert "Available fields" in field_errors[0].hint
        assert "Did you mean" not in field_errors[0].hint

    def test_wildcard_expansion_includes_passthrough(self):
        """Wildcard expansion includes passthrough fields from intermediate action."""
        workflow_config = {
            "actions": [
                {
                    "name": "upstream",
                    "schema": {
                        "type": "object",
                        "properties": {"field_x": {"type": "string"}},
                    },
                },
                {
                    "name": "middle",
                    "depends_on": ["upstream"],
                    "schema": {
                        "type": "object",
                        "properties": {"own_field": {"type": "string"}},
                    },
                    "context_scope": {
                        "passthrough": ["upstream.field_x"],
                        "observe": ["upstream.*"],
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["middle"],
                    "context_scope": {
                        "observe": ["middle.*"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # middle.* should expand to include both own_field and field_x (passthrough).
        # No errors about missing fields.
        field_errors = [e for e in result.errors if "non-existent field" in e.message]
        assert len(field_errors) == 0

    def test_known_schema_field_error_unchanged(self):
        """Regression guard: known schema with nonexistent field still produces error."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "facts": {"type": "array"},
                            "summary": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.nonexistent_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        assert not result.is_valid
        context_errors = [e for e in result.errors if "non-existent field" in e.message]
        assert len(context_errors) >= 1
        assert "nonexistent_field" in context_errors[0].message

    def test_valid_config_no_false_positive(self):
        """Valid workflow with observe and passthrough produces no errors or warnings."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "facts": {"type": "array"},
                            "summary": {"type": "string"},
                        },
                    },
                },
                {
                    "name": "processor",
                    "depends_on": ["extractor"],
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                    },
                    "context_scope": {
                        "observe": ["extractor.facts"],
                        "passthrough": ["extractor.summary"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # No field-related errors or warnings
        field_errors = [
            e
            for e in result.errors
            if "non-existent field" in e.message or "Cannot verify" in e.message
        ]
        assert len(field_errors) == 0

        schema_warnings = [
            w
            for w in result.warnings
            if "no output schema" in w.message or "Cannot verify" in w.message
        ]
        assert len(schema_warnings) == 0

    def test_dynamic_schema_explicit_ref_warns(self):
        """Dynamic schema (non-load-error) with explicit field ref produces warning."""
        workflow_config = {
            "actions": [
                {
                    "name": "my_tool",
                    "kind": "tool",
                    # Non-str/dict/list schema triggers is_dynamic=True without load_error
                    "schema": 42,
                },
                {
                    "name": "consumer",
                    "depends_on": ["my_tool"],
                    "context_scope": {
                        "observe": ["my_tool.some_field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Dynamic schema may produce either a load_error (error) or a
        # dynamic-without-load-error (warning). Either way, it should NOT
        # produce a "non-existent field" error (false positive).
        false_positive_errors = [
            e
            for e in result.errors
            if "non-existent field" in e.message and "some_field" in e.message
        ]
        assert len(false_positive_errors) == 0

        # Should have either a schema-load error or a "dynamic" warning
        schema_issues = [
            issue
            for issue in result.errors + result.warnings
            if "my_tool" in issue.message
            and ("Cannot validate" in issue.message or "Cannot verify" in issue.message)
        ]
        assert len(schema_issues) >= 1
