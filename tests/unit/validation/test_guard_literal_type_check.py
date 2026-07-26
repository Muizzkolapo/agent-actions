"""Preflight: a guard literal whose type can never match the referenced field's
declared schema type must be flagged before any record is processed.

``producer.approved == true`` with ``approved`` declared ``string`` filters every
record at runtime regardless of data — the analyzer must surface it statically.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _workflow(producer_schema_types, guard_condition, on_false="filter"):
    return {
        "name": "wf",
        "actions": [
            {
                "name": "producer",
                "prompt": "P: {{ source.text }}",
                "schema": {
                    "type": "object",
                    "properties": {f: {"type": t} for f, t in producer_schema_types.items()},
                },
                "context_scope": {"observe": ["source.text"]},
            },
            {
                "name": "consumer",
                "dependencies": ["producer"],
                "prompt": "C: {{ source.text }}",
                "schema": {
                    "type": "object",
                    "properties": {"out": {"type": "string"}},
                },
                "guard": {"condition": guard_condition, "on_false": on_false},
                "context_scope": {"observe": ["source.text", "producer.*"]},
            },
        ],
    }


def _type_warnings(result):
    return [w.message for w in result.warnings if "type mismatch" in w.message]


class TestGuardLiteralTypeMismatchWarns:
    def test_boolean_literal_vs_string_field_warns(self):
        wf = _workflow({"approved": "string"}, "producer.approved == true")
        warnings = _type_warnings(WorkflowStaticAnalyzer(wf).analyze())

        assert len(warnings) == 1
        message = warnings[0]
        assert "producer.approved" in message
        assert "string" in message
        assert "boolean" in message

    def test_string_literal_vs_boolean_field_warns(self):
        wf = _workflow({"approved": "boolean"}, 'producer.approved == "true"')
        warnings = _type_warnings(WorkflowStaticAnalyzer(wf).analyze())

        assert len(warnings) == 1
        assert "producer.approved" in warnings[0]

    def test_number_literal_vs_string_field_relational_warns(self):
        wf = _workflow({"score": "string"}, "producer.score > 3")
        warnings = _type_warnings(WorkflowStaticAnalyzer(wf).analyze())

        assert len(warnings) == 1
        assert "producer.score" in warnings[0]

    def test_compound_condition_flags_only_the_mismatched_side(self):
        wf = _workflow(
            {"approved": "string", "status": "string"},
            'producer.approved == true or producer.status == "ok"',
        )
        warnings = _type_warnings(WorkflowStaticAnalyzer(wf).analyze())

        assert len(warnings) == 1
        assert "producer.approved" in warnings[0]
        assert "producer.status" not in warnings[0]


class TestCompatibleGuardLiteralsStaySilent:
    def test_boolean_literal_vs_boolean_field_no_warning(self):
        wf = _workflow({"approved": "boolean"}, "producer.approved == true")
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []

    def test_string_literal_vs_string_field_no_warning(self):
        wf = _workflow({"status": "string"}, 'producer.status == "approved"')
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []

    def test_number_literal_vs_integer_field_no_warning(self):
        wf = _workflow({"score": "integer"}, "producer.score >= 3")
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []

    def test_undeclared_field_no_warning(self):
        wf = _workflow({"other": "string"}, "producer.approved == true")
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []

    def test_udf_guard_no_warning(self):
        wf = _workflow({"approved": "string"}, "udf:tools.check_approved")
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []

    def test_null_literal_no_warning(self):
        wf = _workflow({"approved": "string"}, "producer.approved != null")
        assert _type_warnings(WorkflowStaticAnalyzer(wf).analyze()) == []
