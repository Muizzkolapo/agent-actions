"""Tests for ContextScopeProcessor utility class."""

import pytest
from agent_actions.prompt.context.scope import ContextScopeProcessor
from agent_actions.errors import ConfigurationError


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
        prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
            field_context, context_scope
        )

        # Validate OBSERVE directive
        assert "extracted_entities" in llm_context
        assert llm_context["extracted_entities"] == ["entity1", "entity2"]
        assert "metadata" in llm_context
        assert llm_context["metadata"] == {"count": 2, "source": "research"}
        # Observed fields should REMAIN in prompt_context for template rendering
        assert "extracted_entities" in prompt_context.get("fact_extractor", {})
        assert prompt_context["fact_extractor"]["extracted_entities"] == ["entity1", "entity2"]
        assert "metadata" in prompt_context.get("fact_extractor", {})
        assert prompt_context["fact_extractor"]["metadata"] == {"count": 2, "source": "research"}

        # Validate DROP directive
        assert "api_key" not in prompt_context.get("source", {})
        assert "api_key" not in llm_context
        assert "api_key" not in passthrough_fields
        assert "page_content" in prompt_context.get("source", {})  # Other fields remain

        # Validate PASSTHROUGH directive
        assert "document_id" in passthrough_fields
        assert passthrough_fields["document_id"] == "doc-123"
        assert (
            prompt_context.get("fact_extractor", {}).get("document_id") == "doc-123"
        )  # Now available in prompt_context!
        assert "document_id" not in llm_context

        # Validate fields NOT in any directive remain in prompt_context
        assert "candidate_facts" in prompt_context.get("fact_extractor", {})
        assert prompt_context["fact_extractor"]["candidate_facts"] == ["fact1", "fact2"]

    def test_format_llm_context(self):
        """Test formatting llm_context dict as readable text."""
        # Setup
        llm_context = {
            "extracted_entities": ["entity1", "entity2", "entity3"],
            "metadata": {"source": "research_paper", "date": "2024-01-15", "count": 3},
            "reference_id": "ref-456",
        }

        # Execute
        result = ContextScopeProcessor.format_llm_context(llm_context)

        # Validate
        assert result.startswith("Additional context:")
        assert "extracted_entities:" in result
        assert "metadata:" in result
        assert "reference_id:" in result

    def test_seed_data_namespaced_in_prompt_context(self):
        """Seed data should be namespaced under seed for prompt context only."""
        field_context = {"source": {"page_content": "text"}}
        context_scope = {}
        static_data = {"exam_syllabus": {"exam_name": "Test Exam"}}

        prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
            field_context, context_scope, static_data=static_data
        )

        assert llm_context == {}
        assert prompt_context.get("seed") == static_data
        assert passthrough_fields == {}

    def test_seed_drop_does_not_affect_llm_context(self):
        """Dropping seed.* should not add seed to llm_context."""
        field_context = {"source": {"page_content": "text"}}
        context_scope = {"drop": ["seed.exam_syllabus"]}
        static_data = {"exam_syllabus": {"exam_name": "Test Exam"}}

        _, llm_context, _ = ContextScopeProcessor.apply_context_scope(
            field_context, context_scope, static_data=static_data
        )

        assert llm_context == {}

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
        result = ContextScopeProcessor.merge_passthrough_fields(
            structured_response, passthrough_fields
        )

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

        flat_result = ContextScopeProcessor.merge_passthrough_fields(
            flat_response, passthrough_fields
        )

        # Validate - passthrough fields merged directly
        assert flat_result[0]["classification"] == "positive"
        assert flat_result[0]["confidence"] == 0.95
        assert flat_result[0]["document_id"] == "doc-123"
        assert flat_result[0]["original_filename"] == "report.pdf"

        # Test with empty passthrough returns response unchanged
        unchanged = ContextScopeProcessor.merge_passthrough_fields(structured_response, {})
        assert unchanged == structured_response

    def test_realtime_mode_progressive_exposure_wildcard(self):
        """Test realtime mode with wildcard (all fields from dependency)."""
        contents = {
            "question": "What is MCP?",
            "options": ["A", "B", "C", "D"],
            "answer": "A",
            "answer_text": ["Model Context Protocol"],
            "extra_field": "unused",
        }

        agent_config = {"dependencies": ["add_answer_text"]}
        context_scope = {"observe": ["add_answer_text.*"]}

        # Realtime mode: no current_item, file_path, or agent_indices
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents,
            agent_name="generate_distractor",
            agent_config=agent_config,
            context_scope=context_scope,
        )

        # Should load all fields from contents into dependency namespace
        assert "add_answer_text" in field_context
        assert field_context["add_answer_text"]["question"] == "What is MCP?"
        assert field_context["add_answer_text"]["answer_text"] == ["Model Context Protocol"]
        assert field_context["add_answer_text"]["extra_field"] == "unused"
        assert len(field_context["add_answer_text"]) == 5  # All fields

    def test_realtime_mode_progressive_exposure_specific_fields(self):
        """Test realtime mode with specific fields (progressive exposure)."""
        contents = {
            "question": "What is MCP?",
            "options": ["A", "B", "C", "D"],
            "answer": "A",
            "answer_text": ["Model Context Protocol"],
            "target_word_counts": {"distractor_1": 10},
        }

        agent_config = {"dependencies": ["add_answer_text"]}
        context_scope = {
            "observe": ["add_answer_text.answer_text"],
            "passthrough": ["add_answer_text.question"],
        }

        # Realtime mode: no current_item, file_path, or agent_indices
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents,
            agent_name="generate_distractor",
            agent_config=agent_config,
            context_scope=context_scope,
        )

        # Should load ONLY declared fields
        assert "add_answer_text" in field_context
        assert field_context["add_answer_text"]["answer_text"] == ["Model Context Protocol"]
        assert field_context["add_answer_text"]["question"] == "What is MCP?"

        # Undeclared fields should NOT be in field_context
        assert "options" not in field_context["add_answer_text"]
        assert "answer" not in field_context["add_answer_text"]
        assert "target_word_counts" not in field_context["add_answer_text"]

        # Only 2 fields loaded (progressive exposure working!)
        assert len(field_context["add_answer_text"]) == 2


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
            ContextScopeProcessor._extract_allowed_fields_per_dependency(
                dependencies, context_scope, "test_action"
            )

        assert "dep_C" in str(exc.value)
        assert "not referenced in context_scope" in str(exc.value)

    def test_all_dependencies_declared_with_wildcard(self):
        """Test that wildcard declarations work."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = {"observe": ["dep_A.*", "dep_B.*"]}

        result = ContextScopeProcessor._extract_allowed_fields_per_dependency(
            dependencies, context_scope, "test_action"
        )

        assert result["dep_A"] is None  # Wildcard
        assert result["dep_B"] is None  # Wildcard

    def test_all_dependencies_declared_with_specific_fields(self):
        """Test that specific field declarations work."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = {
            "observe": ["dep_A.field1", "dep_A.field2"],
            "passthrough": ["dep_B.field3"],
        }

        result = ContextScopeProcessor._extract_allowed_fields_per_dependency(
            dependencies, context_scope, "test_action"
        )

        assert set(result["dep_A"]) == {"field1", "field2"}
        assert result["dep_B"] == ["field3"]

    def test_no_context_scope_with_dependencies_raises_error(self):
        """Test that missing context_scope with dependencies raises error."""
        dependencies = ["dep_A", "dep_B"]
        context_scope = None

        with pytest.raises(ConfigurationError) as exc:
            ContextScopeProcessor._extract_allowed_fields_per_dependency(
                dependencies, context_scope, "test_action"
            )

        assert "no context_scope defined" in str(exc.value)
