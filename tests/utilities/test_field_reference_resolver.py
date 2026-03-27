"""
Unit tests for the field_resolution module.

Tests cover:
- Reference parsing (selector, template, Jinja formats)
- Value resolution (simple, nested, array access)
- Text substitution
- Dependency validation
- Evaluation context building
"""

import pytest

from agent_actions.input.preprocessing.field_resolution import (
    DependencyValidationError,
    EvaluationContext,
    EvaluationContextProvider,
    FieldReferenceResolver,
    InvalidReferenceError,
    ReferenceFormat,
    ReferenceNotFoundError,
    ReferenceParser,
    ReferenceValidator,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def resolver():
    """Create a default resolver instance."""
    return FieldReferenceResolver()


@pytest.fixture
def strict_resolver():
    """Create a strict mode resolver instance."""
    return FieldReferenceResolver(strict_mode=True)


@pytest.fixture
def parser():
    """Create a parser instance."""
    return ReferenceParser()


@pytest.fixture
def validator():
    """Create a validator instance."""
    return ReferenceValidator(strict_dependencies=True)


@pytest.fixture
def field_context():
    """Sample field context with various data types."""
    return {
        "extract_facts": {
            "facts": [{"name": "fact1"}, {"name": "fact2"}],
            "count": 2,
            "response": {"data": {"status": "success", "items": [1, 2, 3]}},
        },
        "source": {
            "title": "Test Document",
            "content": "Sample content",
            "metadata": {"type": "pdf", "pages": 10},
        },
        "classifier": {"category": "technical", "confidence": 0.95},
    }


@pytest.fixture
def agent_indices():
    """Sample agent indices for validation tests."""
    return {"extract_facts": 0, "classifier": 1, "filter_action": 2, "final_action": 3}


# =============================================================================
# ReferenceParser Tests
# =============================================================================


class TestReferenceParser:
    """Tests for the ReferenceParser class."""

    def test_parse_simple_selector(self, parser):
        """Test parsing simple action.field selector."""
        ref = parser.parse("extract_facts.count")

        assert ref.action_name == "extract_facts"
        assert ref.field_path == ["count"]
        assert ref.full_reference == "extract_facts.count"
        assert not ref.is_nested

    def test_parse_nested_path(self, parser):
        """Test parsing nested path like action.response.data.status."""
        ref = parser.parse("extract_facts.response.data.status")

        assert ref.action_name == "extract_facts"
        assert ref.field_path == ["response", "data", "status"]
        assert ref.is_nested
        assert ref.field_name == "response"

    def test_parse_template_format(self, parser):
        """Test parsing {action.field} template format."""
        ref = parser.parse("{source.title}")

        assert ref.action_name == "source"
        assert ref.field_path == ["title"]
        assert ref.format_type == ReferenceFormat.TEMPLATE

    def test_parse_jinja_format(self, parser):
        """Test parsing {{ action.field }} Jinja format."""
        ref = parser.parse("{{ source.title }}")

        assert ref.action_name == "source"
        assert ref.field_path == ["title"]
        assert ref.format_type == ReferenceFormat.JINJA

    def test_parse_batch_finds_all_references(self, parser):
        """Test extracting multiple references from text."""
        text = "Found {extract_facts.count} facts in {source.title}"
        refs = parser.parse_batch(text)

        assert len(refs) == 2
        action_names = [r.action_name for r in refs]
        assert "extract_facts" in action_names
        assert "source" in action_names

    def test_parse_batch_selector_format(self, parser):
        """Test extracting selector-style references from guard conditions."""
        text = "extract_facts.count > 5 AND source.metadata.type == 'pdf'"
        refs = parser.parse_batch(text, format_hint=ReferenceFormat.SELECTOR)

        assert len(refs) == 2
        # Check that nested paths are captured
        paths = [".".join(r.field_path) for r in refs]
        assert "count" in paths
        assert "metadata.type" in paths

    def test_parse_invalid_reference_non_strict(self, parser):
        """Test that invalid references return None in non-strict mode (K-3)."""
        # Missing dot - parse() returns None instead of a fallback reference
        ref = parser.parse("invalid", strict=False)
        assert ref is None

    def test_parse_invalid_reference_strict(self, parser):
        """Test that invalid references raise in strict mode."""
        with pytest.raises(InvalidReferenceError):
            parser.parse("invalid_no_dot", strict=True)


# =============================================================================
# FieldReferenceResolver Tests
# =============================================================================


class TestFieldReferenceResolver:
    """Tests for the FieldReferenceResolver class."""

    def test_resolve_simple_field(self, resolver, field_context):
        """Test resolving a simple field reference."""
        result = resolver.resolve("extract_facts.count", field_context)

        assert result.success
        assert result.value == 2
        assert result.source_action == "extract_facts"

    def test_resolve_nested_path(self, resolver, field_context):
        """Test resolving a nested path reference."""
        result = resolver.resolve("extract_facts.response.data.status", field_context)

        assert result.success
        assert result.value == "success"

    def test_resolve_array_element(self, resolver, field_context):
        """Test resolving array element by index."""
        result = resolver.resolve("extract_facts.facts.0.name", field_context)

        assert result.success
        assert result.value == "fact1"

    def test_resolve_missing_action(self, resolver, field_context):
        """Test resolving reference to non-existent action."""
        result = resolver.resolve("nonexistent.field", field_context)

        assert not result.success
        assert result.value is None
        assert "not found" in result.error

    def test_resolve_with_fallback(self, resolver, field_context):
        """Test fallback value for missing reference."""
        result = resolver.resolve("missing.field", field_context, fallback_value="default")

        assert not result.success
        assert result.value == "default"

    def test_resolve_strict_mode_raises(self, strict_resolver, field_context):
        """Test that strict mode raises on missing reference."""
        with pytest.raises(ReferenceNotFoundError):
            strict_resolver.resolve("nonexistent.field", field_context)

    def test_substitute_single_reference(self, resolver, field_context):
        """Test substituting a single reference in text."""
        text = "Found {extract_facts.count} facts"
        result = resolver.substitute(text, field_context)

        assert result == "Found 2 facts"

    def test_substitute_multiple_references(self, resolver, field_context):
        """Test substituting multiple references in text."""
        text = "{source.title} has {extract_facts.count} facts"
        result = resolver.substitute(text, field_context)

        assert result == "Test Document has 2 facts"

    def test_substitute_nested_reference(self, resolver, field_context):
        """Test substituting nested reference in text."""
        text = "Status: {extract_facts.response.data.status}"
        result = resolver.substitute(text, field_context)

        assert result == "Status: success"

    def test_parse_batch_via_resolver(self, resolver):
        """Test batch parsing through resolver."""
        text = "extract.count > 5 AND source.type == 'doc'"
        refs = resolver.parse_batch(text)

        assert len(refs) == 2


# =============================================================================
# ReferenceValidator Tests
# =============================================================================


class TestReferenceValidator:
    """Tests for the ReferenceValidator class."""

    def test_validate_valid_reference(self, validator, agent_indices):
        """Test validation passes for valid upstream reference."""
        agent_config = {
            "agent_type": "filter_action",
            "dependencies": ["extract_facts", "classifier"],
        }

        errors = validator.validate(
            references=["extract_facts.count", "classifier.category"],
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name="filter_action",
        )

        assert len(errors) == 0

    def test_validate_missing_action(self, validator, agent_indices):
        """Test validation fails for non-existent action."""
        agent_config = {"agent_type": "filter_action", "dependencies": ["extract_facts"]}

        errors = validator.validate(
            references=["nonexistent.field"],
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name="filter_action",
        )

        assert len(errors) == 1
        assert "not found in workflow" in errors[0]

    def test_validate_not_upstream(self, validator, agent_indices):
        """Test validation fails for non-upstream action."""
        agent_config = {
            "agent_type": "extract_facts",  # First action
            "dependencies": [],
        }

        errors = validator.validate(
            references=["final_action.result"],  # Later action
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name="extract_facts",
        )

        assert len(errors) == 1
        assert "not upstream" in errors[0]

    def test_validate_not_in_dependencies(self, validator, agent_indices):
        """Test validation fails when action not in declared dependencies."""
        agent_config = {
            "agent_type": "final_action",
            "dependencies": ["filter_action"],  # extract_facts not declared
        }

        errors = validator.validate(
            references=["extract_facts.count"],  # Not in dependencies
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name="final_action",
        )

        assert len(errors) == 1
        assert "not in dependencies" in errors[0]

    def test_validate_strict_raises_exception(self, validator, agent_indices):
        """Test validate_strict raises on errors."""
        agent_config = {"agent_type": "filter_action", "dependencies": []}

        with pytest.raises(DependencyValidationError):
            validator.validate_strict(
                references=["nonexistent.field"],
                agent_config=agent_config,
                agent_indices=agent_indices,
                current_agent_name="filter_action",
            )

    def test_extract_and_validate(self, validator, agent_indices):
        """Test extracting and validating from guard condition."""
        agent_config = {"agent_type": "filter_action", "dependencies": ["extract_facts"]}

        errors = validator.extract_and_validate(
            guard_condition="extract_facts.count > 5 AND source.type == 'pdf'",
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name="filter_action",
        )

        # source is a special namespace, so no errors
        assert len(errors) == 0

    def test_get_referenced_actions(self, validator):
        """Test extracting action names from guard condition."""
        actions = validator.get_referenced_actions(
            "extract_facts.count > 5 AND classifier.category == 'tech'"
        )

        assert "extract_facts" in actions
        assert "classifier" in actions
        assert "source" not in actions  # Special namespace excluded


# =============================================================================
# EvaluationContext Tests
# =============================================================================


class TestEvaluationContext:
    """Tests for the EvaluationContext dataclass."""

    def test_to_flat_dict(self):
        """Test converting context to flat dict."""
        context = EvaluationContext(
            current_content={"current_field": "value"},
            field_context={"extract_facts": {"count": 5}, "source": {"title": "Test"}},
        )

        flat = context.to_flat_dict()

        assert flat["current_field"] == "value"
        assert flat["extract_facts"]["count"] == 5
        assert flat["source"]["title"] == "Test"

    def test_get_field_value(self):
        """Test getting field value from context."""
        context = EvaluationContext(
            current_content={}, field_context={"extract_facts": {"count": 5, "status": "done"}}
        )

        assert context.get_field_value("extract_facts", "count") == 5
        assert context.get_field_value("extract_facts", "status") == "done"
        assert context.get_field_value("extract_facts", "missing") is None
        assert context.get_field_value("missing", "field") is None

    def test_has_action(self):
        """Test checking action existence."""
        context = EvaluationContext(
            current_content={}, field_context={"extract_facts": {"count": 5}}
        )

        assert context.has_action("extract_facts")
        assert not context.has_action("missing_action")


# =============================================================================
# EvaluationContextProvider Tests
# =============================================================================


class TestEvaluationContextProvider:
    """Tests for the EvaluationContextProvider class."""

    def test_build_minimal_context(self):
        """Test building minimal context without historical loading."""
        provider = EvaluationContextProvider()

        context = provider.build_minimal_context(
            current_content={"status": "active"}, upstream_data={"extract_facts": {"count": 10}}
        )

        assert context.current_content["status"] == "active"
        assert context.get_field_value("extract_facts", "count") == 10

    def test_to_flat_dict_merges_correctly(self):
        """Test that to_flat_dict properly merges contexts."""
        provider = EvaluationContextProvider()

        context = provider.build_minimal_context(
            current_content={"status": "active", "type": "doc"},
            upstream_data={"extract": {"count": 5}, "source": {"title": "My Doc"}},
        )

        flat = context.to_flat_dict()

        # Current content should be at top level
        assert flat["status"] == "active"
        assert flat["type"] == "doc"

        # Upstream data should be under action names
        assert flat["extract"]["count"] == 5
        assert flat["source"]["title"] == "My Doc"


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_guard_evaluation_flow(self, field_context):
        """Test complete flow from parsing to resolution."""
        resolver = FieldReferenceResolver()

        # Simulate a guard condition
        guard_condition = "extract_facts.count > 1 AND classifier.confidence > 0.9"

        # Parse references
        refs = resolver.parse_batch(guard_condition)
        assert len(refs) == 2

        # Resolve all references
        results = resolver.resolve_batch(refs, field_context)

        # Check resolved values
        for ref_str, result in results.items():
            assert result.success, f"Failed to resolve: {ref_str}"

        # Verify actual values
        count_result = resolver.resolve("extract_facts.count", field_context)
        assert count_result.value == 2

        confidence_result = resolver.resolve("classifier.confidence", field_context)
        assert confidence_result.value == 0.95

    def test_context_provider_with_resolver(self, field_context):
        """Test using context provider with resolver."""
        provider = EvaluationContextProvider()
        _resolver = FieldReferenceResolver()

        # Build context
        context = provider.build_minimal_context(
            current_content={"local_field": "local_value"}, upstream_data=field_context
        )

        # Get flat dict for evaluation
        eval_data = context.to_flat_dict()

        # Resolve references against flat dict
        # The flat dict should enable "extract_facts.count" style access
        assert eval_data["extract_facts"]["count"] == 2
        assert eval_data["source"]["title"] == "Test Document"
        assert eval_data["local_field"] == "local_value"
