"""Tests for context scope processing functions."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    format_llm_context,
    merge_passthrough_fields,
)
from agent_actions.prompt.context.scope_namespace import (
    _extract_allowed_fields_per_dependency,
    _filter_and_store_fields,
)
from agent_actions.prompt.context.scope_parsing import extract_field_value


class TestContextScopeProcessor:
    """Test suite for ContextScopeProcessor - essential tests only."""

    def test_apply_context_scope_all_directives(self):
        """Test apply_context_scope with all three directives working together."""
        # Setup field context with multiple actions and fields
        field_context = {
            "source": {"page_content": "Sample text data", "api_key": "secret_key_12345"},
            "fact_extractor": {
                "candidate_facts": ["fact1", "fact2"],
                "extracted_entities": ["entity1", "entity2"],
                "metadata": {"count": 2, "source": "research"},
                "document_id": "doc-123",
            },
        }

        # Setup context_scope with all three directives
        context_scope = {
            "observe": ["fact_extractor.extracted_entities", "fact_extractor.metadata"],
            "drop": ["source.api_key"],
            "passthrough": ["fact_extractor.document_id"],
        }

        # Execute
        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # Validate OBSERVE directive — namespaced under action name
        assert llm_context["fact_extractor"]["extracted_entities"] == ["entity1", "entity2"]
        assert llm_context["fact_extractor"]["metadata"] == {"count": 2, "source": "research"}
        # Observed fields should REMAIN in prompt_context for template rendering
        assert "extracted_entities" in prompt_context.get("fact_extractor", {})
        assert prompt_context["fact_extractor"]["extracted_entities"] == ["entity1", "entity2"]
        assert "metadata" in prompt_context.get("fact_extractor", {})
        assert prompt_context["fact_extractor"]["metadata"] == {"count": 2, "source": "research"}

        # Validate DROP directive
        # source is not in observe/passthrough, so it's excluded from prompt_context entirely
        assert "source" not in prompt_context
        assert "api_key" not in llm_context.get("source", {})
        assert "api_key" not in passthrough_fields

        # Validate PASSTHROUGH directive
        assert "document_id" in passthrough_fields
        assert passthrough_fields["document_id"] == "doc-123"
        assert (
            prompt_context.get("fact_extractor", {}).get("document_id") == "doc-123"
        )  # Passthrough fields available in prompt_context
        assert "document_id" not in llm_context.get("fact_extractor", {})

        # Validate prompt_context only contains scoped fields (observe + passthrough)
        # candidate_facts is NOT in observe or passthrough — excluded from prompt_context
        assert "candidate_facts" not in prompt_context.get("fact_extractor", {})

    def test_format_llm_context(self):
        """Test formatting namespaced llm_context dict as readable text."""
        llm_context = {
            "fact_extractor": {
                "extracted_entities": ["entity1", "entity2", "entity3"],
                "metadata": {"source": "research_paper", "date": "2024-01-15", "count": 3},
                "reference_id": "ref-456",
            },
        }

        result = format_llm_context(llm_context)

        assert result.startswith("Additional context:")
        assert "fact_extractor.extracted_entities:" in result
        assert "fact_extractor.metadata:" in result
        assert "fact_extractor.reference_id:" in result

    def test_seed_data_namespaced_in_prompt_context(self):
        """Seed data should be namespaced under seed for prompt context only.

        Seed is a framework namespace — always available in prompt_context
        regardless of observe/passthrough.
        """
        field_context = {"source": {"page_content": "text"}}
        context_scope = {"observe": ["source.page_content"]}
        static_data = {"exam_syllabus": {"exam_name": "Test Exam"}}

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope, static_data=static_data
        )

        assert llm_context["source"]["page_content"] == "text"
        assert prompt_context.get("seed") == static_data
        assert passthrough_fields == {}

    def test_seed_drop_does_not_affect_llm_context(self):
        """Dropping seed.* should not add seed to llm_context."""
        field_context = {"source": {"page_content": "text"}}
        context_scope = {"drop": ["seed.exam_syllabus"], "observe": ["source.page_content"]}
        static_data = {"exam_syllabus": {"exam_name": "Test Exam"}}

        _, llm_context, _ = apply_context_scope(
            field_context, context_scope, static_data=static_data
        )

        # llm_context should have observe fields but NOT seed data
        assert llm_context["source"]["page_content"] == "text"
        assert "exam_syllabus" not in llm_context.get("seed", {})

    def test_merge_passthrough_fields(self):
        """Test merging passthrough fields into LLM response."""
        # Test with structured response (with 'content' key)
        structured_response = [
            {
                "source_guid": "guid-abc-123",
                "node_id": "node_1_classifier",
                "content": {"classification": "positive", "confidence": 0.92},
            },
            {
                "source_guid": "guid-def-456",
                "node_id": "node_1_classifier",
                "content": {"classification": "negative", "confidence": 0.88},
            },
        ]

        passthrough_fields = {"document_id": "doc-123", "original_filename": "report.pdf"}

        # Execute
        result = merge_passthrough_fields(structured_response, passthrough_fields)

        # Validate - passthrough fields merged into content
        assert result[0]["content"]["classification"] == "positive"
        assert result[0]["content"]["confidence"] == 0.92
        assert result[0]["content"]["document_id"] == "doc-123"
        assert result[0]["content"]["original_filename"] == "report.pdf"

        assert result[1]["content"]["classification"] == "negative"
        assert result[1]["content"]["confidence"] == 0.88
        assert result[1]["content"]["document_id"] == "doc-123"
        assert result[1]["content"]["original_filename"] == "report.pdf"

        # Test with flat response (no 'content' key)
        flat_response = [{"classification": "positive", "confidence": 0.95}]

        flat_result = merge_passthrough_fields(flat_response, passthrough_fields)

        # Validate - passthrough fields merged directly
        assert flat_result[0]["classification"] == "positive"
        assert flat_result[0]["confidence"] == 0.95
        assert flat_result[0]["document_id"] == "doc-123"
        assert flat_result[0]["original_filename"] == "report.pdf"

        # Test with empty passthrough returns response unchanged
        unchanged = merge_passthrough_fields(structured_response, {})
        assert unchanged == structured_response

    def test_apply_context_scope_observe_wildcard(self):
        """Test wildcard expansion for observe directive in apply_context_scope."""
        field_context = {
            "action_a": {"field1": "value1", "field2": "value2", "field3": "value3"},
            "action_b": {"other_field": "other_value"},
        }
        context_scope = {"observe": ["action_a.*"]}

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # All fields from action_a should be in llm_context under namespace
        assert llm_context["action_a"]["field1"] == "value1"
        assert llm_context["action_a"]["field2"] == "value2"
        assert llm_context["action_a"]["field3"] == "value3"

        # Fields from action_b should NOT be in llm_context
        assert "action_b" not in llm_context

        # passthrough_fields should be empty
        assert passthrough_fields == {}

        # prompt_context should have only observed namespaces
        assert prompt_context["action_a"]["field1"] == "value1"
        # action_b is not in observe/passthrough — excluded from prompt_context
        assert "action_b" not in prompt_context

    def test_apply_context_scope_passthrough_wildcard(self):
        """Test wildcard expansion for passthrough directive in apply_context_scope."""
        field_context = {
            "action_a": {"field1": "value1", "field2": "value2"},
            "action_b": {"other_field": "other_value"},
        }
        context_scope = {"passthrough": ["action_a.*"]}

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # All fields from action_a should be in passthrough_fields
        assert passthrough_fields["field1"] == "value1"
        assert passthrough_fields["field2"] == "value2"

        # Fields from action_b should NOT be in passthrough_fields
        assert "other_field" not in passthrough_fields

        # llm_context should be empty
        assert llm_context == {}

    def test_apply_context_scope_mixed_wildcard_and_specific(self):
        """Test mixing wildcard and specific field references."""
        field_context = {
            "action_a": {"field1": "value1", "field2": "value2"},
            "action_b": {"field3": "value3", "field4": "value4"},
        }
        context_scope = {
            "observe": ["action_a.*"],  # Wildcard for action_a
            "passthrough": ["action_b.field3"],  # Specific field for action_b
        }

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # action_a fields should be in llm_context under namespace (wildcard)
        assert llm_context["action_a"]["field1"] == "value1"
        assert llm_context["action_a"]["field2"] == "value2"

        # Only field3 from action_b should be in passthrough_fields (specific)
        assert passthrough_fields["field3"] == "value3"
        assert "field4" not in passthrough_fields

    def test_apply_context_scope_wildcard_nonexistent_action(self):
        """Test wildcard on non-existent action returns empty."""
        field_context = {
            "action_a": {"field1": "value1"},
        }
        context_scope = {"observe": ["nonexistent_action.*"]}

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # llm_context should be empty since action doesn't exist
        assert llm_context == {}
        assert passthrough_fields == {}


class TestDependencyDeclarationEnforcement:
    """Tests that all dependencies must be declared in context_scope."""

    def test_missing_dependency_declaration_raises_error(self):
        """Test that missing dependency in context_scope raises ConfigurationError."""
        dependencies = ["dep_A", "dep_B", "dep_C"]
        context_scope = {
            "observe": ["dep_A.field1", "dep_B.field2"]
            # Missing: dep_C
        }

        with pytest.raises(ConfigurationError) as exc:
            _extract_allowed_fields_per_dependency(dependencies, context_scope, "test_action")

        assert "dep_C" in str(exc.value)
        assert "not referenced in context_scope" in str(exc.value)

    def test_all_dependencies_declared_with_wildcard(self):
        """Test that wildcard declarations work."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = {"observe": ["dep_A.*", "dep_B.*"]}

        result = _extract_allowed_fields_per_dependency(dependencies, context_scope, "test_action")

        assert result["dep_A"] is None  # Wildcard
        assert result["dep_B"] is None  # Wildcard

    def test_all_dependencies_declared_with_specific_fields(self):
        """Test that specific field declarations work."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = {
            "observe": ["dep_A.field1", "dep_A.field2"],
            "passthrough": ["dep_B.field3"],
        }

        result = _extract_allowed_fields_per_dependency(dependencies, context_scope, "test_action")

        assert set(result["dep_A"]) == {"field1", "field2"}
        assert result["dep_B"] == ["field3"]

    def test_no_context_scope_with_dependencies_raises_error(self):
        """Test that missing context_scope with dependencies raises error."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = None

        with pytest.raises(ConfigurationError) as exc:
            _extract_allowed_fields_per_dependency(dependencies, context_scope, "test_action")

        assert "no context_scope defined" in str(exc.value)


class TestNestedDictFieldResolution:
    """Tests for nested dict field resolution in context_scope."""

    def test_extract_field_value_nested_dot_path(self):
        """extract_field_value traverses nested dicts via dot-separated path."""
        field_context = {
            "action_a": {"target_word_counts": {"correct_answer_words": 8, "distractor_words": 5}}
        }
        result = extract_field_value(
            field_context, "action_a", "target_word_counts.correct_answer_words"
        )
        assert result == 8

    def test_extract_field_value_flat_key_unchanged(self):
        """Flat key lookup still works as before (backward compat)."""
        field_context = {"action_a": {"simple_field": "hello"}}
        result = extract_field_value(field_context, "action_a", "simple_field")
        assert result == "hello"

    def test_extract_field_value_literal_dotted_key_priority(self):
        """If a literal dotted key exists, it takes priority over nested traversal."""
        field_context = {
            "action_a": {
                "a.b": "literal_value",
                "a": {"b": "nested_value"},
            }
        }
        result = extract_field_value(field_context, "action_a", "a.b")
        assert result == "literal_value"

    def test_filter_and_store_fields_nested_path(self):
        """Nested path in allowed_fields loads the root key."""
        field_context = {}
        data = {"target_word_counts": {"correct_answer_words": 8}, "other": "val"}
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["target_word_counts.correct_answer_words"],
            source_type="test",
        )
        # Root key loaded so Jinja2 can traverse
        assert "target_word_counts" in field_context["action_a"]
        assert field_context["action_a"]["target_word_counts"]["correct_answer_words"] == 8
        # Unrelated keys excluded
        assert "other" not in field_context["action_a"]

    def test_filter_and_store_fields_flat_key_unchanged(self):
        """Flat key filtering still works as before."""
        field_context = {}
        data = {"field1": "val1", "field2": "val2"}
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["field1"],
            source_type="test",
        )
        assert field_context["action_a"] == {"field1": "val1"}

    def test_filter_and_store_fields_no_false_error_for_nested(self):
        """fail_on_missing should NOT raise when root key exists for nested path."""
        field_context = {}
        data = {"target_word_counts": {"correct_answer_words": 8}}
        # Should not raise — the root key exists
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["target_word_counts.correct_answer_words"],
            source_type="test",
            fail_on_missing=True,
        )
        assert "action_a" in field_context

    def test_filter_and_store_fields_raises_on_missing_field(self):
        """fail_on_missing=True raises ConfigurationError when declared fields are absent."""
        from agent_actions.errors import ConfigurationError

        field_context = {}
        data = {"existing": "value"}
        with pytest.raises(ConfigurationError, match="declared fields.*missing_field"):
            _filter_and_store_fields(
                field_context,
                "action_a",
                data,
                allowed_fields=["missing_field"],
                source_type="test",
                fail_on_missing=True,
            )

    def test_filter_and_store_fields_multiple_nested_same_root(self):
        """Multiple nested paths sharing a root key load the root once."""
        field_context = {}
        data = {
            "counts": {"a": 1, "b": 2, "c": 3},
            "other": "excluded",
        }
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["counts.a", "counts.b"],
            source_type="test",
        )
        assert field_context["action_a"]["counts"] == {"a": 1, "b": 2}
        assert "other" not in field_context["action_a"]

    def test_apply_context_scope_nested_field_observe(self):
        """End-to-end: observe with nested path populates llm_context."""
        # field_context as _filter_and_store_fields would produce after the fix:
        # only the declared subfield is stored, not the entire root object.
        field_context = {
            "suggest_distractor_counts": {
                "target_word_counts": {"correct_answer_words": 8},
            }
        }
        context_scope = {
            "observe": ["suggest_distractor_counts.target_word_counts.correct_answer_words"]
        }

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        # The nested value should be extracted into llm_context under namespace
        assert (
            llm_context["suggest_distractor_counts"]["target_word_counts.correct_answer_words"] == 8
        )
        # prompt_context should have the observed namespace with its fields
        assert "suggest_distractor_counts" in prompt_context

    def test_apply_context_scope_nested_field_passthrough(self):
        """End-to-end: passthrough with nested path populates passthrough_fields."""
        field_context = {
            "action_a": {
                "nested": {"deep_value": 42},
            }
        }
        context_scope = {"passthrough": ["action_a.nested.deep_value"]}

        prompt_context, llm_context, passthrough_fields = apply_context_scope(
            field_context, context_scope
        )

        assert passthrough_fields["nested.deep_value"] == 42
        assert llm_context == {}

    def test_nested_field_does_not_leak_siblings(self):
        """Only declared nested fields should appear — siblings must not leak."""
        field_context = {}
        data = {"user": {"name": "Alice", "ssn": "secret", "email": "a@b.com"}}
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["user.name"],
            source_type="test",
        )
        assert field_context["action_a"]["user"] == {"name": "Alice"}
        assert "ssn" not in field_context["action_a"]["user"]

    def test_nested_field_preserves_none_value(self):
        """A nested field with an explicit None value must be preserved, not dropped."""
        field_context = {}
        data = {"user": {"name": None, "ssn": "secret"}}
        _filter_and_store_fields(
            field_context,
            "action_a",
            data,
            allowed_fields=["user.name"],
            source_type="test",
        )
        assert field_context["action_a"]["user"] == {"name": None}
        assert "ssn" not in field_context["action_a"].get("user", {})


class TestFilterAndStoreFieldsMetadataCollector:
    """Tests for metadata_collector parameter in _filter_and_store_fields."""

    def test_metadata_collector_records_gap_for_filtered_fields(self):
        """When allowed_fields filters out some fields, collector records the gap."""
        field_context = {}
        collector = {}
        data = {"question_type": "MCQ", "answer_text": "42", "score": 0.9}

        _filter_and_store_fields(
            field_context,
            "classify",
            data,
            allowed_fields=["question_type"],
            source_type="TEST",
            metadata_collector=collector,
        )

        assert "classify" in collector
        meta = collector["classify"]
        assert meta["stored_fields"] == ["answer_text", "question_type", "score"]
        assert meta["loaded_fields"] == ["question_type"]
        assert meta["stored_count"] == 3
        assert meta["loaded_count"] == 1

    def test_metadata_collector_wildcard_records_all_fields(self):
        """When allowed_fields is None (wildcard), stored == loaded."""
        field_context = {}
        collector = {}
        data = {"question_type": "MCQ", "answer_text": "42"}

        _filter_and_store_fields(
            field_context,
            "classify",
            data,
            allowed_fields=None,
            source_type="TEST",
            metadata_collector=collector,
        )

        assert "classify" in collector
        meta = collector["classify"]
        assert meta["stored_fields"] == meta["loaded_fields"]
        assert meta["stored_count"] == 2
        assert meta["loaded_count"] == 2

    def test_metadata_collector_none_by_default_no_regression(self):
        """When metadata_collector is not passed (default None), behavior is unchanged."""
        field_context = {}
        data = {"question_type": "MCQ", "answer_text": "42"}

        # Should not raise or change behavior
        _filter_and_store_fields(
            field_context,
            "classify",
            data,
            allowed_fields=["question_type"],
            source_type="TEST",
        )

        assert field_context["classify"] == {"question_type": "MCQ"}
