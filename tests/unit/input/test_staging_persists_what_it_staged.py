"""What staging persists, and what it refuses, at the source-save boundary."""

import json

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.input.preprocessing.staging.initial_pipeline import _save_source_data
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

CORRELATION_STUB = [{"source_guid": "g0", "id": "t0", "lineage": [], "node_id": "n0"}]


def _row(guid, **payload):
    return {
        "content": {"source": payload},
        "source_guid": guid,
        "target_id": f"t-{guid}",
        "parent_target_id": None,
        "root_target_id": f"t-{guid}",
        "node_id": "node_0",
    }


def _workflow(tmp_path):
    staging = tmp_path / "wf" / "agent_io" / "staging"
    staging.mkdir(parents=True)
    doc = staging / "ticket.json"
    doc.write_text("[]")
    target = tmp_path / "wf" / "agent_io" / "target" / "extract"
    target.mkdir(parents=True)
    backend = SQLiteBackend(str(tmp_path / "s.db"), "wf")
    backend.initialize()
    return doc, staging, target, backend


def _stored(backend, relative_path):
    try:
        return backend.read_source(relative_path)
    except FileNotFoundError:
        return []


def _save(rows, doc, staging, target, backend):
    _save_source_data([], rows, str(doc), str(staging), str(target), storage_backend=backend)


class TestARecordWithNoIdentityReachesTheGuard:
    def test_it_is_not_dropped_before_the_store_sees_it(self, tmp_path):
        doc, staging, target, backend = _workflow(tmp_path)
        with pytest.raises(DataValidationError) as refused:
            _save([{"content": {"source": {"a": 1}}}], doc, staging, target, backend)
        backend.close()
        # The store is what refused, not a guard above it that raises the same class.
        assert refused.value.context == {"relative_path": "ticket", "record_index": 0}

    def test_a_mixed_chunk_fails_rather_than_storing_only_the_half_that_has_one(self, tmp_path):
        doc, staging, target, backend = _workflow(tmp_path)
        rows = [_row("g1", a=1), {"content": {"source": {"b": 2}}}]
        with pytest.raises(DataValidationError) as refused:
            _save(rows, doc, staging, target, backend)
        stored = _stored(backend, "ticket")
        backend.close()
        assert stored == []
        assert refused.value.context["record_index"] == 1

    def test_rows_that_all_carry_one_are_stored(self, tmp_path):
        doc, staging, target, backend = _workflow(tmp_path)
        _save([_row("g1", a=1), _row("g2", b=2)], doc, staging, target, backend)
        stored = _stored(backend, "ticket")
        backend.close()
        assert sorted(row["source_guid"] for row in stored) == ["g1", "g2"]


class TestWhatWasStagedIsPersisted:
    def _with_correlation_file(self, tmp_path):
        doc, staging, target, backend = _workflow(tmp_path)
        source_dir = tmp_path / "wf" / "agent_io" / "source"
        source_dir.mkdir(parents=True)
        (source_dir / "ticket.json").write_text(json.dumps(CORRELATION_STUB))
        return doc, staging, target, backend

    def test_a_payload_no_wider_than_the_correlation_stub_is_still_stored(self, tmp_path):
        doc, staging, target, backend = self._with_correlation_file(tmp_path)
        _save([_row("g1", id=1, url="u", title="t", text="x")], doc, staging, target, backend)
        stored = _stored(backend, "ticket")
        backend.close()
        assert [row["source_guid"] for row in stored] == ["g1"]

    def test_a_narrower_payload_is_still_stored(self, tmp_path):
        doc, staging, target, backend = self._with_correlation_file(tmp_path)
        _save([_row("g1", only="one")], doc, staging, target, backend)
        stored = _stored(backend, "ticket")
        backend.close()
        assert [row["source_guid"] for row in stored] == ["g1"]

    def test_the_payload_itself_survives(self, tmp_path):
        doc, staging, target, backend = self._with_correlation_file(tmp_path)
        _save([_row("g1", only="one")], doc, staging, target, backend)
        stored = _stored(backend, "ticket")
        backend.close()
        assert [row["content"]["source"] for row in stored] == [{"only": "one"}]
