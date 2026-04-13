"""Tests for FILE-mode source mapping via node_id (NiFi-inspired).

The framework preserves node_id through the observe filter. Tools receive
full records with identity. The framework matches outputs to inputs by
node_id — one approach, no heuristics.
"""

from __future__ import annotations

from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _input(idx: int, *, node_id: str | None = None) -> dict:
    """Build a minimal input record with framework metadata."""
    item: dict = {
        "source_guid": "sg-A",
        "content": {"question": f"Q{idx}", "idx": idx},
        "lineage": [f"upstream_{idx}"],
    }
    if node_id is not None:
        item["node_id"] = node_id
    return item


# ===================================================================
# Core: node_id matching
# ===================================================================


class TestNodeIdMatching:
    """The one approach: match outputs to inputs by node_id."""

    def test_passthrough_dedup_drops_middle_record(self):
        """7 inputs, tool drops record [3], 6 outputs with node_id intact."""
        inputs = [_input(i, node_id=f"flatten_q{i}") for i in range(7)]
        outputs = [{"node_id": f"flatten_q{i}", "question": f"Q{i}"} for i in range(7) if i != 3]
        mapping = _resolve_source_mapping(outputs, inputs, "dedup")
        assert mapping == {0: 0, 1: 1, 2: 2, 3: 4, 4: 5, 5: 6}

    def test_passthrough_filter_reorders(self):
        """Tool returns records [4, 1, 0] — reordered subset."""
        inputs = [_input(i, node_id=f"n{i}") for i in range(5)]
        outputs = [{"node_id": "n4"}, {"node_id": "n1"}, {"node_id": "n0"}]
        mapping = _resolve_source_mapping(outputs, inputs, "filter")
        assert mapping == {0: 4, 1: 1, 2: 0}

    def test_transform_preserves_identity(self):
        """Tool modifies content but keeps node_id — same count, matched."""
        inputs = [_input(i, node_id=f"n{i}") for i in range(3)]
        outputs = [
            {"node_id": "n0", "question": "Q0_UPPER"},
            {"node_id": "n1", "question": "Q1_UPPER"},
            {"node_id": "n2", "question": "Q2_UPPER"},
        ]
        mapping = _resolve_source_mapping(outputs, inputs, "transform")
        assert mapping == {0: 0, 1: 1, 2: 2}

    def test_single_record_passthrough(self):
        """1 input, 1 output with matching node_id."""
        inputs = [_input(0, node_id="n0")]
        outputs = [{"node_id": "n0", "result": "done"}]
        mapping = _resolve_source_mapping(outputs, inputs, "tool")
        assert mapping == {0: 0}


# ===================================================================
# New records: no node_id = no parent
# ===================================================================


class TestNewRecords:
    """Outputs without node_id are new records — fresh lineage, no parent."""

    def test_aggregation_creates_new_record(self):
        """Tool merges 5 inputs into 1 new record. No node_id on output."""
        inputs = [_input(i, node_id=f"n{i}") for i in range(5)]
        outputs = [{"summary": "aggregated result"}]
        mapping = _resolve_source_mapping(outputs, inputs, "aggregate")
        assert mapping == {}

    def test_expansion_creates_new_records(self):
        """Tool generates 5 new records from 1 input. No node_id on outputs."""
        inputs = [_input(0, node_id="n0")]
        outputs = [{"generated": f"item_{i}"} for i in range(5)]
        mapping = _resolve_source_mapping(outputs, inputs, "expand")
        assert mapping == {}

    def test_mixed_passthrough_and_new(self):
        """Some outputs have node_id (passthrough), some don't (new)."""
        inputs = [_input(i, node_id=f"n{i}") for i in range(3)]
        outputs = [
            {"node_id": "n0", "original": True},  # passthrough
            {"summary": "new record"},  # new
            {"node_id": "n2", "original": True},  # passthrough
        ]
        mapping = _resolve_source_mapping(outputs, inputs, "mixed")
        # Only indices 0 and 2 are in the mapping. Index 1 is a new record.
        assert mapping == {0: 0, 2: 2}

    def test_empty_outputs(self):
        """Tool returns empty list."""
        inputs = [_input(0, node_id="n0")]
        mapping = _resolve_source_mapping([], inputs, "tool")
        assert mapping == {}

    def test_empty_inputs(self):
        """No inputs (shouldn't happen in practice but handle gracefully)."""
        outputs = [{"result": "something"}]
        mapping = _resolve_source_mapping(outputs, [], "tool")
        assert mapping == {}


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Boundary conditions and defensive behavior."""

    def test_unknown_node_id_warns_and_treats_as_new(self):
        """Output has node_id not matching any input — treated as new record."""
        inputs = [_input(0, node_id="n0")]
        outputs = [{"node_id": "n_unknown", "data": "x"}]
        mapping = _resolve_source_mapping(outputs, inputs, "tool")
        assert mapping == {}

    def test_non_dict_output_skipped(self):
        """Non-dict items in output are skipped (no crash)."""
        inputs = [_input(0, node_id="n0")]
        outputs = ["not a dict", {"node_id": "n0", "data": "x"}]
        mapping = _resolve_source_mapping(outputs, inputs, "tool")
        # Only index 1 matched. Index 0 was a non-dict.
        assert mapping == {1: 0}

    def test_inputs_without_node_id(self):
        """Inputs have no node_id (first-stage data) — nothing to match."""
        inputs = [_input(i) for i in range(3)]  # no node_id
        outputs = [{"data": "x"}]
        mapping = _resolve_source_mapping(outputs, inputs, "tool")
        assert mapping == {}

    def test_non_string_node_id_skipped(self):
        """Output with non-string node_id is treated as new record."""
        inputs = [_input(0, node_id="n0")]
        outputs = [{"node_id": 42, "data": "x"}]
        mapping = _resolve_source_mapping(outputs, inputs, "tool")
        assert mapping == {}


# ===================================================================
# The reported bug scenario
# ===================================================================


class TestReportedBug:
    """Reproduce the exact scenario from the bug report."""

    def test_dedup_shared_guid_7_to_6(self):
        """7 records from same page (shared source_guid), dedup to 6.

        Before fix: all outputs mapped to input[0] (broadcast-to-first).
        After fix: each output matched to its specific input by node_id.
        """
        questions = [
            "security isolation violations",
            "capability negotiation extensibility",
            "multiple MCP servers",
            "unique ID in requests",
            "HTTP vs STDIO",
            "structure spec compliance",
            "security isolation violations v2",  # duplicate of [0]
        ]
        inputs = [
            {
                "source_guid": "sg-page1",
                "node_id": f"flatten_q{i}",
                "lineage": [f"flatten_q{i}"],
                "content": {"question": q, "idx": i},
            }
            for i, q in enumerate(questions)
        ]
        # Dedup drops record [6] (duplicate). Returns 6 with node_ids.
        outputs = [
            {"node_id": f"flatten_q{i}", "question": q, "idx": i}
            for i, q in enumerate(questions[:6])
        ]
        mapping = _resolve_source_mapping(outputs, inputs, "dedup")
        # Each output maps to its correct input — NOT all to input[0].
        assert mapping == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
