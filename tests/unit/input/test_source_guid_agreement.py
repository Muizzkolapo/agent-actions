"""Ingestion and processing derive the same source_guid — the point of determinism.

The source_data-persisted guid (ingestion) must equal the disposition/checkpoint key
(processing) for the same record, or second-stage source resolution never matches.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata
from agent_actions.utils.id_generation import IDGenerator


def test_batch_ingestion_guid_equals_processing_derive():
    rows = [{"id": "r1", "page_content": "body"}]
    built = _add_batch_metadata([dict(r) for r in rows], batch_id="run", node_id="node_0")
    # Processing re-derives over the same record; envelope exclusion makes it match the
    # stamped ingestion guid despite the run-specific envelope (target_id/batch_id).
    assert IDGenerator.derive_source_guid(built[0]) == built[0]["source_guid"]


def test_online_text_ingestion_guid_equals_processing_derive():
    # Ingestion (_prepare_online_data) stamps a {"content": text} wrapper; processing
    # (task_preparer) derives from the raw string. They must agree.
    text = "a paragraph of source text"
    ingestion_guid = IDGenerator.derive_source_guid({"content": text})
    processing_guid = IDGenerator.derive_source_guid(text)
    assert ingestion_guid == processing_guid
