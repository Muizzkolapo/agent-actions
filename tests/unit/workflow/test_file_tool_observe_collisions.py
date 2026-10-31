"""A FILE-granularity tool observing fields that collide across namespaces must
receive namespace-qualified keys — never a silent last-writer-wins flatten.

Enrichment already warns on collision and promises qualified keys; the tool
input must honor that promise so every observed namespace's value is delivered.
"""

import pytest

from agent_actions.prompt.context.scope_application import (
    apply_context_scope_for_records,
)
from agent_actions.workflow.pipeline_file_mode import extract_tool_input


def _enriched(record, context_scope):
    enriched, skipped = apply_context_scope_for_records(
        records=[record], context_scope=context_scope, action_name="agg"
    )
    assert not skipped
    return enriched[0]


class TestCollidingNamespacesQualify:
    def test_multi_wildcard_delivers_every_namespace(self):
        record = {
            "source_guid": "sg-1",
            "content": {
                "gen_code_1": {"code": "V1", "language": "python"},
                "gen_code_2": {"code": "V2", "language": "js"},
                "gen_code_3": {"code": "V3", "language": "rust"},
            },
        }
        cs = {"observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"]}

        business = extract_tool_input(_enriched(record, cs), cs)

        assert business["gen_code_1.code"] == "V1"
        assert business["gen_code_2.code"] == "V2"
        assert business["gen_code_3.code"] == "V3"
        assert business["gen_code_1.language"] == "python"
        assert business["gen_code_3.language"] == "rust"
        assert "code" not in business  # a bare key would hide two of three values

    @pytest.mark.parametrize(
        ("content", "observe", "expected"),
        [
            pytest.param(
                {"review_a": {"title": "A"}, "review_b": {"title": "B"}},
                ["review_a.title", "review_b.title"],
                {"review_a.title": "A", "review_b.title": "B"},
                id="specific_colliding_refs",
            ),
            # Qualification follows the declared refs, not which upstreams produced
            # output, so tool code can rely on stable key shapes.
            pytest.param(
                {"gen_code_1": {"code": "V1"}},
                ["gen_code_1.*", "gen_code_2.*"],
                {"gen_code_1.code": "V1"},
                id="declared_but_absent_wildcard_namespace",
            ),
        ],
    )
    def test_declared_collisions_qualify(self, content, observe, expected):
        record = {"content": content}
        cs = {"observe": observe}

        assert extract_tool_input(_enriched(record, cs), cs) == expected


class TestNonCollidingStayBare:
    @pytest.mark.parametrize(
        ("content", "observe", "expected"),
        [
            pytest.param(
                {"extract": {"q": "Q1", "a": "A1"}},
                ["extract.*"],
                {"q": "Q1", "a": "A1"},
                id="single_wildcard_namespace_bare",
            ),
            # Whether `extract.*` expands onto `category` is a property of the data, so
            # the only key shape stable across runs qualifies the explicit ref.
            pytest.param(
                {"extract": {"q": "Q1"}, "classify": {"category": "FAQ", "x": 1}},
                ["extract.*", "classify.category"],
                {"q": "Q1", "classify.category": "FAQ"},
                id="explicit_ref_beside_wildcard_qualified",
            ),
        ],
    )
    def test_observed_keys_follow_the_declared_refs(self, content, observe, expected):
        record = {"content": content}
        cs = {"observe": observe}

        assert extract_tool_input(_enriched(record, cs), cs) == expected

    def test_no_observe_flattens_all_namespaces(self):
        record = {"content": {"extract": {"q": "Q1"}, "classify": {"category": "FAQ"}}}

        assert extract_tool_input(record, {}) == {"q": "Q1", "category": "FAQ"}
