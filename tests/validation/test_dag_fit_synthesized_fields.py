"""dag-fit must not flag output fields the consuming tool synthesizes itself.

No upstream producer can guarantee a value the tool computes, so comparing a
tool's own outputs against upstream schemas reports a gap that does not exist.
Where the UDF provably emits the field, the field is guaranteed and the check
must stay quiet; where the shape cannot be read, the check still warns.
"""

import textwrap

from agent_actions.validation.dag_schema_fit_validator import (
    find_dag_schema_compatibility_gaps,
)
from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
    unconditional_output_keys,
)

_CONSUMER = {
    "kind": "tool",
    "dependencies": ["upstream"],
    "json_output_schema": {
        "type": "object",
        "properties": {
            "output_path": {"type": "string"},
            "written_count": {"type": "integer"},
        },
        "required": ["output_path", "written_count"],
    },
}
_UPSTREAM = {"kind": "tool", "json_output_schema": {"type": "object", "properties": {}}}


class TestSynthesizedFieldsAreGuaranteed:
    def test_provably_emitted_fields_are_not_reported(self):
        configs = {"upstream": _UPSTREAM, "writer": _CONSUMER}
        gaps = find_dag_schema_compatibility_gaps(
            configs, synthesized={"writer": {"output_path", "written_count"}}
        )
        assert gaps == {}, f"tool-synthesized fields must not be reported: {gaps}"

    def test_unemitted_fields_are_still_reported(self):
        configs = {"upstream": _UPSTREAM, "writer": _CONSUMER}
        gaps = find_dag_schema_compatibility_gaps(configs, synthesized={"writer": {"output_path"}})
        assert gaps == {"writer": ["written_count"]}, gaps

    def test_no_synthesis_info_preserves_existing_behavior(self):
        configs = {"upstream": _UPSTREAM, "writer": _CONSUMER}
        gaps = find_dag_schema_compatibility_gaps(configs)
        assert gaps == {"writer": ["output_path", "written_count"]}, gaps


class TestFileUDFResultEnvelope:
    """FILE tools return a FileUDFResult envelope; its inner data keys are the output."""

    def test_inline_envelope_keys_are_read(self):
        source = textwrap.dedent("""
            def write_rows(items):
                path = "/out.jsonl"
                rows = [1, 2]
                return FileUDFResult(
                    outputs=[{"source_index": 0, "data": {"output_path": path,
                                                          "written_count": len(rows)}}]
                )
        """)
        assert unconditional_output_keys(source) == {"output_path", "written_count"}

    def test_loop_built_outputs_decline_to_decide(self):
        source = textwrap.dedent("""
            def dedup(items):
                outs = []
                for item in items:
                    outs.append({"data": {"concept_label": item}})
                return FileUDFResult(outputs=outs)
        """)
        assert unconditional_output_keys(source) is None

    def test_plain_dict_return_still_read(self):
        source = textwrap.dedent("""
            def votes(item):
                keeps = 2
                return {"keep": keeps >= 2, "agreement_count": keeps}
        """)
        assert unconditional_output_keys(source) == {"keep", "agreement_count"}

    def test_envelope_reading_does_not_reach_the_refusal_check(self):
        """Reading envelopes must not make the refusal check see FILE tools.

        That check raises and stops the run; extending its reach here would
        turn projects that pass preflight today into refused ones.
        """
        source = textwrap.dedent("""
            def writer(items):
                return FileUDFResult(outputs=[{"data": {"output_path": "/x"}}])
        """)
        assert unconditional_output_keys(source) == {"output_path"}
        assert (
            find_conditional_required_field_risks(
                {"writer": {"source": source, "required": ["output_path", "written_count"]}}
            )
            == []
        )

    def test_multiple_output_rows_intersect_not_union(self):
        """Each output row is validated alone, so only keys on every row are guaranteed."""
        source = textwrap.dedent("""
            def split(items):
                return FileUDFResult(outputs=[
                    {"data": {"shared": 1, "only_first": 2}},
                    {"data": {"shared": 3, "only_second": 4}},
                ])
        """)
        assert unconditional_output_keys(source) == {"shared"}

    def test_tail_return_wins_over_earlier_branches(self):
        """Known limit: the tail return is read as the output shape.

        Keys emitted only by an earlier branch are not counted, and keys the
        earlier branch omits are still treated as guaranteed — so a field the
        early path skips can go unwarned. The reading is shared with the
        conditional-required scanner; narrowing it belongs with that check,
        and the cost here is at most one advisory warning not shown.
        """
        source = textwrap.dedent("""
            def writer(items):
                if not items:
                    return FileUDFResult(outputs=[{"data": {"written_count": 0}}])
                return FileUDFResult(outputs=[{"data": {"written_count": 1,
                                                        "output_path": "/x"}}])
        """)
        assert unconditional_output_keys(source) == {"written_count", "output_path"}

    def test_unparsable_source_declines(self):
        assert unconditional_output_keys("def broken(:") is None


class TestOutputTheReaderCannotSee:
    """A tool whose output keys cannot be read makes no dag-fit claim (1436)."""

    def test_annotated_assignment_is_read_like_a_plain_one(self):
        source = textwrap.dedent("""
            def build(data):
                out: dict[str, Any] = {"alpha": 1}
                out.update({"beta": 2})
                out["gamma"] = 3
                return out
        """)
        assert unconditional_output_keys(source) == {"alpha", "beta", "gamma"}

    def test_annotated_assignment_does_not_reach_the_refusal_check(self):
        """The refusal check stops a run; it keeps reading only what it read before."""
        source = textwrap.dedent("""
            def build(data):
                out: dict = {"alpha": 1}
                if data:
                    out["beta"] = 2
                return out
        """)
        assert (
            find_conditional_required_field_risks(
                {"build": {"source": source, "required": ["alpha", "beta"]}}
            )
            == []
        )

    def test_unreadable_output_is_not_reported(self):
        configs = {"upstream": _UPSTREAM, "writer": _CONSUMER}
        gaps = find_dag_schema_compatibility_gaps(configs, synthesized={"writer": None})
        assert gaps == {}, gaps

    def test_fields_inside_an_emitted_key_are_not_reported(self):
        """The tool computes the whole value of a key it emits; its insides are the tool's."""
        consumer = {
            "kind": "tool",
            "dependencies": ["upstream"],
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                            "required": ["id"],
                        },
                    },
                    "missing": {
                        "type": "object",
                        "properties": {"inner": {"type": "string"}},
                        "required": ["inner"],
                    },
                },
                "required": ["items", "missing"],
            },
        }
        configs = {"upstream": _UPSTREAM, "writer": consumer}
        gaps = find_dag_schema_compatibility_gaps(configs, synthesized={"writer": {"items"}})
        assert gaps == {"writer": ["missing"]}, gaps


class TestUpstreamSuppliesNothingToATool:
    """A tool's output is validated as its UDF returns it; upstream fields are not in it (1492)."""

    _PRODUCER = {
        "kind": "llm",
        "json_output_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
            "required": ["id", "label"],
        },
    }

    def _consumer(self, properties: dict, required: list[str]) -> dict:
        return {
            "kind": "tool",
            "dependencies": ["extract"],
            "context_scope": {"passthrough": ["extract.id"]},
            "json_output_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def test_a_field_upstream_requires_is_reported_when_the_tool_omits_it(self):
        consumer = self._consumer(
            {"id": {"type": "string"}, "note": {"type": "string"}}, ["id", "note"]
        )
        configs = {"extract": self._PRODUCER, "collect": consumer}
        gaps = find_dag_schema_compatibility_gaps(configs, synthesized={"collect": {"note"}})
        assert gaps == {"collect": ["id"]}, gaps

    def test_a_required_field_inside_an_optional_object_the_tool_omits_is_not_reported(self):
        """The object is optional and absent, so nothing inside it is checked at runtime."""
        consumer = self._consumer(
            {
                "note": {"type": "string"},
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}, "rank": {"type": "string"}},
                        "required": ["label", "rank"],
                    },
                },
            },
            ["note"],
        )
        configs = {"extract": self._PRODUCER, "collect": consumer}
        gaps = find_dag_schema_compatibility_gaps(configs, synthesized={"collect": {"note"}})
        assert gaps == {}, gaps
