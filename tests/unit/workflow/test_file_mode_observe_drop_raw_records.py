"""FILE-mode observe-drop must not desync raw_records (spec 587).

When ``context_scope.observe`` drops records that lack an observed upstream
namespace — the shape produced by merging a guard-filtered source (e.g.
``tag_code_concept``) with an unfiltered one (``dedup_code_blocks``) — the pipeline
must pass ``raw_records`` ALIGNED to the observe-filtered survivors, not the full
pre-observe ``data``. Passing the full data desyncs the two arrays, and
``UnifiedProcessor``'s ``prefilter_by_guard`` asserts
``len(original_data) == len(data)`` — so the action crashes with a length-mismatch
``RuntimeError`` and every downstream action cascade-SKIPs.

Alignment is by input INDEX, not source_guid: merged/version records can carry
``source_guid=None`` (loop.py) or duplicate guids, so a guid set-diff would leave
desynced records behind and recreate the crash.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.result_collector import CollectionStats
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

OBSERVE_SCOPE = {"observe": ["tag.label", "code.block"]}


def _build_file_mode_pipeline(context_scope, *, kind="tool", storage_backend=None):
    return ProcessingPipeline(
        config=PipelineConfig(
            action_config={
                "kind": kind,
                "granularity": "file",
                "run_mode": "online",
                "impl": "noop",
                "context_scope": context_scope,
            },
            action_name="dedup_by_concept",
            idx=0,
            storage_backend=storage_backend,
        ),
        processor_factory=object(),
    )


def _run_capture(pipeline, data, tmp_path, process_return=None):
    """Run _process_by_strategy with process() mocked to capture its arguments."""
    captured = {}

    def _capture(records, context, strategy, raw_records=None):
        captured["filtered"] = records
        captured["raw_records"] = raw_records
        return process_return if process_return is not None else ([], MagicMock())

    with (
        patch.object(pipeline._unified_processor, "process", side_effect=_capture),
        patch.object(pipeline.output_handler, "save_main_output"),
    ):
        pipeline._process_by_strategy(
            data=data,
            file_path=str(tmp_path / "in.json"),
            base_directory=str(tmp_path),
            output_directory=str(tmp_path / "out"),
        )
    return captured


def test_observe_drop_passes_raw_records_aligned_to_filtered(tmp_path):
    # sg-2 and sg-4 lack the observed 'tag' namespace (filtered at an upstream
    # guard) and are observe-dropped; sg-0/1/3 survive.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": "sg-1", "content": {"tag": {"label": "B"}, "code": {"block": "y"}}},
        {"source_guid": "sg-2", "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-3", "content": {"tag": {"label": "D"}, "code": {"block": "w"}}},
        {"source_guid": "sg-4", "content": {"code": {"block": "v"}}},
    ]
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE)
    captured = _run_capture(pipeline, data, tmp_path)

    # observe dropped sg-2 and sg-4 → 3 survivors reach the processor.
    assert [r["source_guid"] for r in captured["filtered"]] == ["sg-0", "sg-1", "sg-3"]
    # raw_records is prefilter_by_guard's pre-observe alignment array; it must match
    # the survivors 1:1. Passing the full 5-record data (the bug) makes
    # len(original_data) != len(data) → length-mismatch RuntimeError.
    assert [r["source_guid"] for r in captured["raw_records"]] == ["sg-0", "sg-1", "sg-3"]


def test_observe_drop_aligns_raw_records_when_source_guid_is_none(tmp_path):
    # The observe-dropped records carry source_guid=None (as version/merge records
    # can — loop.py warns and produces them). A guid set-diff cannot exclude them
    # (None is filtered out of the skip set), so it would leave all 5 records in
    # raw_records while only 3 survive → the same length-mismatch crash. Index-based
    # alignment drops exactly positions 2 and 4 regardless of guid.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": "sg-1", "content": {"tag": {"label": "B"}, "code": {"block": "y"}}},
        {"source_guid": None, "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-3", "content": {"tag": {"label": "D"}, "code": {"block": "w"}}},
        {"source_guid": None, "content": {"code": {"block": "v"}}},
    ]
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE)
    captured = _run_capture(pipeline, data, tmp_path)

    assert [r["source_guid"] for r in captured["filtered"]] == ["sg-0", "sg-1", "sg-3"]
    assert [r["source_guid"] for r in captured["raw_records"]] == ["sg-0", "sg-1", "sg-3"]
    assert len(captured["raw_records"]) == len(captured["filtered"])


def test_no_observe_drop_passes_full_data_as_raw_records(tmp_path):
    # No record is dropped (all carry 'tag'), so the fast-path branch returns the
    # full data unchanged as raw_records — 1:1 with filtered.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": "sg-1", "content": {"tag": {"label": "B"}, "code": {"block": "y"}}},
        {"source_guid": "sg-2", "content": {"tag": {"label": "C"}, "code": {"block": "z"}}},
    ]
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE)
    captured = _run_capture(pipeline, data, tmp_path)

    assert [r["source_guid"] for r in captured["filtered"]] == ["sg-0", "sg-1", "sg-2"]
    assert [r["source_guid"] for r in captured["raw_records"]] == ["sg-0", "sg-1", "sg-2"]


def test_hitl_file_mode_aligns_raw_records_to_filtered(tmp_path):
    # The alignment covers HITL actions too (same branch as tool); sg-1 is dropped.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": "sg-1", "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-2", "content": {"tag": {"label": "C"}, "code": {"block": "w"}}},
    ]
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE, kind="hitl")
    captured = _run_capture(pipeline, data, tmp_path)

    assert [r["source_guid"] for r in captured["filtered"]] == ["sg-0", "sg-2"]
    assert [r["source_guid"] for r in captured["raw_records"]] == ["sg-0", "sg-2"]


def test_index_alignment_satisfies_real_prefilter_by_guard_invariant():
    # End-to-end at the exact boundary that crashed: the REAL prefilter_by_guard,
    # not a mock. apply_context_scope_for_records must tag each skipped record with
    # its input index so the caller can align raw_records positionally. Feeding the
    # aligned array satisfies the length invariant; feeding the full pre-observe data
    # raises the length-mismatch RuntimeError the fix exists to prevent.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": None, "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-2", "content": {"tag": {"label": "C"}, "code": {"block": "w"}}},
    ]
    filtered, scope_skipped = apply_context_scope_for_records(
        records=data, context_scope=OBSERVE_SCOPE, action_name="dedup_by_concept"
    )
    assert all("index" in skip for skip in scope_skipped)

    skipped_indices = {skip["index"] for skip in scope_skipped}
    aligned_raw = [record for i, record in enumerate(data) if i not in skipped_indices]

    passing, _skipped, original_passing, _filtered_out = prefilter_by_guard(
        filtered, {}, "dedup_by_concept", original_data=aligned_raw
    )
    assert len(original_passing) == len(passing) == len(filtered)

    with pytest.raises(RuntimeError, match="length mismatch"):
        prefilter_by_guard(filtered, {}, "dedup_by_concept", original_data=data)


def test_terminal_failure_count_reflects_observe_filtered_records(tmp_path):
    # Two of five records are observe-dropped; the remaining three all fail. The
    # terminal-failure error must count the three records actually processed, not
    # the five pre-observe inputs — otherwise operators chase phantom failures.
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": "sg-1", "content": {"tag": {"label": "B"}, "code": {"block": "y"}}},
        {"source_guid": "sg-2", "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-3", "content": {"tag": {"label": "D"}, "code": {"block": "w"}}},
        {"source_guid": "sg-4", "content": {"code": {"block": "v"}}},
    ]
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE)
    with pytest.raises(RuntimeError, match="3 active input"):
        _run_capture(pipeline, data, tmp_path, process_return=([], CollectionStats(failed=3)))


def test_all_records_observe_skipped_writes_node_level_skip(tmp_path):
    # Every record is observe-dropped → the action produces no output, so a
    # node-level SKIPPED disposition must be written for downstream cascade-skip.
    data = [
        {"source_guid": "sg-0", "content": {"code": {"block": "z"}}},
        {"source_guid": "sg-1", "content": {"code": {"block": "v"}}},
    ]
    storage = MagicMock()
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE, storage_backend=storage)
    _run_capture(pipeline, data, tmp_path, process_return=([], CollectionStats()))

    node_skips = [
        call
        for call in storage.set_disposition.call_args_list
        if call.args[1] == NODE_LEVEL_RECORD_ID and call.args[2] == DISPOSITION_SKIPPED
    ]
    assert node_skips, "expected a node-level SKIPPED disposition for the all-skipped action"


def test_observe_skipped_without_source_guid_logs_warning(tmp_path, caplog):
    # Records skipped without a source_guid get no per-record disposition (nothing
    # to key it on). That must be surfaced, not silently dropped, so operators can
    # tell "no skips" from "skips with no disposition written".
    data = [
        {"source_guid": "sg-0", "content": {"tag": {"label": "A"}, "code": {"block": "x"}}},
        {"source_guid": None, "content": {"code": {"block": "z"}}},
        {"source_guid": None, "content": {"code": {"block": "v"}}},
    ]
    storage = MagicMock()
    pipeline = _build_file_mode_pipeline(OBSERVE_SCOPE, storage_backend=storage)

    # The agent_actions root logger sets propagate=False (LoggingBridgeHandler),
    # so caplog (hooked to the Python root) needs propagation re-enabled.
    aa_logger = logging.getLogger("agent_actions")
    orig_propagate = aa_logger.propagate
    aa_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger="agent_actions.workflow.pipeline"):
            _run_capture(pipeline, data, tmp_path)
    finally:
        aa_logger.propagate = orig_propagate

    assert any("no source_guid" in rec.message for rec in caplog.records)
    # No per-record disposition is written for the guid-less skips.
    storage.set_dispositions_batch.assert_not_called()
