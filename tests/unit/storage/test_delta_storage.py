"""Tests for delta storage — extraction, reconstruction, and edge cases.

Verifies that write_target stores only the current action's content namespace
and read_target reconstructs the full accumulated record transparently.
"""

import json

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _make_backend(tmp_path):
    """Create a backend with workflow_metadata support."""
    db_path = tmp_path / "agent_io" / "test.db"
    backend = SQLiteBackend(str(db_path), "test_workflow")
    backend.initialize()
    return backend


def _set_execution_order(backend, actions):
    """Store execution order in metadata."""
    backend.save_metadata("execution_order", json.dumps(actions))


class TestDeltaExtraction:
    """write_target extracts deltas — stores only the current action's namespace."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["action_1", "action_2", "action_3"])
        yield b
        b.close()

    def test_first_action_preserves_source(self, backend):
        """First action delta has {source, action_1} — source is preserved."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"title": "SQL Intro"},
                    "action_1": {"question": "What is SQL?"},
                },
            }
        ]
        backend.write_target("action_1", "file.json", data, is_first_action=True)

        # Check raw DB — should have source + action_1
        raw = backend._read_target_raw("action_1", "file.json")
        assert "source" in raw[0]["content"]
        assert "action_1" in raw[0]["content"]
        assert raw[0]["_delta_mode"] == "first"

    def test_subsequent_action_strips_to_delta(self, backend):
        """Non-first action stores only its own namespace."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"title": "SQL Intro"},
                    "action_1": {"question": "What is SQL?"},
                    "action_2": {"difficulty": "easy"},
                },
            }
        ]
        backend.write_target("action_2", "file.json", data)

        raw = backend._read_target_raw("action_2", "file.json")
        assert raw[0]["content"] == {"action_2": {"difficulty": "easy"}}
        assert raw[0]["_delta_mode"] == "delta"
        # source and action_1 are NOT stored — they're in upstream deltas
        assert "source" not in raw[0]["content"]
        assert "action_1" not in raw[0]["content"]

    def test_full_mode_preserves_all_content(self, backend):
        """Records tagged _delta_mode=full are stored as-is."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "_delta_mode": "full",
                "content": {
                    "source": {"title": "SQL Intro"},
                    "action_1": {"question": "What is SQL?"},
                    "action_2": {"difficulty": "easy"},
                },
            }
        ]
        backend.write_target("action_2", "file.json", data)

        raw = backend._read_target_raw("action_2", "file.json")
        assert len(raw[0]["content"]) == 3
        assert raw[0]["_delta_mode"] == "full"

    def test_record_without_content_stored_as_full(self, backend):
        """Records without a content dict are stored as full (test data, raw records)."""
        data = [{"id": 1, "value": "hello"}]
        backend.write_target("action_1", "file.json", data, is_first_action=True)

        raw = backend._read_target_raw("action_1", "file.json")
        assert raw[0]["_delta_mode"] == "full"
        assert raw[0]["id"] == 1

    def test_is_first_action_auto_detect(self, backend):
        """write_target with is_first_action=None detects from execution_order."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"title": "SQL"},
                    "action_1": {"q": "hi"},
                },
            }
        ]
        # Don't pass is_first_action — should auto-detect action_1 as first
        backend.write_target("action_1", "file.json", data)

        raw = backend._read_target_raw("action_1", "file.json")
        assert raw[0]["_delta_mode"] == "first"
        assert "source" in raw[0]["content"]


class TestDeltaReconstruction:
    """read_target reconstructs full records from upstream deltas."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["action_1", "action_2", "action_3"])
        yield b
        b.close()

    def _write_pipeline(self, backend):
        """Write a 3-action pipeline as deltas."""
        backend.write_target(
            "action_1",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                    },
                }
            ],
            is_first_action=True,
        )
        backend.write_target(
            "action_2",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": {"difficulty": "easy"},
                    },
                }
            ],
        )
        backend.write_target(
            "action_3",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": {"difficulty": "easy"},
                        "action_3": {"draft": "SQL is..."},
                    },
                }
            ],
        )

    def test_reconstruction_produces_full_record(self, backend):
        """read_target for final action returns full record with all upstream namespaces."""
        self._write_pipeline(backend)

        result = backend.read_target("action_3", "file.json")
        content_keys = sorted(result[0]["content"].keys())
        assert content_keys == ["action_1", "action_2", "action_3", "source"]
        assert result[0]["content"]["source"]["title"] == "SQL"
        assert result[0]["content"]["action_1"]["question"] == "What is SQL?"
        assert result[0]["content"]["action_2"]["difficulty"] == "easy"
        assert result[0]["content"]["action_3"]["draft"] == "SQL is..."

    def test_delta_mode_stripped_from_all_modes(self, backend):
        """_delta_mode never leaks to consumers — stripped from delta, first, and full."""
        self._write_pipeline(backend)

        for action in ["action_1", "action_2", "action_3"]:
            result = backend.read_target(action, "file.json")
            assert "_delta_mode" not in result[0], f"_delta_mode leaked in {action}"

    def test_reconstruction_cache_invalidated_on_write(self, backend):
        """Cache is cleared after write_target — subsequent read returns fresh data."""
        self._write_pipeline(backend)

        # First read — populates cache
        result1 = backend.read_target("action_3", "file.json")
        assert result1[0]["content"]["action_3"]["draft"] == "SQL is..."

        # Write new data for action_3
        backend.write_target(
            "action_3",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": {"difficulty": "easy"},
                        "action_3": {"draft": "UPDATED"},
                    },
                }
            ],
        )

        # Second read — must return updated data, not cached
        result2 = backend.read_target("action_3", "file.json")
        assert result2[0]["content"]["action_3"]["draft"] == "UPDATED"

    def test_missing_upstream_guid_not_flagged_as_incomplete(self, backend):
        """Upstream with data for other guids but not this one — partitioned, not incomplete."""
        # Write action_1 with a DIFFERENT guid (partitioned pipeline)
        backend.write_target(
            "action_1",
            "file.json",
            [
                {
                    "source_guid": "other_guid",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"title": "Other"}, "action_1": {"q": "Other"}},
                }
            ],
            is_first_action=True,
        )
        # Write action_3 with guid g1 — action_1 has data but NOT for g1
        backend.write_target(
            "action_3",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": {"difficulty": "easy"},
                        "action_3": {"draft": "SQL is..."},
                    },
                }
            ],
        )

        result = backend.read_target("action_3", "file.json")
        # Partitioned: upstream has other guids, not g1 — not flagged
        assert "_reconstruction_incomplete" not in result[0]
        assert "action_3" in result[0]["content"]


class TestGuardSkipTombstone:
    """Guard-skip tombstones (content[action] = None) work correctly with delta storage."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["action_1", "action_2", "action_3"])
        yield b
        b.close()

    def test_tombstone_stored_as_delta(self, backend):
        """Guard-skip tombstone stores {action_name: None} as delta."""
        # Write action_1 first
        backend.write_target(
            "action_1",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                    },
                }
            ],
            is_first_action=True,
        )

        # Write action_2 tombstone (guard-skipped)
        backend.write_target(
            "action_2",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "guard_skipped",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": None,
                    },
                }
            ],
        )

        # Raw DB should have only the null marker
        raw = backend._read_target_raw("action_2", "file.json")
        assert raw[0]["content"] == {"action_2": None}
        assert raw[0]["_delta_mode"] == "delta"

    def test_tombstone_reconstruction_includes_upstream(self, backend):
        """Reconstructed tombstone has all upstream content + null marker."""
        # Write action_1
        backend.write_target(
            "action_1",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                    },
                }
            ],
            is_first_action=True,
        )

        # Write guard-skip tombstone
        backend.write_target(
            "action_2",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "guard_skipped",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"question": "What is SQL?"},
                        "action_2": None,
                    },
                }
            ],
        )

        # Reconstruct — should have upstream + null marker
        result = backend.read_target("action_2", "file.json")
        assert result[0]["content"]["source"]["title"] == "SQL"
        assert result[0]["content"]["action_1"]["question"] == "What is SQL?"
        assert result[0]["content"]["action_2"] is None


class TestBackwardCompatibility:
    """Legacy records (no _delta_mode) work unchanged."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        yield b
        b.close()

    def test_legacy_records_returned_as_is(self, backend):
        """Records without _delta_mode are returned without reconstruction."""
        import sqlite3

        # Insert a legacy full record directly (no _delta_mode)
        legacy_data = [
            {
                "_state": "active",
                "source_guid": "g1",
                "content": {
                    "source": {"title": "SQL"},
                    "action_1": {"question": "What is SQL?"},
                },
            }
        ]
        conn = sqlite3.connect(str(backend.db_path))
        conn.execute(
            "INSERT INTO target_data (action_name, relative_path, data, record_count) "
            "VALUES (?, ?, ?, ?)",
            ("action_1", "file.json", json.dumps(legacy_data), 1),
        )
        conn.commit()
        conn.close()

        result = backend.read_target("action_1", "file.json")
        assert result[0]["content"]["source"]["title"] == "SQL"
        assert result[0]["content"]["action_1"]["question"] == "What is SQL?"
        assert "_delta_mode" not in result[0]


class TestMetadata:
    """save_metadata / load_metadata round-trip."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        yield b
        b.close()

    def test_save_load_round_trip(self, backend):
        """Metadata key-value round-trip works."""
        backend.save_metadata("my_key", "my_value")
        assert backend.load_metadata("my_key") == "my_value"

    def test_load_missing_returns_none(self, backend):
        """Missing key returns None, not error."""
        assert backend.load_metadata("nonexistent") is None

    def test_save_overwrites(self, backend):
        """Second save to same key overwrites."""
        backend.save_metadata("key", "v1")
        backend.save_metadata("key", "v2")
        assert backend.load_metadata("key") == "v2"

    def test_execution_order_stored_and_retrieved(self, backend):
        """Execution order survives save/load cycle."""
        order = ["a1", "a2", "a3"]
        backend.save_metadata("execution_order", json.dumps(order))
        loaded = json.loads(backend.load_metadata("execution_order"))
        assert loaded == order


class TestFormatVersionCheck:
    """Format version prevents silent corruption on downgrade."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["a1"])
        yield b
        b.close()

    def test_format_version_stored_on_first_write(self, backend):
        """First write_target stores format version in metadata."""
        backend.write_target(
            "a1",
            "f.json",
            [{"_state": "active", "content": {"a1": {"x": 1}}}],
            is_first_action=True,
        )
        ver = backend.load_metadata("storage_format_version")
        assert ver == "2"

    def test_old_code_rejects_delta_db(self, backend, tmp_path):
        """Code with lower version raises ConfigurationError on delta DB."""
        from agent_actions.errors.configuration import ConfigValidationError

        # Simulate a future version
        backend.save_metadata("storage_format_version", "99")

        with pytest.raises(ConfigValidationError, match="storage format version 99"):
            backend.read_target("a1", "f.json")

    def test_corrupt_version_raises(self, backend):
        """Non-integer version raises ConfigurationError."""
        from agent_actions.errors.configuration import ConfigValidationError

        backend.save_metadata("storage_format_version", "not_a_number")

        with pytest.raises(ConfigValidationError, match="Corrupt"):
            backend.read_target("a1", "f.json")


class TestPreviewReconstruction:
    """preview_target reconstructs deltas before pagination."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["action_1", "action_2"])
        yield b
        b.close()

    def test_preview_shows_full_content(self, backend):
        """preview_target shows reconstructed content, not raw deltas."""
        backend.write_target(
            "action_1",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"title": "SQL"}, "action_1": {"q": "hi"}},
                }
            ],
            is_first_action=True,
        )
        backend.write_target(
            "action_2",
            "file.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"title": "SQL"},
                        "action_1": {"q": "hi"},
                        "action_2": {"d": "easy"},
                    },
                }
            ],
        )

        result = backend.preview_target("action_2")
        records = result["records"]
        assert len(records) == 1
        # Should have all namespaces, not just action_2
        assert "source" in records[0]["content"]
        assert "action_1" in records[0]["content"]
        assert "action_2" in records[0]["content"]
        assert "_delta_mode" not in records[0]


# ---------------------------------------------------------------------------
# FILE-mode expansion and contraction through enrichment + delta storage
# ---------------------------------------------------------------------------


class TestFileToolExpansionDelta:
    """FILE-mode tools that expand 1→N records get stored as full (not delta).

    Expansion records get fresh source_guids in enrichment.py.
    These GUIDs don't exist in any upstream action, so delta reconstruction
    would fail. The enricher tags them _delta_mode="full" to prevent stripping.
    """

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["extract", "flatten", "classify"])
        yield b
        b.close()

    def _simulate_expansion_pipeline(self, backend):
        """Simulate: extract (3 records) → flatten (10 records, 1→N expansion)."""
        from unittest.mock import MagicMock

        from agent_actions.processing.enrichment import LineageEnricher
        from agent_actions.processing.types import ProcessingResult, ProcessingStatus

        # Step 1: Write extract action (3 records, first action)
        extract_records = [
            {
                "source_guid": f"original-{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"title": f"Page {i}"},
                    "extract": {"questions": [{"q": f"Q{j}"} for j in range(3)]},
                },
            }
            for i in range(3)
        ]
        backend.write_target("extract", "file.json", extract_records, is_first_action=True)

        # Step 2: Simulate flatten tool expanding 3→9 records
        # Each input record produces 3 output records (one per question)
        expanded_items = []
        for i, rec in enumerate(extract_records):
            for j, q in enumerate(rec["content"]["extract"]["questions"]):
                expanded_items.append(
                    {
                        "source_guid": rec["source_guid"],  # parent guid (will be replaced)
                        "target_id": f"tid-{i}-{j}",
                        "_state": "processed",
                        "_state_schema_version": 1,
                        "content": {
                            "source": rec["content"]["source"],
                            "extract": rec["content"]["extract"],
                            "flatten": {"question_text": q["q"], "index": j},
                        },
                    }
                )

        # Run through enrichment with is_expansion=True (like the real pipeline)
        result = ProcessingResult(
            data=expanded_items,
            status=ProcessingStatus.SUCCESS,
            is_expansion=True,
        )
        ctx = MagicMock()
        ctx.action_name = "flatten"
        ctx.agent_name = "flatten"
        ctx.is_first_stage = False
        ctx.source_data = extract_records
        ctx.record_index = 0
        ctx.agent_config = {}

        enricher = LineageEnricher()
        enriched = enricher.enrich(result, ctx)

        # Write enriched expansion records
        backend.write_target("flatten", "file.json", enriched.data)

        return enriched.data

    def test_expansion_records_stored_as_full(self, backend):
        """Expansion records (fresh GUIDs) must be stored as _delta_mode=full."""
        self._simulate_expansion_pipeline(backend)

        raw = backend._read_target_raw("flatten", "file.json")
        assert len(raw) == 9

        modes = {r.get("_delta_mode") for r in raw}
        assert modes == {"full"}, f"Expected all full, got: {modes}"

    def test_expansion_records_have_fresh_source_guids(self, backend):
        """Each expansion record has a unique source_guid, not the parent's."""
        enriched = self._simulate_expansion_pipeline(backend)

        guids = [r["source_guid"] for r in enriched]
        assert len(set(guids)) == 9, "Each expansion record should have a unique GUID"
        assert all(not g.startswith("original-") for g in guids), "GUIDs should be fresh UUIDs"

    def test_expansion_records_preserve_parent_guid(self, backend):
        """Expansion records carry parent_source_guid for lineage tracking."""
        enriched = self._simulate_expansion_pipeline(backend)

        for record in enriched:
            assert "parent_source_guid" in record, "Missing parent_source_guid"
            assert record["parent_source_guid"].startswith("original-")

    def test_expansion_read_returns_full_content(self, backend):
        """read_target for expansion records returns full content (no reconstruction needed)."""
        self._simulate_expansion_pipeline(backend)

        result = backend.read_target("flatten", "file.json")
        assert len(result) == 9

        for record in result:
            assert "source" in record["content"], "Missing source namespace"
            assert "extract" in record["content"], "Missing extract namespace"
            assert "flatten" in record["content"], "Missing flatten namespace"
            assert "_delta_mode" not in record, "_delta_mode leaked to consumer"

    def test_downstream_after_expansion_uses_delta(self, backend):
        """Action after expansion stores deltas (not full) for the expanded records."""
        enriched = self._simulate_expansion_pipeline(backend)

        # Simulate classify action processing the expanded records.
        # In the real pipeline, enrichment for a non-expansion action
        # does NOT set _delta_mode, so drop it from the simulated input.
        classify_records = []
        for rec in enriched:
            classify_records.append(
                {
                    **{k: v for k, v in rec.items() if k not in ("content", "_delta_mode")},
                    "content": {
                        **rec["content"],
                        "classify": {"difficulty": "medium"},
                    },
                }
            )

        backend.write_target("classify", "file.json", classify_records)

        raw = backend._read_target_raw("classify", "file.json")
        modes = {r.get("_delta_mode") for r in raw}
        assert "delta" in modes, f"Expected delta mode for downstream, got: {modes}"

    def test_downstream_reconstruction_uses_expansion_boundary(self, backend):
        """Records downstream of expansion reconstruct from the expansion point, not from the start.

        The expansion (flatten) creates new GUIDs. Actions before the expansion
        (summarize, extract) have the old GUIDs. Reconstruction for actions after
        flatten should start at flatten's full record — not try to find the new
        GUIDs in summarize/extract (where they don't exist).
        """
        enriched = self._simulate_expansion_pipeline(backend)

        # Write a downstream action that processes the expanded records
        classify_records = []
        for rec in enriched:
            classify_records.append(
                {
                    **{k: v for k, v in rec.items() if k not in ("content", "_delta_mode")},
                    "content": {
                        **rec["content"],
                        "classify": {"difficulty": "medium"},
                    },
                }
            )
        backend.write_target("classify", "file.json", classify_records)

        # Read classify — should reconstruct from flatten (full) + classify (delta)
        # Should NOT try to find these GUIDs in extract (they don't exist there)
        result = backend.read_target("classify", "file.json")
        assert len(result) == 9

        for record in result:
            # Must have flatten + classify content (from flatten's full + classify's delta)
            assert "flatten" in record["content"], "Missing flatten namespace"
            assert "classify" in record["content"], "Missing classify namespace"
            # Must have source + extract content (baked into flatten's full record)
            assert "source" in record["content"], "Missing source namespace"
            assert "extract" in record["content"], "Missing extract namespace"
            # Must NOT be flagged incomplete
            assert "_reconstruction_incomplete" not in record, (
                f"Record incorrectly flagged incomplete: {record.get('source_guid')}"
            )
            assert "_delta_mode" not in record


class TestFileToolContractionDelta:
    """FILE-mode tools that contract N→M records (M < N).

    Contraction tools (e.g., grouping 100 records into 5 batches) produce
    fewer output records than input. If output records have new GUIDs
    (from enrichment expansion path), they should be stored as full.
    If they reuse input GUIDs, they should be stored as delta.
    """

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["input_action", "group_action"])
        yield b
        b.close()

    def test_contraction_with_reused_guids_stores_delta(self, backend):
        """Tool that returns fewer records but reuses input GUIDs → delta storage."""
        # 5 input records
        input_records = [
            {
                "source_guid": f"g{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"id": i},
                    "input_action": {"value": f"v{i}"},
                },
            }
            for i in range(5)
        ]
        backend.write_target("input_action", "file.json", input_records, is_first_action=True)

        # Tool returns 3 records, reusing source_guids g0, g1, g2
        output_records = [
            {
                "source_guid": f"g{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"id": i},
                    "input_action": {"value": f"v{i}"},
                    "group_action": {"group": f"batch_{i}"},
                },
            }
            for i in range(3)
        ]
        backend.write_target("group_action", "file.json", output_records)

        raw = backend._read_target_raw("group_action", "file.json")
        modes = {r.get("_delta_mode") for r in raw}
        assert modes == {"delta"}, f"Expected delta for reused GUIDs, got: {modes}"

    def test_contraction_reconstruction_works(self, backend):
        """Contracted records reconstruct upstream content correctly."""
        input_records = [
            {
                "source_guid": f"g{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"id": i},
                    "input_action": {"value": f"v{i}"},
                },
            }
            for i in range(5)
        ]
        backend.write_target("input_action", "file.json", input_records, is_first_action=True)

        output_records = [
            {
                "source_guid": f"g{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"id": i},
                    "input_action": {"value": f"v{i}"},
                    "group_action": {"group": f"batch_{i}"},
                },
            }
            for i in range(3)
        ]
        backend.write_target("group_action", "file.json", output_records)

        result = backend.read_target("group_action", "file.json")
        assert len(result) == 3
        for i, rec in enumerate(result):
            assert rec["content"]["source"]["id"] == i
            assert rec["content"]["input_action"]["value"] == f"v{i}"
            assert rec["content"]["group_action"]["group"] == f"batch_{i}"
            assert "_delta_mode" not in rec


class TestForceFullParameter:
    """write_target(force_full=True) bypasses delta extraction entirely."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["a1", "a2"])
        yield b
        b.close()

    def test_force_full_stores_complete_content(self, backend):
        """force_full=True stores all content namespaces regardless of action."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"x": 1},
                    "a1": {"q": "hi"},
                    "a2": {"level": "easy"},
                },
            }
        ]
        backend.write_target("a2", "file.json", data, force_full=True)

        raw = backend._read_target_raw("a2", "file.json")
        assert raw[0]["_delta_mode"] == "full"
        assert len(raw[0]["content"]) == 3

    def test_force_full_records_read_without_reconstruction(self, backend):
        """force_full records are returned as-is, no upstream lookup."""
        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {
                    "source": {"x": 1},
                    "a1": {"q": "hi"},
                    "a2": {"level": "easy"},
                },
            }
        ]
        backend.write_target("a2", "file.json", data, force_full=True)

        result = backend.read_target("a2", "file.json")
        assert result[0]["content"]["source"]["x"] == 1
        assert result[0]["content"]["a1"]["q"] == "hi"
        assert "_delta_mode" not in result[0]


# ---------------------------------------------------------------------------
# E2E tests for every issue found during review
# Each test uses real SQLiteBackend, real data, no mocks.
# ---------------------------------------------------------------------------


class TestIssue2_ParallelPeers:
    """Parallel actions at the same level must NOT appear in each other's upstream."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        # Pipeline: source → [branch_a, branch_b] (parallel) → merge
        _set_execution_order(b, ["source_action", "branch_a", "branch_b", "merge_action"])
        # Dep graph from levels: branch_a and branch_b share the same deps
        dep_graph = {
            "source_action": [],
            "branch_a": ["source_action"],
            "branch_b": ["source_action"],
            "merge_action": ["source_action", "branch_a", "branch_b"],
        }
        b.save_metadata("dependency_graph", json.dumps(dep_graph))
        yield b
        b.close()

    def test_parallel_branches_dont_include_each_other(self, backend):
        """branch_a's upstream must NOT include branch_b (they're parallel peers)."""
        backend.write_target(
            "source_action",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"x": 1}, "source_action": {"data": "raw"}},
                }
            ],
            is_first_action=True,
        )
        backend.write_target(
            "branch_a",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source_action": {"data": "raw"},
                        "branch_a": {"score": 5},
                    },
                }
            ],
        )
        backend.write_target(
            "branch_b",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source_action": {"data": "raw"},
                        "branch_b": {"score": 8},
                    },
                }
            ],
        )

        # Read branch_a — should NOT contain branch_b's content
        result_a = backend.read_target("branch_a", "f.json")
        assert "branch_b" not in result_a[0]["content"], (
            "Parallel peer branch_b leaked into branch_a"
        )
        assert "source_action" in result_a[0]["content"]

        # Read branch_b — should NOT contain branch_a's content
        result_b = backend.read_target("branch_b", "f.json")
        assert "branch_a" not in result_b[0]["content"], (
            "Parallel peer branch_a leaked into branch_b"
        )

    def test_merge_action_gets_both_branches(self, backend):
        """merge_action depends on both branches — should have all namespaces."""
        backend.write_target(
            "source_action",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"x": 1}, "source_action": {"data": "raw"}},
                }
            ],
            is_first_action=True,
        )
        backend.write_target(
            "branch_a",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source_action": {"data": "raw"},
                        "branch_a": {"score": 5},
                    },
                }
            ],
        )
        backend.write_target(
            "branch_b",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source_action": {"data": "raw"},
                        "branch_b": {"score": 8},
                    },
                }
            ],
        )
        backend.write_target(
            "merge_action",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source_action": {"data": "raw"},
                        "branch_a": {"score": 5},
                        "branch_b": {"score": 8},
                        "merge_action": {"combined": 13},
                    },
                }
            ],
        )

        result = backend.read_target("merge_action", "f.json")
        assert "source_action" in result[0]["content"]
        assert "branch_a" in result[0]["content"]
        assert "branch_b" in result[0]["content"]
        assert "merge_action" in result[0]["content"]


class TestIssue3_VersionedActions:
    """Versioned actions (action_1, action_2, action_3) must be in the dep graph."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["summarize", "extract_1", "extract_2", "extract_3", "merge"])
        dep_graph = {
            "summarize": [],
            "extract_1": ["summarize"],
            "extract_2": ["summarize"],
            "extract_3": ["summarize"],
            "merge": ["summarize", "extract_1", "extract_2", "extract_3"],
        }
        b.save_metadata("dependency_graph", json.dumps(dep_graph))
        yield b
        b.close()

    def test_versioned_actions_have_correct_upstream(self, backend):
        """Each extract_N depends only on summarize, not on other extract_N peers."""
        backend.write_target(
            "summarize",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"title": "SQL"}, "summarize": {"summary": "about SQL"}},
                }
            ],
            is_first_action=True,
        )
        for i in range(1, 4):
            backend.write_target(
                f"extract_{i}",
                "f.json",
                [
                    {
                        "source_guid": "g1",
                        "_state": "processed",
                        "_state_schema_version": 1,
                        "content": {
                            "source": {"title": "SQL"},
                            "summarize": {"summary": "about SQL"},
                            f"extract_{i}": {"question": f"Q{i}"},
                        },
                    }
                ],
            )

        # Each extract_N should have source + summarize + its own namespace
        for i in range(1, 4):
            result = backend.read_target(f"extract_{i}", "f.json")
            assert "source" in result[0]["content"]
            assert "summarize" in result[0]["content"]
            assert f"extract_{i}" in result[0]["content"]
            # Should NOT have other extract peers
            for j in range(1, 4):
                if j != i:
                    assert f"extract_{j}" not in result[0]["content"], (
                        f"extract_{j} leaked into extract_{i}"
                    )


class TestIssue4_MetadataCacheInvalidation:
    """save_metadata must clear the in-memory cache so reads get fresh data."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        yield b
        b.close()

    def test_dep_graph_cache_cleared_on_save(self, backend):
        """Writing new dep graph invalidates the cached version."""
        # Write initial graph
        backend.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
        backend.save_metadata("execution_order", json.dumps(["a1", "a2"]))

        # Force cache population by reading
        backend.write_target(
            "a1",
            "f.json",
            [{"source_guid": "g1", "_state": "active", "content": {"a1": {"x": 1}}}],
            is_first_action=True,
        )
        backend.write_target(
            "a2",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "active",
                    "content": {"a1": {"x": 1}, "a2": {"y": 2}},
                }
            ],
        )

        result1 = backend.read_target("a2", "f.json")
        assert "a1" in result1[0]["content"]

        # Now update the dep graph to make a2 have NO deps
        backend.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": []}))

        # Read again — should use the NEW graph (no upstream for a2)
        result2 = backend.read_target("a2", "f.json")
        # a2's delta has only {a2: ...}, and with empty deps, no upstream is merged
        assert "a2" in result2[0]["content"]


class TestIssue6_MissingSourceGuid:
    """Records without source_guid must be stored as full — can't reconstruct without a join key."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["a1", "a2"])
        yield b
        b.close()

    def test_no_source_guid_stored_as_full(self, backend):
        """Record without source_guid is stored as _delta_mode=full."""
        data = [
            {
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {"source": {"x": 1}, "a2": {"y": 2}},
            }
        ]
        backend.write_target("a2", "f.json", data)

        raw = backend._read_target_raw("a2", "f.json")
        assert raw[0]["_delta_mode"] == "full"
        assert "source" in raw[0]["content"]
        assert "a2" in raw[0]["content"]

    def test_no_source_guid_read_returns_full_content(self, backend):
        """read_target for guid-less record returns all content intact."""
        data = [
            {
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {"source": {"x": 1}, "a1": {"q": "hi"}, "a2": {"y": 2}},
            }
        ]
        backend.write_target("a2", "f.json", data)

        result = backend.read_target("a2", "f.json")
        assert "source" in result[0]["content"]
        assert "a1" in result[0]["content"]
        assert "a2" in result[0]["content"]


class TestIssue7_PartitionedPipeline:
    """Diamond DAG where branches process different guids — no false incomplete flags."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["source", "branch_a", "branch_b", "merge"])
        dep_graph = {
            "source": [],
            "branch_a": ["source"],
            "branch_b": ["source"],
            "merge": ["source", "branch_a", "branch_b"],
        }
        b.save_metadata("dependency_graph", json.dumps(dep_graph))
        yield b
        b.close()

    def test_partitioned_guids_no_false_incomplete(self, backend):
        """branch_a processes g1, branch_b processes g2 — merge sees both without false flags."""
        backend.write_target(
            "source",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"x": 1}, "source": {"data": "raw"}},
                },
                {
                    "source_guid": "g2",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {"source": {"x": 2}, "source": {"data": "raw2"}},
                },
            ],
            is_first_action=True,
        )
        # branch_a only processes g1
        backend.write_target(
            "branch_a",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source": {"data": "raw"},
                        "branch_a": {"score": 5},
                    },
                }
            ],
        )
        # branch_b only processes g2
        backend.write_target(
            "branch_b",
            "f.json",
            [
                {
                    "source_guid": "g2",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 2},
                        "source": {"data": "raw2"},
                        "branch_b": {"score": 8},
                    },
                }
            ],
        )
        # merge processes both
        backend.write_target(
            "merge",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 1},
                        "source": {"data": "raw"},
                        "branch_a": {"score": 5},
                        "merge": {"combined": "g1_result"},
                    },
                },
                {
                    "source_guid": "g2",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {
                        "source": {"x": 2},
                        "source": {"data": "raw2"},
                        "branch_b": {"score": 8},
                        "merge": {"combined": "g2_result"},
                    },
                },
            ],
        )

        result = backend.read_target("merge", "f.json")
        for r in result:
            assert "_reconstruction_incomplete" not in r, (
                f"False incomplete flag on {r.get('source_guid')}"
            )
            assert "merge" in r["content"]


class TestIssue8_FilesystemLeak:
    """_delta_mode must not appear in filesystem target files."""

    def test_write_target_does_not_create_disk_file(self, tmp_path):
        """FileWriter writes to backend only — no filesystem file created."""
        from agent_actions.output.writer import FileWriter

        backend = _make_backend(tmp_path)
        _set_execution_order(backend, ["expand_action"])
        backend.initialize()

        output_dir = tmp_path / "target" / "expand_action"
        file_path = output_dir / "out.json"

        writer = FileWriter(
            str(file_path),
            storage_backend=backend,
            action_name="expand_action",
            output_directory=str(output_dir),
        )

        data = [
            {
                "source_guid": "g1",
                "_state": "processed",
                "_state_schema_version": 1,
                "_delta_mode": "full",
                "content": {"source": {"x": 1}, "expand_action": {"expanded": True}},
            }
        ]
        writer.write_target(data)

        assert not file_path.exists(), "Target file should not be written to disk"

        db_data = backend.read_target("expand_action", "out.json")
        for record in db_data:
            assert "_delta_mode" not in record, "_delta_mode leaked through read_target"

        backend.close()


class TestIssue9_CorruptMetadata:
    """Corrupt metadata must degrade gracefully, not crash."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        yield b
        b.close()

    def test_corrupt_dependency_graph_falls_back(self, backend):
        """Corrupt dep graph → fallback to flat execution order, no crash."""
        backend.save_metadata("dependency_graph", "NOT VALID JSON{{{")
        backend.save_metadata("execution_order", json.dumps(["a1", "a2"]))

        backend.write_target(
            "a1",
            "f.json",
            [{"source_guid": "g1", "_state": "active", "content": {"a1": {"x": 1}}}],
            is_first_action=True,
        )
        backend.write_target(
            "a2",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "active",
                    "content": {"a1": {"x": 1}, "a2": {"y": 2}},
                }
            ],
        )

        # Should not crash — falls back to flat order
        result = backend.read_target("a2", "f.json")
        assert "a2" in result[0]["content"]

    def test_corrupt_execution_order_returns_raw(self, backend):
        """Corrupt execution order → reconstruction disabled, raw delta returned."""
        backend.save_metadata("execution_order", "CORRUPT!!!")

        backend.write_target(
            "a1",
            "f.json",
            [{"source_guid": "g1", "_state": "active", "content": {"a1": {"x": 1}}}],
            is_first_action=True,
        )

        # read_target should not crash
        result = backend.read_target("a1", "f.json")
        assert "a1" in result[0]["content"]


class TestIssue10_UniformDeltaMode:
    """write_target must produce uniform _delta_mode across all records in a batch."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["a1", "a2"])
        yield b
        b.close()

    def test_batch_has_uniform_delta_mode(self, backend):
        """All records in a single write_target call get the same _delta_mode."""
        data = [
            {
                "source_guid": f"g{i}",
                "_state": "processed",
                "_state_schema_version": 1,
                "content": {"source": {"x": i}, "a1": {"q": f"Q{i}"}, "a2": {"level": f"L{i}"}},
            }
            for i in range(5)
        ]
        backend.write_target("a2", "f.json", data)

        raw = backend._read_target_raw("a2", "f.json")
        modes = {r.get("_delta_mode") for r in raw}
        assert len(modes) == 1, f"Non-uniform delta modes in batch: {modes}"


class TestIssue11_FallbackWarning:
    """Action not in dep graph should warn and fall back to flat order."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = _make_backend(tmp_path)
        _set_execution_order(b, ["a1", "a2", "a3"])
        # dep graph deliberately missing a3
        b.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
        yield b
        b.close()

    def test_missing_action_in_graph_still_works(self, backend, capsys):
        """Action not in dep graph falls back to flat order with warning."""
        backend.write_target(
            "a1",
            "f.json",
            [{"source_guid": "g1", "_state": "active", "content": {"a1": {"x": 1}}}],
            is_first_action=True,
        )
        backend.write_target(
            "a2",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "active",
                    "content": {"a1": {"x": 1}, "a2": {"y": 2}},
                }
            ],
        )
        backend.write_target(
            "a3",
            "f.json",
            [
                {
                    "source_guid": "g1",
                    "_state": "active",
                    "content": {"a1": {"x": 1}, "a2": {"y": 2}, "a3": {"z": 3}},
                }
            ],
        )

        result = backend.read_target("a3", "f.json")

        # Should still reconstruct (using flat order fallback)
        assert "a3" in result[0]["content"]
        # Warning fires via logging to stderr
        stderr = capsys.readouterr().err
        assert "not found in dependency graph" in stderr
