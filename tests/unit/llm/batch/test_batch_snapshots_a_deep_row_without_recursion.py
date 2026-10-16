"""Collection snapshots a record's original row, whatever its depth.

Every result built for a record the provider did not answer, or that a guard or an
empty answer turned away, carries a copy of the row it came from. `copy.deepcopy`
recurses once per level and fails on a row about 500 levels deep, which failed the
whole collect pass; each builder is driven here with a row far past that.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import ExpectationsMetadata, RecoveryMetadata

DEPTH = 800


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _depth(node: list) -> int:
    depth = 0
    while node:
        node = node[0]
        depth += 1
    return depth


def _row() -> dict:
    return {
        "target_id": "t-1",
        "source_guid": "sg-1",
        "content": {"source": {"deep": _nested(DEPTH)}},
    }


def _ctx(row: dict, **config) -> MagicMock:
    ctx = MagicMock()
    ctx.reconciler.get_source_guid.return_value = "sg-1"
    ctx.reconciler.get_record_by_id.return_value = row
    ctx.reconciler.get_record_index.return_value = 0
    ctx.agent_config = {"action_name": "act", **config}
    ctx.output_directory = "/out"
    return ctx


def _innermost(node: list) -> list:
    while node:
        node = node[0]
    return node


def _assert_snapshot_is_a_full_independent_copy(snapshot: dict, row: dict) -> None:
    deep = snapshot["content"]["source"]["deep"]
    assert _depth(deep) == DEPTH
    assert deep is not row["content"]["source"]["deep"]
    _innermost(deep).append("changed")
    assert _innermost(row["content"]["source"]["deep"]) == [], "the copy shares its depths"


class TestEveryBuilderSnapshotsADeepRow:
    def test_an_error_result(self):
        row = _row()

        result = BatchResultStrategy()._build_error_result(_ctx(row), "t-1", "the provider erred")

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_an_unprocessed_passthrough(self):
        row = _row()

        result = BatchResultStrategy()._build_unprocessed_passthrough(
            _ctx(row), row, "act", "sg-1", 0
        )

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_a_failed_passthrough(self):
        row = _row()

        result = BatchResultStrategy()._build_failed_passthrough(_ctx(row), row, "act", "sg-1", 0)

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_a_record_the_provider_did_not_answer(self):
        row = _row()

        result = BatchResultStrategy()._build_not_returned(_ctx(row), row, "act", "sg-1", 0)

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_a_record_with_no_identity_keeps_a_snapshot_and_an_input_copy(self):
        row = _row()

        result = BatchResultStrategy()._build_not_returned(_ctx(row), row, "act", None, 0)

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)
        _assert_snapshot_is_a_full_independent_copy(result.input_record, row)
        assert result.input_record is not result.source_snapshot

    def test_an_exhausted_passthrough(self):
        row = _row()
        strategy = BatchResultStrategy()

        with patch.object(
            strategy,
            "_exhausted_recovery_for",
            return_value=(MagicMock(), SimpleNamespace(attempts=2)),
        ):
            result = strategy._build_exhausted_passthrough(_ctx(row), "t-1", row, "act", "sg-1", 0)

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_a_record_the_expectation_loop_gave_up_on(self):
        row = _row()
        batch_result = BatchResult(
            custom_id="t-1",
            content=None,
            success=False,
            recovery_metadata=RecoveryMetadata(
                expectations=ExpectationsMetadata(attempts=2, failed=["enough"])
            ),
        )

        result = BatchResultStrategy()._build_expectations_exhausted(_ctx(row), "t-1", batch_result)

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)

    def test_an_empty_answer_the_action_skips(self):
        row = _row()
        ctx = _ctx(row, on_empty="skip")

        result = BatchResultStrategy()._empty_answer(
            ctx, BatchResult(custom_id="t-1", content=None, success=True), "t-1", None
        )

        _assert_snapshot_is_a_full_independent_copy(result.source_snapshot, row)


def test_the_snapshot_equals_the_row_at_a_shallow_depth():
    row = {"target_id": "t-1", "source_guid": "sg-1", "content": {"source": {"a": [1, {"b": 2}]}}}

    result = BatchResultStrategy()._build_error_result(_ctx(row), "t-1", "boom")

    assert result.source_snapshot == row
    assert result.source_snapshot is not row
