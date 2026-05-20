"""Tests for DispositionGate — per-record idempotency gate for retry.

Tests cover: parent spec items 1, 2, 3, 7, 8, 9, 10, 11, 12, 15, 16.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_actions.processing.disposition_gate import (
    GATE_TERMINAL_DISPOSITIONS,
    DispositionGate,
    build_carry_forward,
)


def _make_record(guid: str | None = None, **extra: object) -> dict:
    rec: dict = {}
    if guid is not None:
        rec["source_guid"] = guid
    rec.update(extra)
    return rec


def _mock_backend(terminal_ids: set[str] | None = None) -> MagicMock:
    backend = MagicMock()
    backend.get_terminal_record_ids.return_value = terminal_ids or set()
    return backend


# ── Test 2: First run (no dispositions) processes all records ────────


class TestDispositionGateFirstRun:
    def test_no_backend_returns_all_records(self):
        gate = DispositionGate(storage_backend=None)
        records = [_make_record(f"r{i}") for i in range(10)]
        to_process, carry_ids = gate.filter(records, "action_a")
        assert to_process == records
        assert carry_ids == set()

    def test_no_dispositions_returns_all_records(self):
        """Spec test 2: first run processes all, zero extra queries."""
        backend = _mock_backend(terminal_ids=set())
        gate = DispositionGate(storage_backend=backend)
        records = [_make_record(f"r{i}") for i in range(10)]
        to_process, carry_ids = gate.filter(records, "action_a")
        assert to_process == records
        assert carry_ids == set()
        backend.get_terminal_record_ids.assert_called_once_with("action_a")


# ── Test 1: Records with SUCCESS disposition skipped on retry ────────


class TestDispositionGateRetry:
    def test_terminal_records_skipped(self):
        """Spec test 1: 9 with success, 1 cleared → 1 to process."""
        terminal = {f"r{i}" for i in range(9)}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)
        records = [_make_record(f"r{i}") for i in range(10)]

        to_process, carry_ids = gate.filter(records, "action_a")

        assert len(to_process) == 1
        assert to_process[0]["source_guid"] == "r9"
        assert carry_ids == terminal

    def test_all_terminal_returns_empty_to_process(self):
        terminal = {f"r{i}" for i in range(5)}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)
        records = [_make_record(f"r{i}") for i in range(5)]

        to_process, carry_ids = gate.filter(records, "action_a")

        assert len(to_process) == 0
        assert carry_ids == terminal


# ── Test 3: Records without source_guid always processed ────────────


class TestRecordsWithoutGuid:
    def test_no_guid_always_processed(self):
        """Spec test 3: records without source_guid flow through."""
        terminal = {"r0", "r1"}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)
        records = [
            _make_record("r0"),  # terminal → carry
            _make_record(None),  # no guid → process
            _make_record("r2"),  # not terminal → process
        ]

        to_process, carry_ids = gate.filter(records, "action_a")

        assert len(to_process) == 2
        guids = [r.get("source_guid") for r in to_process]
        assert None in guids
        assert "r2" in guids
        assert carry_ids == {"r0"}


# ── Tests 7, 8: Terminal set correctness ─────────────────────────────


class TestTerminalSetCorrectness:
    def test_deferred_is_not_terminal(self):
        """Spec test 7: DEFERRED records must be reprocessed."""
        assert "deferred" not in GATE_TERMINAL_DISPOSITIONS

    def test_failed_is_not_terminal(self):
        """Spec test 8: FAILED records must be reprocessed."""
        assert "failed" not in GATE_TERMINAL_DISPOSITIONS

    def test_exhausted_is_terminal(self):
        """Spec test 9: EXHAUSTED is gate-terminal."""
        assert "exhausted" in GATE_TERMINAL_DISPOSITIONS

    def test_all_expected_terminals_present(self):
        assert GATE_TERMINAL_DISPOSITIONS == frozenset({
            "success", "filtered", "skipped", "passthrough", "exhausted",
        })


# ── Test 9: EXHAUSTED cleared by retry, then gate lets through ───────


class TestExhaustedRetryCleared:
    def test_exhausted_gated_then_cleared(self):
        """Spec test 9: gate skips EXHAUSTED, then retry clears it."""
        # First: gate sees EXHAUSTED as terminal
        backend = _mock_backend(terminal_ids={"r1"})
        gate1 = DispositionGate(storage_backend=backend)
        records = [_make_record("r1")]
        _, carry_ids = gate1.filter(records, "action_a")
        assert carry_ids == {"r1"}

        # After retry clears disposition: new gate instance sees no terminals
        backend2 = _mock_backend(terminal_ids=set())
        gate2 = DispositionGate(storage_backend=backend2)
        to_process, carry_ids = gate2.filter(records, "action_a")
        assert len(to_process) == 1
        assert carry_ids == set()


# ── Test 10: SUCCESS + stale DEFERRED ────────────────────────────────


class TestMultipleDispositions:
    def test_success_plus_stale_deferred(self):
        """Spec test 10: record with both SUCCESS and DEFERRED → gated."""
        # get_terminal_record_ids only returns IDs with terminal dispositions.
        # A record with SUCCESS is in that set regardless of DEFERRED.
        backend = _mock_backend(terminal_ids={"r1"})
        gate = DispositionGate(storage_backend=backend)
        records = [_make_record("r1")]
        _, carry_ids = gate.filter(records, "action_a")
        assert carry_ids == {"r1"}


# ── Test 15: Cache — one query per action, not per file ──────────────


class TestCachePerformance:
    def test_one_query_per_action_cached_across_files(self):
        """Spec test 15: 5 actions × 10 files = 5 calls, not 50."""
        backend = _mock_backend(terminal_ids=set())
        gate = DispositionGate(storage_backend=backend)

        for action_idx in range(5):
            action = f"action_{action_idx}"
            for file_idx in range(10):
                records = [_make_record(f"r{file_idx}")]
                gate.filter(records, action)

        # One call per action, not per file
        assert backend.get_terminal_record_ids.call_count == 5

    def test_cache_reuses_terminal_ids_across_files(self):
        """When terminals exist, same IDs used for all files of that action."""
        backend = _mock_backend(terminal_ids={"r0", "r1"})
        gate = DispositionGate(storage_backend=backend)

        # File 1
        records1 = [_make_record("r0"), _make_record("r2")]
        to_process1, carry1 = gate.filter(records1, "action_a")
        assert carry1 == {"r0"}
        assert len(to_process1) == 1

        # File 2 — same action, different records
        records2 = [_make_record("r1"), _make_record("r3")]
        to_process2, carry2 = gate.filter(records2, "action_a")
        assert carry2 == {"r1"}
        assert len(to_process2) == 1

        # Only one SQL call total for this action
        backend.get_terminal_record_ids.assert_called_once_with("action_a")


# ── Test 16: All records failed + retry clears all ───────────────────


class TestAllFailedRetryCleared:
    def test_all_cleared_flows_through(self):
        """Spec test 16: after retry clears all, gate processes all."""
        backend = _mock_backend(terminal_ids=set())
        gate = DispositionGate(storage_backend=backend)
        records = [_make_record(f"r{i}") for i in range(10)]
        to_process, carry_ids = gate.filter(records, "action_a")
        assert len(to_process) == 10
        assert carry_ids == set()

    def test_instance_level_cache_fresh_per_run(self):
        """New gate instance = fresh cache (no stale data from prior run)."""
        # Run 1: all terminal
        backend1 = _mock_backend(terminal_ids={"r0", "r1"})
        gate1 = DispositionGate(storage_backend=backend1)
        _, carry1 = gate1.filter([_make_record("r0")], "action_a")
        assert carry1 == {"r0"}

        # Run 2: new instance, all cleared
        backend2 = _mock_backend(terminal_ids=set())
        gate2 = DispositionGate(storage_backend=backend2)
        to_process2, carry2 = gate2.filter([_make_record("r0")], "action_a")
        assert len(to_process2) == 1
        assert carry2 == set()


# ── Test 11: build_carry_forward reads prior output ──────────────────


class TestBuildCarryForward:
    def test_reads_from_prior_output(self):
        """Spec test 11: carry-forward reads from action's prior output."""
        prior = [
            {"source_guid": "r1", "score_quality": {"score": 0.9}},
            {"source_guid": "r2", "score_quality": {"score": 0.5}},
        ]
        backend = MagicMock()
        backend.read_target.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        backend.read_target.assert_called_once_with("action_b", "data.json")
        assert len(found) == 1
        assert found[0]["source_guid"] == "r1"
        assert found[0]["score_quality"] == {"score": 0.9}
        assert missing == set()

    def test_missing_prior_output_returns_all_as_missing(self):
        """Spec test 12: missing prior output → all carry_ids as missing."""
        backend = MagicMock()
        backend.read_target.side_effect = FileNotFoundError("no file")

        found, missing = build_carry_forward(
            carry_ids={"r1", "r2"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert found == []
        assert missing == {"r1", "r2"}

    def test_partial_match_returns_missing_ids(self):
        """Records not found in prior output are returned as missing."""
        prior = [{"source_guid": "r1", "data": "ok"}]
        backend = MagicMock()
        backend.read_target.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r1", "r2"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert len(found) == 1
        assert found[0]["source_guid"] == "r1"
        assert missing == {"r2"}

    def test_records_without_guid_in_prior_output_ignored(self):
        """Prior output records without source_guid are skipped in lookup."""
        prior = [
            {"source_guid": "r1", "data": "ok"},
            {"no_guid": True},
        ]
        backend = MagicMock()
        backend.read_target.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert len(found) == 1
        assert missing == set()

    def test_empty_carry_ids(self):
        """Edge case: empty carry_ids returns empty results."""
        backend = MagicMock()
        backend.read_target.return_value = [{"source_guid": "r1"}]

        found, missing = build_carry_forward(
            carry_ids=set(),
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert found == []
        assert missing == set()
