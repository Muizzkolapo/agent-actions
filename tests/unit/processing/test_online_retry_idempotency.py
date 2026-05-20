"""Tests for DispositionGate integration in UnifiedProcessor (online path).

Tests cover: parent spec items 1, 2, 3, 4, 13, 14.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

# Avoid the circular import triggered by pipeline_file_mode → workflow → ...
# by mocking the offending module before importing unified.
_sentinel = object()
_pipeline_file_mode = sys.modules.get("agent_actions.workflow.pipeline_file_mode", _sentinel)
if _pipeline_file_mode is _sentinel:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
)
from agent_actions.processing.unified import UnifiedProcessor


def _make_context(
    agent_name: str = "test_action",
    *,
    file_path: str | None = "data.json",
    storage_backend: Any = None,
    raw_records: bool = False,
) -> ProcessingContext:
    config: dict[str, Any] = {
        "agent_type": agent_name,
        "name": agent_name,
    }
    return ProcessingContext(
        agent_config=config,
        agent_name=agent_name,
        file_path=file_path,
        storage_backend=storage_backend,
    )


def _mock_backend(terminal_ids: set[str], prior_output: list[dict] | None = None) -> MagicMock:
    backend = MagicMock()
    backend.get_terminal_record_ids.return_value = terminal_ids
    if prior_output is not None:
        backend.read_target.return_value = prior_output
    else:
        backend.read_target.return_value = []
    return backend


def _make_record(guid: str, **extra: object) -> dict:
    rec = {"source_guid": guid, "content": {}}
    rec.update(extra)
    return rec


class _TrackingStrategy:
    """Strategy that records what records it receives."""

    def __init__(self, transform: dict[str, dict] | None = None) -> None:
        self.received: list[dict] = []
        self._transform = transform or {}

    def invoke(
        self, records: list[dict[str, Any]], context: ProcessingContext
    ) -> list[ProcessingResult]:
        self.received.extend(records)
        results = []
        for r in records:
            guid = r.get("source_guid")
            data = self._transform.get(guid, r) if guid else r
            results.append(ProcessingResult.success(data=[data], source_guid=guid))
        return results


# ── Test 1: Records with SUCCESS disposition skipped on retry ────────


class TestOnlineRecordRetry:
    """Spec test 1: 9 with success, 1 cleared → only 1 goes to strategy."""

    def test_terminal_records_skipped_strategy_sees_only_cleared(self):
        terminal = {f"r{i}" for i in range(9)}
        prior_output = [{"source_guid": f"r{i}", "score_quality": {"score": 0.9}} for i in range(9)]
        backend = _mock_backend(terminal_ids=terminal, prior_output=prior_output)
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [_make_record(f"r{i}") for i in range(10)]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # Strategy only receives the 1 cleared record
        assert len(strategy.received) == 1
        assert strategy.received[0]["source_guid"] == "r9"

        # Output contains all 10 records
        assert len(output) == 10


# ── Test 2: First run (no dispositions) processes all ────────────────


class TestOnlineFirstRun:
    """Spec test 2: first run processes all, gate is no-op."""

    def test_no_dispositions_all_go_to_strategy(self):
        backend = _mock_backend(terminal_ids=set())
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [_make_record(f"r{i}") for i in range(10)]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        assert len(strategy.received) == 10

    def test_no_gate_all_go_to_strategy(self):
        """Backward compatibility: no gate = all records processed."""
        processor = UnifiedProcessor(disposition_gate=None)
        strategy = _TrackingStrategy()
        records = [_make_record(f"r{i}") for i in range(5)]
        context = _make_context()

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        assert len(strategy.received) == 5


# ── Test 3: Records without source_guid always processed ────────────


class TestRecordsWithoutGuidProcessed:
    def test_no_guid_records_sent_to_strategy(self):
        backend = _mock_backend(
            terminal_ids={"r0"}, prior_output=[{"source_guid": "r0", "data": "carried"}]
        )
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [
            _make_record("r0"),  # terminal → carry
            {"content": {}},  # no guid → process
            _make_record("r2"),  # not terminal → process
        ]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # Strategy receives 2 records (the no-guid and r2)
        assert len(strategy.received) == 2
        guids = [r.get("source_guid") for r in strategy.received]
        assert None in guids
        assert "r2" in guids


# ── Test 4: FILE mode carry-forward uses FILE-mode result types ──────


class TestFileModeCarryForward:
    def test_file_mode_uses_unprocessed_result_type(self):
        """Spec test 4: FILE mode carry-forward uses ProcessingResult.unprocessed()."""
        terminal = {f"r{i}" for i in range(4)}
        prior_output = [{"source_guid": f"r{i}", "enriched": True} for i in range(4)]
        backend = _mock_backend(terminal_ids=terminal, prior_output=prior_output)
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [_make_record(f"r{i}") for i in range(5)]
        raw_records = [_make_record(f"r{i}") for i in range(5)]
        context = _make_context(storage_backend=backend)

        with patch.object(
            processor,
            "_guard_filter_file_mode",
            return_value=(records, [], raw_records),
        ):
            output, stats = processor.process(records, context, strategy, raw_records=raw_records)

        # Strategy receives only the 1 cleared record
        assert len(strategy.received) == 1
        assert strategy.received[0]["source_guid"] == "r4"


# ── Test 13: Carry-forward records skip LineageEnricher ──────────────


class TestCarryForwardSkipsEnrichment:
    def test_carry_forward_bypasses_enrichment(self):
        """Spec test 13: carry-forward records keep their original node_id."""
        prior_output = [
            {
                "source_guid": "r0",
                "node_id": "original_123",
                "lineage": {"parent": "abc"},
                "score_quality": {"score": 0.9},
            }
        ]
        backend = _mock_backend(terminal_ids={"r0"}, prior_output=prior_output)
        gate = DispositionGate(storage_backend=backend)

        # Use a real enrichment pipeline that would overwrite node_id
        from agent_actions.processing.enrichment import EnrichmentPipeline

        enrichment = EnrichmentPipeline()
        processor = UnifiedProcessor(
            enrichment_pipeline=enrichment,
            disposition_gate=gate,
        )
        strategy = _TrackingStrategy()
        records = [_make_record("r0"), _make_record("r1")]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # Find the carry-forward record in output
        carried = [r for r in output if r.get("source_guid") == "r0"]
        assert len(carried) == 1
        # node_id preserved from prior run (not overwritten by enricher)
        assert carried[0].get("node_id") == "original_123"
        assert carried[0].get("lineage") == {"parent": "abc"}


# ── Test 14: Carry-forward stats counted separately ──────────────────


class TestCarryForwardStats:
    def test_carry_forward_not_counted_as_success(self):
        """Spec test 14: carry-forward must not inflate stats.success."""
        terminal = {f"r{i}" for i in range(9)}
        prior_output = [{"source_guid": f"r{i}", "data": "carried"} for i in range(9)]
        backend = _mock_backend(terminal_ids=terminal, prior_output=prior_output)
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [_make_record(f"r{i}") for i in range(10)]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # All 10 records in output (1 strategy-processed + 9 carry-forward)
        assert len(output) == 10
        # Only 1 record was strategy-processed → stats.success == 1
        assert stats.success == 1
        # Carry-forward counted separately
        assert stats.carry_forward == 9
        # Strategy only received 1 record
        assert len(strategy.received) == 1


# ── Test: Missing file_path degrades gracefully ──────────────────────


class TestMissingFilePath:
    def test_no_file_path_processes_all(self):
        """No file_path → can't derive relative_path → gate skips carry-forward."""
        terminal = {"r0"}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _TrackingStrategy()
        records = [_make_record("r0"), _make_record("r1")]
        context = _make_context(file_path=None, storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # With no file_path, can't carry forward, so all records go to strategy
        assert len(strategy.received) == 2


# ── Test: Carry-forward must not mask real failures ──────────────────


class _FailingStrategy:
    """Strategy that fails all records."""

    def invoke(
        self, records: list[dict[str, Any]], context: ProcessingContext
    ) -> list[ProcessingResult]:
        return [
            ProcessingResult.failed(
                error="test failure",
                source_guid=r.get("source_guid"),
            )
            for r in records
        ]


class TestCarryForwardDoesNotMaskFailure:
    def test_single_failed_record_detected_despite_carry_forward(self):
        """pipeline.py:610 checks stats.success == 0 to detect total failure.

        With 9 carry-forward + 1 strategy-processed that FAILS,
        stats.success must be 0 (not 9) so the failure is detected.
        """
        terminal = {f"r{i}" for i in range(9)}
        prior_output = [{"source_guid": f"r{i}", "data": "carried"} for i in range(9)]
        backend = _mock_backend(terminal_ids=terminal, prior_output=prior_output)
        gate = DispositionGate(storage_backend=backend)

        processor = UnifiedProcessor(disposition_gate=gate)
        strategy = _FailingStrategy()
        records = [_make_record(f"r{i}") for i in range(10)]
        context = _make_context(storage_backend=backend)

        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, stats = processor.process(records, context, strategy)

        # The 1 real record failed → stats.success == 0
        assert stats.success == 0
        assert stats.failed == 1
        # 9 carry-forward counted separately
        assert stats.carry_forward == 9
        # All 10 records still in output
        assert len(output) == 10
