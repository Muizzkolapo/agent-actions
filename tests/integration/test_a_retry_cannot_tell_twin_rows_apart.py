"""A FILE tool writing two rows holding the same for one record: which stored row each
one was cannot be told, so neither is put back, and both are answered again below."""

from __future__ import annotations

import pytest

from tests.integration.test_a_retry_runs_a_file_tool_over_its_whole_file import (
    _FILE_TOOL_HEAD,
    TOOL_BELOW,
    _failed_then_fixed,
    _finalized,
    _project,
    _retry,
    _rows,
)

_TWINS = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    return FileUDFResult(
        outputs=[
            {"source_index": i, "data": {"summary": f"{page} twin", "exam_density": "low"}}
            for i, page in enumerate(pages)
            for _ in (1, 2)
        ]
    )
"""
)


@pytest.fixture
def project(tmp_path):
    return _project(tmp_path, TOOL_BELOW, _TWINS)


def test_twin_rows_are_minted_again_and_answered_again_below(project):
    before = {r["source_guid"] for r in _failed_then_fixed(project)["pages1.json"]}

    _retry(project)

    after = {r["source_guid"] for r in _rows(project, as_stored=True)["pages1.json"]}
    assert len(after) == 4
    assert after.isdisjoint(before)
    assert sorted(_finalized(project)) == [
        "Page alpha. twin",
        "Page alpha. twin",
        "Page beta. twin",
        "Page beta. twin",
    ]
