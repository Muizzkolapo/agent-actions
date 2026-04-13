"""Tests for FILE-mode source_mapping inference (4-tier cascade).

Covers the fix for the shared-source_guid lineage bug: when a FILE tool
changes cardinality and all inputs share the same source_guid, the old
inference broadcast all outputs to input[0].  The new inference uses
node_id matching, content fingerprinting, and improved positional fallback.
"""

from __future__ import annotations

from agent_actions.workflow.pipeline_file_mode import (
    _content_fingerprint,
    _infer_source_mapping,
    _match_by_content,
    _match_by_node_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(idx: int, *, source_guid: str = "sg-A", node_id: str | None = None) -> dict:
    """Build a minimal input record with framework metadata."""
    item: dict = {
        "content": {"question": f"Q{idx}", "idx": idx},
        "source_guid": source_guid,
        "lineage": [f"upstream_{idx}"],
    }
    if node_id is not None:
        item["node_id"] = node_id
    return item


def _make_flat_input(idx: int) -> dict:
    """Build a minimal observe-filtered (flat) input dict."""
    return {"question": f"Q{idx}", "idx": idx}


# ===================================================================
# Tier 1: Identity
# ===================================================================


class TestIdentityMapping:
    """When output_count == input_count, return {i: i} unconditionally."""

    def test_same_count_returns_identity(self):
        inputs = [_make_input(i) for i in range(5)]
        result = _infer_source_mapping(5, inputs, "action")
        assert result == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}

    def test_same_count_ignores_raw_outputs(self):
        """Identity check fires first regardless of node_id availability."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(3)]
        outputs = [{"node_id": f"n{2 - i}"} for i in range(3)]  # reversed
        result = _infer_source_mapping(3, inputs, "action", raw_outputs=outputs)
        # Identity wins because counts match, even though node_ids differ.
        assert result == {0: 0, 1: 1, 2: 2}


# ===================================================================
# Tier 2: Node-ID matching
# ===================================================================


class TestNodeIdMatching:
    """Match outputs to inputs by node_id when tool passes records through."""

    def test_dedup_with_node_ids(self):
        """7 inputs, 6 outputs — dedup drops one record."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(7)]
        # Tool drops input[3]
        outputs = [{"node_id": f"n{i}", "question": f"Q{i}"} for i in range(7) if i != 3]
        result = _infer_source_mapping(6, inputs, "dedup", raw_outputs=outputs)
        assert result == {0: 0, 1: 1, 2: 2, 3: 4, 4: 5, 5: 6}

    def test_reorder_with_node_ids(self):
        """Outputs are same records but in different order."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(4)]
        outputs = [
            {"node_id": "n3"},
            {"node_id": "n0"},
            {"node_id": "n2"},
        ]
        result = _infer_source_mapping(3, inputs, "filter", raw_outputs=outputs)
        assert result == {0: 3, 1: 0, 2: 2}

    def test_partial_node_ids_falls_through(self):
        """Some outputs missing node_id → returns None."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(4)]
        outputs = [{"node_id": "n0"}, {"question": "Q2"}, {"node_id": "n3"}]
        result = _match_by_node_id(outputs, inputs)
        assert result is None

    def test_no_node_ids_falls_through(self):
        """No outputs have node_id → returns None."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(3)]
        outputs = [{"question": "Q0"}, {"question": "Q1"}]
        result = _match_by_node_id(outputs, inputs)
        assert result is None

    def test_unknown_node_id_falls_through(self):
        """Output carries a node_id not in inputs → returns None."""
        inputs = [_make_input(i, node_id=f"n{i}") for i in range(3)]
        outputs = [{"node_id": "n0"}, {"node_id": "n_unknown"}]
        result = _match_by_node_id(outputs, inputs)
        assert result is None

    def test_inputs_without_node_ids_falls_through(self):
        """Inputs have no node_ids → returns None."""
        inputs = [_make_input(i) for i in range(3)]  # no node_id
        outputs = [{"node_id": "n0"}, {"node_id": "n1"}]
        result = _match_by_node_id(outputs, inputs)
        assert result is None


# ===================================================================
# Tier 3: Content fingerprint matching
# ===================================================================


class TestContentMatching:
    """Match outputs to inputs by content fingerprint."""

    def test_dedup_with_observe_filtered_data(self):
        """Observe-filtered flat dicts: dedup drops one, content matches."""
        tool_inputs = [_make_flat_input(i) for i in range(7)]
        # Tool drops input[4]
        raw_outputs = [_make_flat_input(i) for i in range(7) if i != 4]
        result = _match_by_content(raw_outputs, tool_inputs)
        assert result == {0: 0, 1: 1, 2: 2, 3: 3, 4: 5, 5: 6}

    def test_filter_with_reorder(self):
        """Outputs are a reordered subset — non-sequential mapping."""
        tool_inputs = [_make_flat_input(i) for i in range(5)]
        # Tool returns inputs [3, 0, 4] in that order
        raw_outputs = [_make_flat_input(3), _make_flat_input(0), _make_flat_input(4)]
        result = _match_by_content(raw_outputs, tool_inputs)
        assert result == {0: 3, 1: 0, 2: 4}

    def test_duplicate_content_first_unclaimed_wins(self):
        """Two inputs with identical content — first unclaimed is used."""
        tool_inputs = [{"q": "same"}, {"q": "same"}, {"q": "unique"}]
        raw_outputs = [{"q": "same"}, {"q": "unique"}]
        result = _match_by_content(raw_outputs, tool_inputs)
        # First "same" output claims input[0], "unique" claims input[2].
        assert result == {0: 0, 1: 2}

    def test_transformed_content_falls_through(self):
        """Tool modified field values — no fingerprint match → None."""
        tool_inputs = [{"q": "A", "score": 0.9}, {"q": "B", "score": 0.3}]
        raw_outputs = [{"q": "A", "score": 0.95}]  # score changed
        result = _match_by_content(raw_outputs, tool_inputs)
        assert result is None

    def test_new_content_falls_through(self):
        """Tool generated entirely new content → None."""
        tool_inputs = [{"q": "A"}, {"q": "B"}]
        raw_outputs = [{"q": "C"}]  # not from any input
        result = _match_by_content(raw_outputs, tool_inputs)
        assert result is None

    def test_all_inputs_claimed_falls_through(self):
        """More outputs matching same fingerprint than available inputs → None."""
        tool_inputs = [{"q": "same"}]
        raw_outputs = [{"q": "same"}, {"q": "same"}]  # 2 outputs but only 1 input
        result = _match_by_content(raw_outputs, tool_inputs)
        assert result is None

    def test_empty_outputs(self):
        """Empty output list → empty mapping."""
        tool_inputs = [_make_flat_input(0)]
        result = _match_by_content([], tool_inputs)
        assert result == {}

    def test_non_dict_output_falls_through(self):
        """Non-dict in output → None."""
        tool_inputs = [_make_flat_input(0)]
        result = _match_by_content(["not a dict"], tool_inputs)  # type: ignore[list-item]
        assert result is None


# ===================================================================
# Content fingerprint function
# ===================================================================


class TestContentFingerprint:
    """Unit tests for _content_fingerprint."""

    def test_flat_dict_returns_hex_digest(self):
        fp = _content_fingerprint({"b": 2, "a": 1})
        assert len(fp) == 64  # sha256 hex digest
        assert all(c in "0123456789abcdef" for c in fp)

    def test_wrapped_dict_fingerprints_content(self):
        """When item has a content dict, fingerprint the content — not the wrapper."""
        fp_wrapped = _content_fingerprint({"content": {"b": 2, "a": 1}, "node_id": "n0"})
        fp_flat = _content_fingerprint({"b": 2, "a": 1})
        assert fp_wrapped == fp_flat

    def test_strips_reserved_fields(self):
        fp_with = _content_fingerprint({"question": "Q1", "source_guid": "sg", "node_id": "n0"})
        fp_without = _content_fingerprint({"question": "Q1"})
        assert fp_with == fp_without

    def test_deterministic(self):
        """Same content, different insertion order → same fingerprint."""
        fp1 = _content_fingerprint({"a": 1, "b": 2})
        fp2 = _content_fingerprint({"b": 2, "a": 1})
        assert fp1 == fp2

    def test_empty_dict(self):
        fp = _content_fingerprint({})
        assert len(fp) == 64  # valid hash even for empty content


# ===================================================================
# Tier 4: Heuristic fallback
# ===================================================================


class TestHeuristicFallback:
    """When node_id and content matching both fail."""

    def test_shared_guid_reduction_uses_positional(self):
        """Reduction with shared source_guid → positional {i: i}."""
        inputs = [_make_input(i) for i in range(7)]
        # No node_ids in outputs, content doesn't match (transformed).
        outputs = [{"transformed": f"T{i}"} for i in range(5)]
        tool_inputs = [_make_flat_input(i) for i in range(7)]
        result = _infer_source_mapping(
            5,
            inputs,
            "transform_filter",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}

    def test_shared_guid_expansion_uses_broadcast(self):
        """Expansion with shared source_guid → broadcast {i: 0}."""
        inputs = [_make_input(i) for i in range(3)]
        outputs = [{"new": f"N{i}"} for i in range(5)]
        tool_inputs = [_make_flat_input(i) for i in range(3)]
        result = _infer_source_mapping(
            5,
            inputs,
            "expand",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    def test_no_source_guids_reduction_uses_positional(self):
        """Reduction with no source_guids → positional."""
        inputs = [{"content": {"q": f"Q{i}"}} for i in range(5)]
        outputs = [{"new": f"N{i}"} for i in range(3)]
        tool_inputs = [{"q": f"Q{i}"} for i in range(5)]
        result = _infer_source_mapping(
            3,
            inputs,
            "filter",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0, 1: 1, 2: 2}

    def test_mixed_guids_uses_broadcast_with_warning(self, caplog):
        """Mixed source_guids → broadcast to first."""
        inputs = [
            _make_input(0, source_guid="sg-A"),
            _make_input(1, source_guid="sg-B"),
            _make_input(2, source_guid="sg-C"),
        ]
        outputs = [{"new": "N0"}]
        tool_inputs = [{"q": "Q0"}, {"q": "Q1"}, {"q": "Q2"}]
        result = _infer_source_mapping(
            1,
            inputs,
            "aggregate",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0}


# ===================================================================
# Integration: full cascade
# ===================================================================


class TestFullCascade:
    """End-to-end tests through _infer_source_mapping showing tier priority."""

    def test_node_id_wins_over_content(self):
        """When both node_id and content could match, node_id is tried first."""
        inputs = [
            _make_input(0, node_id="n0"),
            _make_input(1, node_id="n1"),
            _make_input(2, node_id="n2"),
        ]
        # Output carries node_ids — node_id matching should fire.
        outputs = [{"node_id": "n2", "question": "Q2"}, {"node_id": "n0", "question": "Q0"}]
        tool_inputs = [_make_flat_input(0), _make_flat_input(1), _make_flat_input(2)]
        result = _infer_source_mapping(
            2,
            inputs,
            "filter",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        # node_id matching gives the correct non-sequential mapping.
        assert result == {0: 2, 1: 0}

    def test_content_fires_when_node_id_absent(self):
        """Observe-filtered outputs (no node_id) → content matching fires."""
        inputs = [_make_input(i) for i in range(5)]
        tool_inputs = [_make_flat_input(i) for i in range(5)]
        # Tool drops input[2], returns flat dicts without node_id.
        outputs = [_make_flat_input(i) for i in range(5) if i != 2]
        result = _infer_source_mapping(
            4,
            inputs,
            "dedup",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0, 1: 1, 2: 3, 3: 4}

    def test_heuristic_fires_when_both_fail(self):
        """Transformed content + no node_ids → falls to positional."""
        inputs = [_make_input(i) for i in range(4)]
        tool_inputs = [_make_flat_input(i) for i in range(4)]
        # All-new content, no node_ids.
        outputs = [{"transformed": f"X{i}"} for i in range(3)]
        result = _infer_source_mapping(
            3,
            inputs,
            "transform",
            raw_outputs=outputs,
            tool_inputs=tool_inputs,
        )
        assert result == {0: 0, 1: 1, 2: 2}

    def test_backward_compat_no_raw_outputs(self):
        """When raw_outputs is not provided, falls through to heuristic."""
        inputs = [_make_input(i) for i in range(5)]
        result = _infer_source_mapping(3, inputs, "legacy")
        # Shared guid, reduction → positional.
        assert result == {0: 0, 1: 1, 2: 2}

    def test_the_reported_bug_scenario(self):
        """Reproduce the exact bug from the report: 7 in, 6 out, shared guid.

        Before fix: all outputs → input[0].
        After fix: content matching → each output to its correct input.
        """
        questions = [
            "security isolation violations",
            "capability negotiation extensibility",
            "multiple MCP servers",
            "unique ID in requests",
            "HTTP vs STDIO",
            "structure spec compliance",
            "security isolation violations v2",  # duplicate, from different page
        ]
        inputs = [
            _make_input(i, source_guid="sg-A" if i < 6 else "sg-B", node_id=f"flatten_{i}")
            for i in range(7)
        ]
        # Observe-filtered tool inputs (flat dicts, no node_id).
        tool_inputs = [{"question": q, "idx": i} for i, q in enumerate(questions)]
        # Dedup drops the last record (duplicate of [0]).
        raw_outputs = [{"question": q, "idx": i} for i, q in enumerate(questions[:6])]

        result = _infer_source_mapping(
            6,
            inputs,
            "dedup",
            raw_outputs=raw_outputs,
            tool_inputs=tool_inputs,
        )
        # Each output maps to its corresponding input — NOT all to input[0].
        assert result == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
