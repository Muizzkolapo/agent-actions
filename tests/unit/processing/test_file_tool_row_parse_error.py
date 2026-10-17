"""One _parse_error row in a bundled FILE result fails only that row (#1269)."""

from unittest.mock import MagicMock

from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingResult, ProcessingStatus


def _row(guid, answer):
    return {"source_guid": guid, "content": {"shape": answer}}


def _collect(rows):
    backend = MagicMock()
    result = ProcessingResult(status=ProcessingStatus.SUCCESS, data=rows, source_guid=None)
    output, stats = collect_results_from_processing_results(
        [result], "shape", storage_backend=backend
    )
    written = [row for call in backend.set_dispositions_batch.call_args_list for row in call[0][0]]
    return output, stats, {row[1]: (row[2], row[3]) for row in written}


def test_only_the_row_holding_parse_error_fails():
    output, stats, dispositions = _collect(
        [
            _row("g1", {"summary": "s", "_parse_error": "bad json"}),
            _row("g2", {"summary": "ok"}),
        ]
    )

    assert dispositions == {"g1": ("failed", "parse_error"), "g2": ("success", None)}
    states = {row["source_guid"]: row["_state"] for row in output}
    assert states == {"g1": "failed", "g2": "processed"}
    assert stats.success == 1
    assert stats.failed == 1


def test_every_row_holding_parse_error_fails_every_row():
    output, stats, dispositions = _collect(
        [
            _row("g1", {"_parse_error": "bad"}),
            _row("g2", {"_parse_error": "bad"}),
        ]
    )

    assert dispositions == {"g1": ("failed", "parse_error"), "g2": ("failed", "parse_error")}
    assert {row["_state"] for row in output} == {"failed"}
    assert stats.success == 0
    assert stats.failed == 2
