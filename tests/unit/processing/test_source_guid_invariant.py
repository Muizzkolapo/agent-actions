"""source_guid invariant: born at a source/producer, inherited downstream, never fabricated blank.

Covers the three enforcement points of the no-fallback design:
- producer: FILE-mode reconciliation stamps synthetic/parent-less records at the producer;
- chokepoint: enrichment raises (does not stamp "") when a record arrives without a guid;
- storage: write_source fails loud instead of silently dropping a guid-less record.
"""

import tempfile
from pathlib import Path

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.processing.enrichment import RequiredFieldsEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid


def _ctx():
    return ProcessingContext(
        agent_config={"agent_type": "consumer"},
        agent_name="consumer",
        is_first_stage=False,
    )


# ── chokepoint: no "" fallback ───────────────────────────────────────────────


def test_chokepoint_raises_on_guidless_record_instead_of_stamping_empty():
    # No item source_guid and no result.source_guid → today ensure_required_fields
    # stamps "". The invariant: a record reaching enrichment without a source_guid
    # is an upstream bug and must fail loud, naming the action.
    result = ProcessingResult.success(data=[{"content": {"x": 1}}], source_guid=None)
    with pytest.raises(DataValidationError) as exc:
        RequiredFieldsEnricher().enrich(result, _ctx())
    msg = str(exc.value)
    assert "source_guid" in msg and "consumer" in msg


def test_chokepoint_inherits_parent_guid_without_fabricating_a_fresh_one():
    # A record inherits result.source_guid (its parent) — the exact parent guid,
    # never a freshly generated one. Pins lineage preservation.
    result = ProcessingResult.success(data=[{"content": {"x": 1}}], source_guid="parent-guid")
    enriched = RequiredFieldsEnricher().enrich(result, _ctx())
    assert enriched.data[0]["source_guid"] == "parent-guid"


# ── producer: FILE-mode reconciliation never leaves a record blank ────────────


def test_producer_stamps_synthetic_file_record():
    # source_index=None (tool-synthesized row) is left blank today; the producer
    # must give it an identity (born at the producer, tracing to the source file).
    structured = [{"content": "new-row"}]
    _reattach_source_guid(structured, {0: None}, [{"source_guid": "file-parent"}])
    assert structured[0].get("source_guid")


def test_producer_stamps_when_parent_lacks_guid():
    # Mapped to a parent that itself has no guid → child left blank today.
    structured = [{"content": "child"}]
    _reattach_source_guid(structured, {0: 0}, [{"content": "parent-without-guid"}])
    assert structured[0].get("source_guid")


def test_producer_inherits_parent_guid_when_available():
    # The happy path stays intact: a mapped parent's guid is inherited verbatim.
    structured = [{"content": "child"}]
    _reattach_source_guid(structured, {0: 0}, [{"source_guid": "parent-1"}])
    assert structured[0]["source_guid"] == "parent-1"


# ── storage: fail loud, never silently partial-drop ──────────────────────────


def test_storage_fails_loud_on_guidless_record_in_a_mixed_batch():
    # Today write_source silently skips the guid-less item (rows < input, no error)
    # unless ALL are dropped. A partial drop is silent data loss — it must raise.
    with tempfile.TemporaryDirectory() as d:
        backend = SQLiteBackend(str(Path(d) / "s.db"), "wf")
        backend.initialize()
        mixed = [{"source_guid": "g1", "v": 1}, {"v": 2}]  # second lacks a guid
        with pytest.raises(DataValidationError):
            backend.write_source("in.json", mixed)
        backend.close()
