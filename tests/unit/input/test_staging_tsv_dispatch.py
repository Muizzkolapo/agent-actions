"""Regression tests for `.tsv` files staging dispatch.

Before this fix, the staging dispatch in
``agent_actions/input/preprocessing/staging/initial_pipeline.py`` had no
``.tsv`` branch in ``_prepare_batch_data`` or ``_prepare_online_data``, and
the ``supported`` lists in the else-branches excluded ``.tsv``. ``TabularLoader``
already accepted ``.tsv``, so doc readers placing a ``.tsv`` file in
``agent_io/staging/`` hit ``AgentActionsError("Unsupported file type in
staging loader")`` before the loader ever saw the file.

These tests pin both code paths so a future refactor that adds a new
file-type branch cannot silently re-introduce the trap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_batch_data,
    _prepare_online_data,
)


def _write_tsv(tmp_path: Path, name: str = "rows.tsv") -> Path:
    p = tmp_path / name
    p.write_text(
        "id\tcontent\tcategory\n1\tFirst row\ttechnical\n2\tSecond row\tgeneral\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def tsv_ctx(tmp_path: Path) -> DataPreparationContext:
    tsv_file = _write_tsv(tmp_path)
    return DataPreparationContext(
        content=None,
        file_type=".tsv",
        agent_config={},
        file_path=str(tsv_file),
        agent_name="tsv_workflow",
        idx=0,
    )


class TestBatchTsvDispatch:
    """``_prepare_batch_data`` routes ``.tsv`` through the tabular loader."""

    def test_tsv_routes_through_tabular_loader(self, tsv_ctx):
        data_chunk, src_text = _prepare_batch_data(tsv_ctx)

        assert data_chunk, "TSV staging produced no data chunk"
        assert src_text == []

        first = data_chunk[0]
        assert "batch_id" in first
        assert "batch_uuid" in first

    def test_tsv_listed_in_batch_supported_types(self):
        """When a future refactor changes the dispatch table, the ``supported``
        list still names ``.tsv`` so the error context tells the user it is
        accepted."""
        import inspect

        from agent_actions.input.preprocessing.staging import initial_pipeline

        source = inspect.getsource(initial_pipeline._prepare_batch_data)
        assert '".tsv"' in source, (
            "_prepare_batch_data must reference .tsv in its supported-types list"
        )


class TestOnlineTsvDispatch:
    """``_prepare_online_data`` routes ``.tsv`` through the tabular loader."""

    def test_tsv_routes_through_tabular_loader(self, tsv_ctx):
        data_chunk, src_text = _prepare_online_data(tsv_ctx)

        assert data_chunk, "TSV online prep produced no data chunk"
        assert data_chunk == src_text

    def test_tsv_listed_in_online_supported_types(self):
        import inspect

        from agent_actions.input.preprocessing.staging import initial_pipeline

        source = inspect.getsource(initial_pipeline._prepare_online_data)
        assert '".tsv"' in source, (
            "_prepare_online_data must reference .tsv in its supported-types list"
        )
