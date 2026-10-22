"""A staged CSV or TSV is stored cell for cell (1521).

A quoted cell holding a line break, `"line one\\nline two"`, was stored as
`'line oneline two'` and the run exited 0: the loader split the file into lines
before the csv module saw it, so a quoted newline ended the line. A file saved with
a UTF-8 byte order mark stored its first column as `'\\ufeffitem_id'`, so
`source.item_id` was refused by the check that renders the first record.

Every case is a real `agac run` through the CLI, with the mock provider for LLM actions.
"""

from __future__ import annotations

import pytest

from tests.helpers.trace_store import trace_rows
from tests.integration.test_a_staged_spreadsheet_row_is_read_by_column import (
    LLM_PROMPT,
    TOOL_FIRST,
    _assert_ran,
    _project,
    _run,
    _stored,
)


def _restage(root, file_type: str, text: str, *, bom: bool = False) -> None:
    staging = root / "agent_workflow" / "sheet_columns" / "agent_io" / "staging"
    for staged in staging.iterdir():
        staged.unlink()
    data = ("﻿" if bom else "") + text
    (staging / f"items.{file_type}").write_bytes(data.encode("utf-8"))


def _delimited(file_type: str, *rows: tuple[str, str]) -> str:
    sep = "," if file_type == "csv" else "\t"
    return "".join(f"{a}{sep}{b}\r\n" for a, b in (("item_id", "text"), *rows))


MULTILINE = (("a1", '"line one\nline two"'), ("a2", '"crlf one\r\ncrlf two"'))


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "tsv"])
def test_a_quoted_cell_keeps_its_line_breaks(tmp_path, file_type, run_mode):
    root = _project(tmp_path, file_type, TOOL_FIRST.replace("source.item_id", "source.*"), run_mode)
    _restage(root, file_type, _delimited(file_type, *MULTILINE))

    result = _run(root, run_mode)

    _assert_ran(result)
    sources = sorted(
        (record["content"]["source"] for record in _stored(root)), key=lambda s: s["item_id"]
    )
    assert sources == [
        {"item_id": "a1", "text": "line one\nline two"},
        {"item_id": "a2", "text": "crlf one\r\ncrlf two"},
    ]


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "tsv"])
def test_a_prompt_renders_a_multi_line_cell_whole(tmp_path, file_type, run_mode):
    root = _project(tmp_path, file_type, LLM_PROMPT, run_mode)
    _restage(root, file_type, _delimited(file_type, ("a1", '"line one\nline two"')))

    result = _run(root, run_mode)

    _assert_ran(result)
    (prompt,) = [
        p
        for (p,) in trace_rows(
            root, "select compiled_prompt from prompt_trace where action_name = 'first'"
        )
    ]
    assert "Item a1 says line one\nline two." in prompt, prompt


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "tsv"])
def test_a_byte_order_mark_is_not_part_of_the_first_column_name(tmp_path, file_type, run_mode):
    root = _project(tmp_path, file_type, TOOL_FIRST, run_mode)
    _restage(root, file_type, _delimited(file_type, ("a1", "hello"), ("a2", "world")), bom=True)

    result = _run(root, run_mode)

    _assert_ran(result)
    seen = sorted(record["content"]["first"]["got"] for record in _stored(root))
    assert seen == [repr({"source": {"item_id": "a1"}}), repr({"source": {"item_id": "a2"}})]
    assert all(set(r["content"]["source"]) == {"item_id", "text"} for r in _stored(root))
