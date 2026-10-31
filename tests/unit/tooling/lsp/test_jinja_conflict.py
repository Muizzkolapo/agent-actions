"""Regression tests: LSP handles Jinja template syntax without false matches.

Investigation found that Jinja delimiters ({{ }}, {% %}, {# #}) do not match
any LSP reference regex because '{' is not a word character (\\w). These tests
guard against regressions if the regex patterns are ever changed.
"""

import textwrap
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from agent_actions.tooling.lsp.indexer import _index_workflow_file
from agent_actions.tooling.lsp.models import ProjectIndex, ReferenceType
from agent_actions.tooling.lsp.resolver import get_reference_at_position

# -- Helpers ------------------------------------------------------------------


def _index_yaml(tmp_path: Path, yaml_content: str) -> tuple[list, ProjectIndex]:
    """Write YAML content to a temp file, index it, return (references, index)."""
    yaml_file = tmp_path / "test.yml"
    yaml_file.write_text(yaml_content)
    index = ProjectIndex(root=tmp_path)
    _index_workflow_file(index, yaml_file, YAML(typ="safe"))
    return index.references_by_file.get(yaml_file, []), index


# -- Resolver: Jinja lines produce no references -----------------------------

_JINJA_LINES = [
    pytest.param("{% from 'macro.jinja2' import thing %}", id="import"),
    pytest.param("{% if action_name %}some content{% endif %}", id="if-block"),
    pytest.param("{% for item in items %}", id="for-loop"),
    pytest.param("{% set schema = 'review_output' %}", id="set-keyword"),
    pytest.param("{{ variable }}", id="variable"),
    pytest.param("{{ extract_details.summary }}", id="dotted-variable"),
    pytest.param("prompt: {{ variable }}", id="prompt-value"),
    pytest.param("{# this is a Jinja comment #}", id="comment"),
    pytest.param("{{ items | join(', ') }}", id="filter-chain"),
]


class TestResolverJinjaNoFalseMatches:
    """get_reference_at_position returns None for all Jinja syntax lines."""

    @pytest.mark.parametrize("content", _JINJA_LINES)
    def test_jinja_line_produces_no_reference(self, content: str):
        assert get_reference_at_position(content, 0, 0) is None


class TestResolverNonJinjaStillWorks:
    """Regular YAML references still resolve correctly (no over-suppression)."""

    def test_prompt_reference(self):
        ref = get_reference_at_position("prompt: $my_workflow.MyPrompt", 0, 12)
        assert ref is not None
        assert ref.type == ReferenceType.PROMPT
        assert ref.value == "my_workflow.MyPrompt"

    def test_schema_reference(self):
        ref = get_reference_at_position("schema: review_output", 0, 10)
        assert ref is not None
        assert ref.type == ReferenceType.SCHEMA
        assert ref.value == "review_output"

    def test_impl_reference(self):
        ref = get_reference_at_position("impl: my_tool_function", 0, 8)
        assert ref is not None
        assert ref.type == ReferenceType.TOOL
        assert ref.value == "my_tool_function"

    def test_seed_file_reference(self):
        ref = get_reference_at_position("seed: $file:data/lookup.json", 0, 14)
        assert ref is not None
        assert ref.type == ReferenceType.SEED_FILE
        assert ref.value == "data/lookup.json"


class TestResolverMixedContent:
    """File with both Jinja and plain YAML: only plain lines produce references."""

    def test_mixed_jinja_and_yaml_lines(self):
        content = "\n".join(
            [
                "prompt: $wf.Prompt",
                "{% if version.first %}",
                "{{ extract_details.summary }}",
                "schema: my_schema",
            ]
        )

        ref0 = get_reference_at_position(content, 0, 12)
        assert ref0 is not None
        assert ref0.type == ReferenceType.PROMPT

        # Jinja lines — no reference
        assert get_reference_at_position(content, 1, 0) is None
        assert get_reference_at_position(content, 2, 0) is None

        ref3 = get_reference_at_position(content, 3, 10)
        assert ref3 is not None
        assert ref3.type == ReferenceType.SCHEMA


# -- Indexer: Jinja in prompt blocks produces no false references -------------


class TestIndexerJinjaNoFalseReferences:
    """Indexer does not produce false references from Jinja content in prompt blocks."""

    def test_jinja_in_prompt_block(self, tmp_path):
        """Jinja inside prompt: | block — only the real schema ref is indexed."""
        refs, _ = _index_yaml(
            tmp_path,
            textwrap.dedent("""\
                actions:
                  - name: classify
                    prompt: |
                      You are classifier {{ i }} of {{ version.length }}.
                      {% if version.first %}Be conservative.{% endif %}
                      {% if version.last %}Be comprehensive.{% endif %}
                      Classify: {{ extract_details.summary }}
                    schema: my_schema
            """),
        )

        schema_refs = [r for r in refs if r.type == ReferenceType.SCHEMA]
        assert len(schema_refs) == 1
        assert schema_refs[0].value == "my_schema"

        for ref in refs:
            assert "version" not in ref.value
            assert "extract_details" not in ref.value

    def test_version_conditionals_in_prompt(self, tmp_path):
        """Real versioned_classifier pattern — only dependency + schema indexed."""
        refs, _ = _index_yaml(
            tmp_path,
            textwrap.dedent("""\
                actions:
                  - name: classify
                    dependencies:
                      - extract_details
                    prompt: |
                      You are classifier {{ i }} of {{ version.length }}.
                      {% if version.first %}Be conservative in your assessment.{% endif %}
                      {% if version.last %}Be comprehensive in your assessment.{% endif %}
                      Classifier ID: {{ classifier_id }}
                      Based on the extracted details:
                      {{ extract_details.summary }}
                      Classify the content.
                    schema: my_schema
            """),
        )

        ref_pairs = [(r.type, r.value) for r in refs]
        assert (ReferenceType.ACTION, "extract_details") in ref_pairs
        assert (ReferenceType.SCHEMA, "my_schema") in ref_pairs
        assert len(refs) == 2

    def test_top_level_jinja_file_gracefully_skipped(self, tmp_path):
        """Top-level Jinja blocks cause YAML parse failure — no crash, no refs."""
        refs, _ = _index_yaml(
            tmp_path,
            "{% from 'macros.jinja2' import quality_check %}\nactions:\n  - name: test\n",
        )
        assert len(refs) == 0

    def test_jinja_filters_in_prompt(self, tmp_path):
        """Jinja filters (| join) in prompt — only schema ref indexed."""
        refs, _ = _index_yaml(
            tmp_path,
            textwrap.dedent("""\
                actions:
                  - name: summarize
                    prompt: |
                      Entities: {{ extracted_data.entities | join(', ') }}
                      Topics: {{ topics | join(', ') }}
                      Text: {{ raw_text }}
                    schema: summary_schema
            """),
        )

        assert len(refs) == 1
        assert refs[0].type == ReferenceType.SCHEMA
        assert refs[0].value == "summary_schema"
