"""A FILE tool's named observe field keeps its bare key beside a wildcard.

The keys a FILE tool reads come from the observe refs alone, so they are the same on
every record and every run. A field the action names is the one it asked for by that
name; a wildcard elsewhere that happens to yield the same name arrives qualified
(``ns.field``) instead of taking the bare key from the named ref. Preflight reports a
qualified key only when the declared schemas show such a collision.
"""

from __future__ import annotations

from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)
from agent_actions.workflow.pipeline_file_mode import extract_tool_input


def _payloads(records: list[dict], observe: list[str]) -> list[dict]:
    scope = {"observe": observe}
    enriched, skipped = apply_context_scope_for_records(
        records=[{"source_guid": f"g{i}", "content": c} for i, c in enumerate(records)],
        context_scope=scope,
        action_name="merge",
    )
    assert not skipped
    return [extract_tool_input(r, scope) for r in enriched]


def _llm(name: str, fields: list[str]) -> dict:
    return {
        "name": name,
        "prompt": f"Run {name}",
        "schema": {"type": "object", "properties": {f: {"type": "string"} for f in fields}},
    }


def _collision_warnings(observe: list[str], gen_b_fields: list[str]) -> list:
    workflow = {
        "actions": [
            _llm("gen_a", ["code", "notes"]),
            _llm("gen_b", gen_b_fields),
            {
                "name": "merge",
                "kind": "tool",
                "function": "merge_fn",
                "granularity": "file",
                "dependencies": ["gen_a", "gen_b"],
                "context_scope": {"observe": observe},
            },
        ]
    }
    result = WorkflowStaticAnalyzer(workflow).analyze()
    return [w for w in result.warnings if "namespace-qualified" in w.message]


class TestTheKeysAToolIsHanded:
    def test_a_named_field_beside_a_wildcard_keeps_its_bare_key(self):
        (payload,) = _payloads(
            [{"a": {"code": 1, "size": 2}, "b": {"flag": "F"}}], ["a.*", "b.flag"]
        )

        assert payload == {"code": 1, "size": 2, "flag": "F"}

    def test_a_wildcard_field_that_shares_a_named_fields_name_arrives_qualified(self):
        (payload,) = _payloads(
            [{"a": {"code": 1, "size": 2}, "b": {"code": "B"}}], ["a.*", "b.code"]
        )

        assert payload == {"code": "B", "a.code": 1, "size": 2}

    def test_a_wildcard_field_two_named_refs_share_a_name_with_arrives_qualified_too(self):
        """Both named refs are qualified against each other; the wildcard's field does
        not inherit the bare name they gave up."""
        (payload,) = _payloads(
            [{"a": {"x": "A", "y": 1}, "b": {"x": "B"}, "c": {"x": "C"}}],
            ["a.*", "b.x", "c.x"],
        )

        assert payload == {"a.x": "A", "y": 1, "b.x": "B", "c.x": "C"}

    def test_a_named_field_of_the_wildcards_own_namespace_stays_bare(self):
        (payload,) = _payloads([{"a": {"x": 1, "y": 2}}], ["a.*", "a.x"])

        assert payload == {"x": 1, "y": 2}

    def test_the_named_key_is_the_same_on_a_record_the_wildcard_reaches_and_one_it_does_not(
        self,
    ):
        """Control: the key shape comes from the refs, never from a record's values."""
        first, second = _payloads(
            [{"a": {"code": 1}, "b": {"code": "B"}}, {"a": {}, "b": {"code": "B"}}],
            ["a.*", "b.code"],
        )

        named_key_first = [k for k, v in first.items() if v == "B"]
        named_key_second = [k for k, v in second.items() if v == "B"]
        assert named_key_first == named_key_second
        assert len(named_key_first) == 1
        assert 1 in first.values()
        assert list(second) == named_key_second


class TestWhatPreflightReports:
    def test_a_named_field_a_wildcard_schema_does_not_hold_is_not_a_collision(self):
        assert _collision_warnings(["gen_a.*", "gen_b.score"], ["score"]) == []

    def test_a_wildcard_field_the_schema_says_shares_the_name_is_reported_as_the_qualified_one(
        self,
    ):
        (warning,) = _collision_warnings(["gen_a.*", "gen_b.code"], ["code"])

        assert "gen_a.code" in warning.message
        assert "gen_b.code" not in warning.message
