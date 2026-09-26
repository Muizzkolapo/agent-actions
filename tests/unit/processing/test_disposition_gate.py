"""Tests for DispositionGate — per-record idempotency gate for retry.

Tests cover: parent spec items 1, 2, 3, 7, 8, 9, 10, 11, 12, 15, 16.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_actions.processing.disposition_gate import (
    DispositionGate,
    build_carry_forward,
)
from agent_actions.storage.backend import TERMINAL_DISPOSITIONS


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
        assert "deferred" not in TERMINAL_DISPOSITIONS

    def test_failed_is_not_terminal(self):
        """Spec test 8: FAILED records must be reprocessed."""
        assert "failed" not in TERMINAL_DISPOSITIONS

    def test_exhausted_is_terminal(self):
        """Spec test 9: EXHAUSTED is gate-terminal."""
        assert "exhausted" in TERMINAL_DISPOSITIONS

    def test_all_expected_terminals_present(self):
        assert TERMINAL_DISPOSITIONS == frozenset(
            {
                "success",
                "filtered",
                "skipped",
                "passthrough",
                "exhausted",
            }
        )


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
    def test_rows_come_back_in_stored_order(self):
        """These rows are written straight back into the file they came from, so
        their order is the file's, not the carry-id set's iteration order."""
        prior = [{"source_guid": f"r{i}"} for i in range(6)]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, _missing = build_carry_forward(
            carry_ids={"r4", "r1", "r5", "r0"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert [r["source_guid"] for r in found] == ["r0", "r1", "r4", "r5"]

    def test_the_last_of_several_rows_sharing_an_identity_is_the_one_kept(self):
        """Several stored rows can share a source_guid. Carry-forward keeps one, and
        keeps the last — which is what the guid-keyed mapping this replaced did.
        Whether one row is the right answer at all is 615; pinned here so that
        question stays open rather than being closed by accident."""
        prior = [
            {"source_guid": "a", "row": "a-first"},
            {"source_guid": "b", "row": "b-only"},
            {"source_guid": "a", "row": "a-last"},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"a", "b"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert [r["row"] for r in found] == ["b-only", "a-last"]
        assert missing == set()

    def test_a_carry_id_resolves_through_the_rows_it_produced(self):
        """An action minting an identity per row holds none carrying its input's,
        so matching on source_guid alone finds nothing and the input is re-queued
        and re-split. Every row the input produced comes back, not one."""
        prior = [
            {"source_guid": "m0", "producer_source_guids": ["r0"]},
            {"source_guid": "m1", "producer_source_guids": ["r0"]},
            {"source_guid": "m2", "producer_source_guids": ["r1"]},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r0"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0"},
        )

        assert [r["source_guid"] for r in found] == ["m0", "m1"]
        assert missing == set()

    def test_rows_matched_either_way_come_back_in_stored_order(self):
        """One carry id names a stored row and another names a producer. The rows
        are written back into the file they came from, so a producer match must not
        append after the direct ones."""
        prior = [
            {"source_guid": "m0", "producer_source_guids": ["r0"]},
            {"source_guid": "r1"},
            {"source_guid": "m1", "producer_source_guids": ["r0"]},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, _missing = build_carry_forward(
            carry_ids={"r0", "r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0", "r1"},
        )

        assert [r["source_guid"] for r in found] == ["m0", "r1", "m1"]

    def test_a_carry_id_no_row_accounts_for_is_still_reported_missing(self):
        """The caller re-queues what comes back missing. Counting a producer match
        the store does not hold would drop the record silently instead."""
        prior = [{"source_guid": "m0", "producer_source_guids": ["r0"]}]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r0", "r9"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0", "r9"},
        )

        assert [r["source_guid"] for r in found] == ["m0"]
        assert missing == {"r9"}

    def test_two_rows_sharing_an_identity_still_collapse_to_the_last(self):
        """The rule the direct match states and the producer match must not break: two
        stored rows can share a source_guid, and handing back both writes a duplicate
        identity the checkpoint table cannot even hold. The repair path documents
        producing exactly that state."""
        prior = [
            {"source_guid": "m0", "producer_source_guids": ["r1"], "row": "stale"},
            {"source_guid": "m0", "producer_source_guids": ["r1"], "row": "fresh"},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, _missing = build_carry_forward(
            carry_ids={"r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r1"},
        )

        assert [r["row"] for r in found] == ["fresh"]

    def test_a_producers_several_rows_all_come_back(self):
        """Collapsing by identity must not collapse a producer's distinct rows: they
        carry different guids, and the input is the whole group's only identity."""
        prior = [
            {"source_guid": "m0", "producer_source_guids": ["r0"]},
            {"source_guid": "m1", "producer_source_guids": ["r0"]},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, _missing = build_carry_forward(
            carry_ids={"r0"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0"},
        )

        assert [r["source_guid"] for r in found] == ["m0", "m1"]

    def test_a_stored_row_identity_does_not_resolve_through_producers(self):
        """The two callers pass different kinds of id. A repair names stored ROWS; the
        gate names INPUTS. A producer index is only meaningful for inputs, so a repair's
        ids must not match one, or a row is handed back while the repair rewrites it —
        two stored rows under one source_guid."""
        prior = [
            {"source_guid": "in0", "producer_source_guids": ["in1"], "v": "TOTAL"},
            {"source_guid": "in1", "v": "row"},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        # `in1` here is a stored row identity the repair named, NOT an input of this run.
        found, _missing = build_carry_forward(
            carry_ids={"in1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert [r["source_guid"] for r in found] == ["in1"]

    def test_a_row_is_not_carried_when_only_some_of_its_producers_are(self):
        """A collapse row is rebuilt by whichever of its inputs this run reprocesses, so
        carrying it while one producer is re-queued leaves the stale row beside the fresh
        one."""
        prior = [{"source_guid": "in0", "producer_source_guids": ["in1", "in2"], "v": "TOTAL"}]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, _missing = build_carry_forward(
            carry_ids={"in1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"in1"},
            reprocessing={"in2"},
        )

        assert found == [], f"carried a row a re-queued producer rebuilds: {found}"

    def test_a_dropped_rows_other_producers_are_re_queued(self):
        """A row whose producers straddle the boundary is not carried — the tool sees only
        the reprocessed half, so it cannot rebuild it. Its carried producers must then be
        re-queued, or the row is never rebuilt and is gone from stored output. Re-queueing
        one makes every row naming it rebuilt in turn, so a sibling row that would carry
        it must be dropped too, or the rebuild duplicates."""
        prior = [
            {"source_guid": "m0", "producer_source_guids": ["in1"], "v": "in1 alone"},
            {"source_guid": "m1", "producer_source_guids": ["in1", "in2"], "v": "in1+in2"},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"in1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"in1"},
            reprocessing={"in2"},
        )

        assert missing == {"in1"}, "in1 was not re-queued, so the in1+in2 row is never rebuilt"
        assert found == [], f"carried a row the rebuild will produce again: {found}"

    def test_a_row_carrying_no_identity_is_skipped_not_raised(self):
        """Guid-less prior-output rows are an expected input, as the test below pins. One
        naming producers must not abort the action on a subscript."""
        prior = [{"producer_source_guids": ["r0"], "v": "no guid"}, {"source_guid": "r0"}]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r0"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0"},
        )

        assert [r.get("source_guid") for r in found] == ["r0"]
        assert missing == set()

    def test_a_row_is_returned_once_when_it_matches_both_ways(self):
        """A row whose own identity is carried and whose producer is carried too —
        a repair naming an input beside a row of it. Returned twice it would be
        written twice, duplicating the row the rewrite is meant to replace."""
        prior = [{"source_guid": "m0", "producer_source_guids": ["r0"]}]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"m0", "r0"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
            produced_by={"r0"},
        )

        assert [r["source_guid"] for r in found] == ["m0"]
        assert missing == set()

    def test_an_ordinary_one_to_one_row_still_resolves_by_its_own_identity(self):
        """The 1:1 path, which is most rows: no producer recorded, and resolution by
        source_guid unchanged. A regression guard on the common case, not on the
        producer logic — it passes before and after the fix."""
        prior = [{"source_guid": "r1", "data": "ok"}, {"source_guid": "r2"}]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert [r["source_guid"] for r in found] == ["r1"]
        assert missing == set()

    def test_reads_from_prior_output(self):
        """Spec test 11: carry-forward reads from action's prior output."""
        prior = [
            {"source_guid": "r1", "score_quality": {"score": 0.9}},
            {"source_guid": "r2", "score_quality": {"score": 0.5}},
        ]
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = prior

        found, missing = build_carry_forward(
            carry_ids={"r1"},
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        backend.read_target_for_rewrite.assert_called_once_with("action_b", "data.json")
        assert len(found) == 1
        assert found[0]["source_guid"] == "r1"
        assert found[0]["score_quality"] == {"score": 0.9}
        assert missing == set()

    def test_missing_prior_output_returns_all_as_missing(self):
        """Spec test 12: missing prior output → all carry_ids as missing."""
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no file")

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
        backend.read_target_for_rewrite.return_value = prior

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
        backend.read_target_for_rewrite.return_value = prior

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
        backend.read_target_for_rewrite.return_value = [{"source_guid": "r1"}]

        found, missing = build_carry_forward(
            carry_ids=set(),
            action_name="action_b",
            relative_path="data.json",
            storage_backend=backend,
        )

        assert found == []
        assert missing == set()
