"""The record a JSON Schema form file produces carries the fields it declares (1346)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.store import stored_rows
from tests.integration.test_a_json_schema_file_runs import (
    _OBJECT,
    WORKFLOW,
    _project,
    _run,
)


def _records(root: Path) -> list[dict]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    blobs = [row[0] for row in stored_rows(db, "select data from target_data")]
    out: list[dict] = []
    for blob in blobs:
        loaded = json.loads(blob)
        out.extend(loaded if isinstance(loaded, list) else [loaded])
    return out


def test_an_object_form_schema_file_produces_records_with_its_properties(tmp_path):
    root = _project(tmp_path, "json_schema_page_summary", _OBJECT, "online")

    code, output = _run(root)

    assert code == 0, output
    records = _records(root)
    assert records, "nothing was written"
    for record in records:
        assert {"summary", "tone"} <= set(record["content"]["summarize"]), record
