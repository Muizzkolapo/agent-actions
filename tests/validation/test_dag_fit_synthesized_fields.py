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

    def test_unparsable_source_declines(self):
        assert unconditional_output_keys("def broken(:") is None
