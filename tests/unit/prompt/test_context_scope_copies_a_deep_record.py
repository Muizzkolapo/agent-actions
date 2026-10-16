"""Applying a context scope copies the record it scopes, whatever its depth.

The scope must not mutate the record it was handed, so it works on a copy.
`copy.deepcopy` recurses once per level and fails on a record about 500 levels deep,
which failed a batch run while its tasks were being prepared.
"""

from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    apply_context_scope_for_records,
)

DEPTH = 800


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _depth(node: list) -> int:
    depth = 0
    while node:
        node = node[0]
        depth += 1
    return depth


class TestARecordScopedForOneTask:
    def test_a_scope_with_no_directive_returns_a_full_independent_copy(self):
        field_context = {"source": {"q": "x", "deep": _nested(DEPTH)}}

        prompt_context, _, _ = apply_context_scope(field_context, {}, action_name="act")

        assert _depth(prompt_context["source"]["deep"]) == DEPTH
        assert prompt_context["source"]["deep"] is not field_context["source"]["deep"]

    def test_a_scope_that_observes_leaves_the_record_it_was_handed_untouched(self):
        field_context = {"source": {"q": "x", "deep": _nested(DEPTH)}}

        _, llm_context, _ = apply_context_scope(
            field_context, {"observe": ["source.q"]}, action_name="act"
        )

        assert llm_context["source"] == {"q": "x"}
        assert _depth(field_context["source"]["deep"]) == DEPTH


class TestRecordsScopedForOneFile:
    @staticmethod
    def _record() -> dict:
        return {
            "source_guid": "sg_0",
            "content": {
                "source": {"q": "x", "deep": _nested(DEPTH)},
                "dep": {"a": "1", "deep": _nested(DEPTH)},
            },
        }

    def test_the_enriched_record_is_a_full_independent_copy(self):
        record = self._record()

        enriched, skipped = apply_context_scope_for_records(
            records=[record], context_scope={"observe": ["dep.a"]}, action_name="act"
        )

        assert skipped == []
        assert _depth(enriched[0]["content"]["dep"]["deep"]) == DEPTH
        assert enriched[0]["content"]["dep"]["deep"] is not record["content"]["dep"]["deep"]

    def test_the_source_namespace_is_copied_in_full_too(self):
        record = self._record()

        enriched, skipped = apply_context_scope_for_records(
            records=[record],
            context_scope={"observe": ["source.q"]},
            action_name="act",
            source_data=[record],
        )

        assert skipped == []
        deep = enriched[0]["content"]["source"]["deep"]
        assert _depth(deep) == DEPTH
        assert deep is not record["content"]["source"]["deep"]
