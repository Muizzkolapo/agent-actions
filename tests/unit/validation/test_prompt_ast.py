"""Tests for PromptASTAnalyzer full path extraction."""

import pytest

from agent_actions.validation.prompt_ast import (
    PromptASTAnalyzer,
    scan_prompt_fields_ast,
    validate_prompt_fields_ast,
)


class TestExtractVariables:
    """Tests for extract_variables method."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return PromptASTAnalyzer()

    def test_extracts_nested_attribute_path(self, analyzer):
        """Should extract full nested attribute path."""
        template = "{{ seed.exam_syllabus.platform_name }}"

        result = analyzer.extract_variables(template)

        assert result == {"seed.exam_syllabus.platform_name"}

    def test_extracts_single_level_attribute(self, analyzer):
        """Should extract single-level attribute access."""
        template = "{{ source.url }}"

        result = analyzer.extract_variables(template)

        assert result == {"source.url"}

    def test_extracts_standalone_variable(self, analyzer):
        """Should extract standalone variables without attributes."""
        template = "{{ seed }}"

        result = analyzer.extract_variables(template)

        assert result == {"seed"}

    def test_extracts_multiple_variables(self, analyzer):
        """Should extract all variables from template."""
        template = """
        Extract facts about {{ seed.exam_syllabus.platform_name }}
        {% if source.url %}
        Source: {{ source.url }}
        {% endif %}
        """

        result = analyzer.extract_variables(template)

        assert result == {"seed.exam_syllabus.platform_name", "source.url"}

    def test_extracts_bracket_notation(self, analyzer):
        """Should handle bracket notation access."""
        template = '{{ data["key"] }}'

        result = analyzer.extract_variables(template)

        assert result == {'data["key"]'}

    def test_extracts_mixed_bracket_and_dot(self, analyzer):
        """Should handle mixed bracket and dot notation."""
        template = "{{ items[0].name }}"

        result = analyzer.extract_variables(template)

        assert result == {"items[0].name"}

    def test_extracts_from_if_blocks(self, analyzer):
        """Should extract variables from control flow blocks."""
        template = "{% if target.ready %}ready{% endif %}"

        result = analyzer.extract_variables(template)

        assert result == {"target.ready"}

    def test_extracts_from_for_loops(self, analyzer):
        """Should extract source variable from for loops."""
        template = "{% for item in items.list %}{{ item.name }}{% endfor %}"

        result = analyzer.extract_variables(template)

        # 'item' is loop variable (declared), 'items.list' is source
        assert "items.list" in result

    def test_excludes_loop_variables(self, analyzer):
        """Should exclude declared loop variables from results."""
        template = "{% for item in items.list %}{{ item.name }}{% endfor %}"

        result = analyzer.extract_variables(template)

        # Loop variable 'item' should NOT appear as a required reference
        assert "item" not in result
        assert "item.name" not in result
        # But the source should be included
        assert result == {"items.list"}

    def test_excludes_set_variables(self, analyzer):
        """Should exclude variables declared with set."""
        template = "{% set x = seed.value %}{{ x }}"

        result = analyzer.extract_variables(template)

        # 'x' is declared via set, should NOT appear
        assert "x" not in result
        # But the source should be included
        assert result == {"seed.value"}

    def test_preserves_both_parent_and_child_paths(self, analyzer):
        """Should keep both paths when parent and child are explicitly used."""
        template = "{{ seed.exam }} and {{ seed.exam.field }}"

        result = analyzer.extract_variables(template)

        # Both explicitly referenced paths should be present
        assert "seed.exam" in result
        assert "seed.exam.field" in result
        assert len(result) == 2

    def test_handles_dynamic_keys(self, analyzer):
        """Should represent dynamic keys as [*] and include index variable."""
        template = "{{ items[i].name }}"

        result = analyzer.extract_variables(template)

        # Dynamic key represented as [*], index variable 'i' is also a reference
        assert "items[*].name" in result
        assert "i" in result

    def test_raises_on_syntax_error(self, analyzer):
        """Should raise ValueError on invalid template syntax."""
        template = "{{ field"

        with pytest.raises(ValueError, match="Template syntax error"):
            analyzer.extract_variables(template)


class TestExtractReferencedVariables:
    """Tests for extract_referenced_variables method."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return PromptASTAnalyzer()

    def test_returns_roots_and_paths(self, analyzer):
        """Should return both root variables and full paths."""
        template = "{{ seed.exam_syllabus }} and {{ source.content }}"

        roots, paths = analyzer.extract_referenced_variables(template)

        assert sorted(roots) == ["seed", "source"]
        assert sorted(paths) == ["seed.exam_syllabus", "source.content"]

    def test_handles_bracket_notation_roots(self, analyzer):
        """Should extract root from bracket notation paths."""
        template = '{{ data["key"] }}'

        roots, paths = analyzer.extract_referenced_variables(template)

        assert roots == {"data"}
        assert paths == {'data["key"]'}


class TestAnalyzeFieldRequirements:
    """Tests for analyze_field_requirements method."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return PromptASTAnalyzer()

    def test_detects_missing_root_reference(self, analyzer):
        """Should detect when root variable is not in context."""
        template = "{{ seed.exam }} and {{ missing.field }}"
        context = {"seed": {"exam"}}

        result = analyzer.analyze_field_requirements(template, context)

        assert "missing" in result["missing_references"]
        assert result["is_valid"] is False

    def test_detects_missing_nested_field(self, analyzer):
        """Should detect when nested field doesn't exist."""
        template = "{{ seed.exam }}"
        context = {"seed": {"exam_syllabus", "other_field"}}

        result = analyzer.analyze_field_requirements(template, context)

        assert len(result["missing_fields"]) == 1
        assert result["missing_fields"][0]["field"] == "exam"
        assert result["missing_fields"][0]["full_path"] == "seed.exam"
        assert result["is_valid"] is False

    def test_validates_correct_fields(self, analyzer):
        """Should pass when all fields exist."""
        template = "{{ seed.exam_syllabus }} and {{ source.content }}"
        context = {"seed": {"exam_syllabus"}, "source": {"content"}}

        result = analyzer.analyze_field_requirements(template, context)

        assert result["missing_references"] == []
        assert result["missing_fields"] == []
        assert result["is_valid"] is True

    def test_returns_required_paths(self, analyzer):
        """Should include full paths in result."""
        template = "{{ seed.exam_syllabus.platform_name }}"
        context = {"seed": {"exam_syllabus"}}

        result = analyzer.analyze_field_requirements(template, context)

        assert "seed.exam_syllabus.platform_name" in result["required_paths"]


class TestScanPromptFieldsAst:
    """Tests for scan_prompt_fields_ast utility function."""

    def test_extracts_full_paths(self):
        """Should extract full attribute paths."""
        template = "{{ seed.exam }} and {{ source.data }}"

        result = scan_prompt_fields_ast(template)

        assert sorted(result) == ["seed.exam", "source.data"]


class TestValidatePromptFieldsAst:
    """Tests for validate_prompt_fields_ast utility function."""

    def test_validates_correct_fields(self):
        """Should return valid when all fields exist."""
        template = "{{ seed.exam }} and {{ source.content }}"
        context = {"seed": {"exam"}, "source": {"content"}}

        valid, errors = validate_prompt_fields_ast(template, context)

        assert valid is True
        assert errors == []

    def test_returns_errors_for_missing_reference(self):
        """Should return error for missing root reference."""
        template = "{{ seed.exam }} and {{ source.content }}"
        context = {"seed": {"exam"}}

        valid, errors = validate_prompt_fields_ast(template, context)

        assert valid is False
        assert len(errors) == 1
        assert "Missing reference: 'source'" in errors[0]

    def test_returns_errors_for_missing_field(self):
        """Should return error for missing nested field."""
        template = "{{ seed.exam }}"
        context = {"seed": {"exam_syllabus"}}

        valid, errors = validate_prompt_fields_ast(template, context)

        assert valid is False
        assert len(errors) == 1
        assert "Missing field: 'exam'" in errors[0]
