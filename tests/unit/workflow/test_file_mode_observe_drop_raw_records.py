"""FILE-mode observe-drop must not desync raw_records (spec 587).

When ``context_scope.observe`` drops records that lack an observed upstream
namespace — the shape produced by merging a guard-filtered source (e.g.
``tag_code_concept``) with an unfiltered one (``dedup_code_blocks``) — the pipeline
must pass ``raw_records`` ALIGNED to the observe-filtered survivors, not the full
pre-observe ``data``. Passing the full data desyncs the two arrays, and
``UnifiedProcessor``'s ``prefilter_by_guard`` asserts
``len(original_data) == len(data)`` — so the action crashes with a length-mismatch
``RuntimeError`` and every downstream action cascade-SKIPs.
"""

from unittest.mock import MagicMock, patch

from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def _build_file_mode_tool_pipeline(context_scope):
    return ProcessingPipeline(
        config=PipelineConfig(
            action_config={
                "kind": "tool",
                "granularity": "file",
                "run_mode": "online",
                "impl": "noop",
                "context_scope": context_scope,
            },
            action_name="dedup_by_concept",
            idx=0,
        ),
        processor_factory=object(),
    )


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
    pipeline = _build_file_mode_tool_pipeline({"observe": ["tag.label", "code.block"]})

    captured = {}

    def _capture(records, context, strategy, raw_records=None):
        captured["filtered"] = records
        captured["raw_records"] = raw_records
        return [], MagicMock()

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

    # observe dropped sg-2 and sg-4 → 3 survivors reach the processor.
    assert [r["source_guid"] for r in captured["filtered"]] == ["sg-0", "sg-1", "sg-3"]
    # raw_records is prefilter_by_guard's pre-observe alignment array; it must match
    # the survivors 1:1. Passing the full 5-record data (the bug) makes
    # len(original_data) != len(data) → length-mismatch RuntimeError.
    assert [r["source_guid"] for r in captured["raw_records"]] == ["sg-0", "sg-1", "sg-3"]
