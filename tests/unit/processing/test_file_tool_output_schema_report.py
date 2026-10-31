"""validate_output_against_schema unwraps a FileUDFResult and reports per record."""

from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.validation.schema_output_validator import validate_output_against_schema

_SCHEMA = {
    "name": "dedup_by_concept",
    "properties": {"concept_label": {"type": "string"}, "key": {"type": "string"}},
    "required": ["concept_label", "key"],
}


def test_conforming_file_udf_result_reports_compliant():
    result = FileUDFResult(
        outputs=[
            {"source_index": 0, "data": {"concept_label": "geometry", "key": "g1"}},
            {"source_index": 1, "data": {"concept_label": "algebra", "key": "a1"}},
        ]
    )
    report = validate_output_against_schema(result, _SCHEMA, "dedup_by_concept")
    assert report.is_compliant
    assert not any("Empty object" in e for e in report.validation_errors)
    assert report.missing_required == []


def test_file_udf_result_records_missing_required_reports_noncompliant():
    result = FileUDFResult(outputs=[{"source_index": 0, "data": {"concept_label": "geometry"}}])
    report = validate_output_against_schema(result, _SCHEMA, "dedup_by_concept")
    assert not report.is_compliant
    assert "key" in report.missing_required


def test_file_udf_result_field_union_across_records():
    # Fields are drawn from all records, so a field present in any record counts.
    result = FileUDFResult(
        outputs=[
            {"source_index": 0, "data": {"concept_label": "geometry"}},
            {"source_index": 1, "data": {"key": "g1"}},
        ]
    )
    report = validate_output_against_schema(result, _SCHEMA, "dedup_by_concept")
    assert {"concept_label", "key"} <= report.actual_fields
