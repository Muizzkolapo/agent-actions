"""First-stage identity is robust to real loader output: dates and tabs.

The single envelope authority routes every online row through derive_source_guid
(json.dumps-based). A pandas Timestamp date cell from .xlsx must hash rather than crash, a
tab-separated .tsv must parse into real columns, and identity for normal string-keyed rows
must not move (576 golden). A non-string field name has no stable identity and is rejected.
"""

import datetime
from pathlib import Path

import pytest

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.errors import DataValidationError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_online_data,
)
from agent_actions.utils.id_generation import IDGenerator


def _online(content, file_type, file_path):
    ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        agent_config={},
        file_path=file_path,
        agent_name="a",
    )
    return _prepare_online_data(ctx)


def test_derive_golden_values_unchanged():
    # canonicalization must be a strict no-op for normal string-keyed payloads
    assert (
        IDGenerator.derive_source_guid(
            {"content": "The mitochondria is the powerhouse of the cell."}
        )
        == "865e85c1-c292-5537-a9dc-aed6618263eb"
    )
    assert (
        IDGenerator.derive_source_guid(
            {"question": "What is 2+2?", "answer": "4", "metadata": {"src": "quiz.json", "row": 7}}
        )
        == "cac9d8de-ed99-5b95-948e-ebd0439e27e2"
    )


def test_derive_handles_datetime_values_deterministically():
    row = {"id": "1", "when": datetime.datetime(2024, 1, 1)}
    g1 = IDGenerator.derive_source_guid(dict(row))
    g2 = IDGenerator.derive_source_guid(dict(row))
    assert g1 and g1 == g2, "datetime identity must be non-blank and deterministic"
    assert (
        IDGenerator.derive_source_guid({"id": "1", "when": datetime.datetime(2024, 1, 2)}) != g1
    ), "a different date must be a different identity"


def test_derive_rejects_non_string_field_names():
    # a ragged csv row's None restkey / a numeric xlsx header has no usable name — fail loud
    with pytest.raises(DataValidationError):
        IDGenerator.derive_source_guid({"a": "1", "b": "2", None: ["3", "4"]})
    with pytest.raises(DataValidationError):
        IDGenerator.derive_source_guid({2024: "x", "name": "y"})


def test_online_xlsx_date_column_ingests_without_crash():
    row = {"id": "1", "when": datetime.datetime(2024, 3, 4)}
    _dc, st = _online([dict(row)], ".xlsx", "/tmp/d.xlsx")
    assert st[0]["content"]["source"]["id"] == "1"
    assert st[0]["source_guid"] == IDGenerator.derive_source_guid(row)


def _write_tsv(tmp_path: Path) -> str:
    p = tmp_path / "rows.tsv"
    p.write_text("id\tbody\tnode_id\n1\thello\tUSER_A\n", encoding="utf-8")
    return str(p)


def test_online_tsv_columns_split_on_tab(tmp_path):
    # a .tsv must parse tab-delimited, not collapse into one mangled column
    _dc, st = _online(None, ".tsv", _write_tsv(tmp_path))
    src = st[0]["content"]["source"]
    assert set(src.keys()) == {"id", "body", "node_id"}, f"tsv not tab-split: {src}"
    assert src == {"id": "1", "body": "hello", "node_id": "USER_A"}


def _write_csv_with_guid_col(tmp_path: Path) -> str:
    p = tmp_path / "rows.csv"
    p.write_text("source_guid,a\ncollide,1\ncollide,2\n", encoding="utf-8")
    return str(p)


def test_online_csv_source_guid_column_does_not_hijack_identity(tmp_path):
    _dc, st = _online(None, ".csv", _write_csv_with_guid_col(tmp_path))
    assert st[0]["source_guid"] != st[1]["source_guid"], "csv source_guid column hijacked identity"
    assert st[0]["source_guid"] == IDGenerator.derive_source_guid(
        {"source_guid": "collide", "a": "1"}
    )


def test_online_xlsx_source_guid_column_does_not_hijack_identity():
    rows = [{"source_guid": "collide", "a": "1"}, {"source_guid": "collide", "a": "2"}]
    _dc, st = _online([dict(r) for r in rows], ".xlsx", "/tmp/d.xlsx")
    assert st[0]["source_guid"] != st[1]["source_guid"], "xlsx source_guid column hijacked identity"
