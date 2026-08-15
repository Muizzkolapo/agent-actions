"""A FILE-granularity tool observing fields that collide across namespaces must
receive namespace-qualified keys — never a silent last-writer-wins flatten.

Enrichment already warns on collision and promises qualified keys; the tool
input must honor that promise so every observed namespace's value is delivered.
"""

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

    def test_specific_colliding_refs_qualify(self):
        record = {"content": {"review_a": {"title": "A"}, "review_b": {"title": "B"}}}
        cs = {"observe": ["review_a.title", "review_b.title"]}

        business = extract_tool_input(_enriched(record, cs), cs)

        assert business == {"review_a.title": "A", "review_b.title": "B"}

    def test_declared_but_absent_wildcard_namespace_still_qualifies(self):
        """Qualification follows the declared refs, not which upstreams produced
        output — tool code must be able to rely on stable key shapes."""
        record = {"content": {"gen_code_1": {"code": "V1"}}}
        cs = {"observe": ["gen_code_1.*", "gen_code_2.*"]}

        business = extract_tool_input(_enriched(record, cs), cs)

        assert business == {"gen_code_1.code": "V1"}


class TestNonCollidingStayBare:
    def test_single_wildcard_namespace_bare_keys(self):
        record = {"content": {"extract": {"q": "Q1", "a": "A1"}}}
        cs = {"observe": ["extract.*"]}

        assert extract_tool_input(_enriched(record, cs), cs) == {"q": "Q1", "a": "A1"}

    def test_explicit_ref_is_qualified_when_a_wildcard_could_reach_it(self):
        """Whether `extract.*` expands onto `category` is a property of the data,
        so the only key shape stable across runs qualifies the explicit ref."""
        record = {"content": {"extract": {"q": "Q1"}, "classify": {"category": "FAQ", "x": 1}}}
        cs = {"observe": ["extract.*", "classify.category"]}

        business = extract_tool_input(_enriched(record, cs), cs)

        assert business == {"q": "Q1", "classify.category": "FAQ"}

    def test_no_observe_flattens_all_namespaces(self):
        record = {"content": {"extract": {"q": "Q1"}, "classify": {"category": "FAQ"}}}

        assert extract_tool_input(record, {}) == {"q": "Q1", "category": "FAQ"}
