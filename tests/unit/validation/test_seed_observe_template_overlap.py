"""Warn when a seed field is both observed and referenced in the prompt template.

Seed data is always available to Jinja templates. Observing the same seed field
additionally injects it into the LLM context message, so the blob reaches the
model twice. The static analyzer must surface the overlap.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _workflow(prompt, observe):
    return {
        "name": "wf",
        "actions": [
            {
                "name": "author",
                "prompt": prompt,
                "schema": {
                    "type": "object",
                    "properties": {"out": {"type": "string"}},
                },
                "context_scope": {"observe": observe},
            }
        ],
    }


def _overlap_warnings(result):
    return [w.message for w in result.warnings if "seed" in w.message and "twice" in w.message]


class TestSeedObserveTemplateOverlap:
    def test_observed_and_templated_seed_field_warns(self):
        wf = _workflow(
            "Rules: {{ seed.rules }}\nText: {{ source.text }}",
            ["source.text", "seed.rules"],
        )
        result = WorkflowStaticAnalyzer(wf).analyze()

        warnings = _overlap_warnings(result)
        assert len(warnings) == 1
        assert "rules" in warnings[0]
        assert "author" in warnings[0]

    def test_observe_only_no_warning(self):
        wf = _workflow(
            "Text: {{ source.text }}",
            ["source.text", "seed.rules"],
        )
        result = WorkflowStaticAnalyzer(wf).analyze()
        assert _overlap_warnings(result) == []

    def test_template_only_no_warning(self):
        wf = _workflow(
            "Rules: {{ seed.rules }}\nText: {{ source.text }}",
            ["source.text"],
        )
        result = WorkflowStaticAnalyzer(wf).analyze()
        assert _overlap_warnings(result) == []

    def test_wildcard_seed_observe_with_template_ref_warns(self):
        wf = _workflow(
            "Rules: {{ seed.rules }}\nText: {{ source.text }}",
            ["source.text", "seed.*"],
        )
        result = WorkflowStaticAnalyzer(wf).analyze()

        warnings = _overlap_warnings(result)
        assert len(warnings) == 1
        assert "rules" in warnings[0]

    def test_distinct_seed_fields_no_warning(self):
        wf = _workflow(
            "Rules: {{ seed.rules }}",
            ["source.text", "seed.examples"],
        )
        result = WorkflowStaticAnalyzer(wf).analyze()
        assert _overlap_warnings(result) == []
