"""Wave 12 regression tests for SQLite backend (T2-1, T2-2, T2-3)."""

from __future__ import annotations

import pytest

from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_UNPROCESSED,
    VALID_DISPOSITIONS,
    Disposition,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    db_path = tmp_path / "agent_io" / "test.db"
    b = SQLiteBackend(str(db_path), "test_workflow")
    b.initialize()
    yield b
    b.close()


# ── T2-1: unknown kwarg guard ────────────────────────────────────────────────


class TestSQLiteBackendCreate:
    """T2-1: SQLiteBackend.create() must reject unknown kwargs."""

    def test_create_unknown_kwarg_raises_config_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        with pytest.raises(ConfigValidationError, match="Unknown kwargs for SQLiteBackend"):
            SQLiteBackend.create(
                db_path=db_path,
                workflow_name="wf",
                bad_kwarg="oops",
            )

    def test_create_valid_kwargs_succeeds(self, tmp_path):
        db_path = tmp_path / "test.db"
        b = SQLiteBackend.create(db_path=db_path, workflow_name="wf")
        assert isinstance(b, SQLiteBackend)
        b.close()

    def test_create_multiple_unknown_kwargs_all_listed(self, tmp_path):
        db_path = tmp_path / "test.db"
        with pytest.raises(ConfigValidationError) as exc_info:
            SQLiteBackend.create(
                db_path=db_path,
                workflow_name="wf",
                foo="a",
                bar="b",
            )
        msg = str(exc_info.value)
        # Both unknown keys should appear in the error
        assert "foo" in msg and "bar" in msg


# ── T2-2: Disposition enum ───────────────────────────────────────────────────


class TestDispositionEnum:
    """T2-2: Disposition enum values must match existing string constants."""

    def test_enum_values_match_string_constants(self):
        assert Disposition.PASSTHROUGH.value == DISPOSITION_PASSTHROUGH
        assert Disposition.SKIPPED.value == DISPOSITION_SKIPPED
        assert Disposition.FILTERED.value == DISPOSITION_FILTERED
        assert Disposition.EXHAUSTED.value == DISPOSITION_EXHAUSTED
        assert Disposition.FAILED.value == DISPOSITION_FAILED
        assert Disposition.UNPROCESSED.value == DISPOSITION_UNPROCESSED

    def test_valid_dispositions_contains_all_enum_values(self):
        for member in Disposition:
            assert member.value in VALID_DISPOSITIONS

    def test_disposition_is_str_subclass(self):
        assert isinstance(Disposition.PASSTHROUGH, str)

    def test_set_disposition_accepts_enum_member(self, backend):
        backend.set_disposition(
            action_name="action_a",
            record_id="rec_001",
            disposition=Disposition.SKIPPED,
            reason="test",
        )
        rows = backend.get_disposition("action_a", "rec_001")
        assert len(rows) == 1
        assert rows[0]["disposition"] == "skipped"

    def test_set_disposition_accepts_string(self, backend):
        backend.set_disposition(
            action_name="action_b",
            record_id="rec_002",
            disposition="filtered",
        )
        rows = backend.get_disposition("action_b", "rec_002")
        assert rows[0]["disposition"] == "filtered"


# ── T2-3: write_source executemany dedup ────────────────────────────────────


class TestWriteSourceExecutemany:
    """T2-3: write_source must use executemany and return correct dedup counts."""

    def test_write_source_inserts_all_new_records(self, backend):
        data = [
            {"source_guid": "g1", "value": "a"},
            {"source_guid": "g2", "value": "b"},
        ]
        result = backend.write_source("path/data.json", data, enable_deduplication=True)
        assert result == "path/data.json"
        rows = backend.read_source("path/data.json")
        assert len(rows) == 2

    def test_write_source_inserted_count_correct_for_large_batch(self, backend):
        """cursor.rowcount (not SELECT changes()) must reflect the total across executemany."""
        # Insert 5 unique rows — inserted_count must be 5, not 0/1 (last-row only)
        data = [{"source_guid": f"g{i}", "value": str(i)} for i in range(5)]
        backend.write_source("path/batch.json", data, enable_deduplication=True)
        rows = backend.read_source("path/batch.json")
        assert len(rows) == 5

        # Now re-insert the same 5 plus 2 new — skipped=5, inserted=2
        data2 = [{"source_guid": f"g{i}", "value": "dup"} for i in range(5)]
        data2 += [{"source_guid": "new1", "value": "x"}, {"source_guid": "new2", "value": "y"}]
        backend.write_source("path/batch.json", data2, enable_deduplication=True)
        rows2 = backend.read_source("path/batch.json")
        # Only the 2 new guids were inserted; total is now 7
        assert len(rows2) == 7
        assert {r["source_guid"] for r in rows2} == {f"g{i}" for i in range(5)} | {"new1", "new2"}

    def test_write_source_dedup_skips_existing(self, backend):
        data = [{"source_guid": "g1", "value": "first"}]
        backend.write_source("path/data.json", data)

        # Second write with same guid — should be skipped
        data2 = [
            {"source_guid": "g1", "value": "dup"},
            {"source_guid": "g3", "value": "new"},
        ]
        backend.write_source("path/data.json", data2, enable_deduplication=True)
        rows = backend.read_source("path/data.json")
        # g1 stays as first write; g3 is inserted
        guids = {r["source_guid"] for r in rows}
        assert "g1" in guids
        assert "g3" in guids

    def test_write_source_no_dedup_replaces(self, backend):
        data = [{"source_guid": "g1", "value": "first"}]
        backend.write_source("path/data.json", data)

        data2 = [{"source_guid": "g1", "value": "replaced"}]
        backend.write_source("path/data.json", data2, enable_deduplication=False)
        rows = backend.read_source("path/data.json")
        assert any(r["value"] == "replaced" for r in rows)

    def test_write_source_skips_items_without_guid(self, backend):
        data = [
            {"value": "no_guid"},
            {"source_guid": "g1", "value": "has_guid"},
        ]
        backend.write_source("path/data.json", data)
        rows = backend.read_source("path/data.json")
        assert len(rows) == 1

    def test_write_source_all_missing_guid_raises(self, backend):
        data = [{"value": "no_guid_1"}, {"value": "no_guid_2"}]
        with pytest.raises(ValueError, match="missing source_guid"):
            backend.write_source("path/data.json", data)
