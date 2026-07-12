"""First-stage source_guid is a deterministic content identity, not a random uuid.

source_guid is the cross-run match key for the disposition/checkpoint gate, so the
same input record must produce the same guid across runs (batch resume). These
assert the behavioral contract at the real batch stamp path.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle that
# otherwise makes initial_pipeline uncollectable in isolation.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata


def test_batch_json_first_stage_guid_is_deterministic_across_runs():
    rows = [{"id": "r1", "title": "T", "page_content": "hello"}]
    a = _add_batch_metadata([dict(r) for r in rows], batch_id="run-A", node_id="n1")
    b = _add_batch_metadata([dict(r) for r in rows], batch_id="run-B", node_id="n2")
    # Same input content → same identity, independent of run-specific envelope
    # (batch_id / target_id differ between the two runs).
    assert a[0]["source_guid"] == b[0]["source_guid"]


def test_batch_first_stage_guid_is_distinct_per_record():
    rows = [{"id": "r1", "page_content": "A"}, {"id": "r2", "page_content": "B"}]
    built = _add_batch_metadata([dict(r) for r in rows], batch_id="run", node_id="n")
    assert built[0]["source_guid"] != built[1]["source_guid"]


def test_byte_identical_records_share_identity():
    # Two byte-identical records are the same source → same guid (dedup-correct).
    rows = [{"id": "dup", "page_content": "same"}, {"id": "dup", "page_content": "same"}]
    built = _add_batch_metadata([dict(r) for r in rows], batch_id="run", node_id="n")
    assert built[0]["source_guid"] == built[1]["source_guid"]
