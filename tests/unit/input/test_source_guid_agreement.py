"""Ingestion and processing agree on source_guid — the point of determinism (575/577).

Ingestion hashes the RAW payload before the envelope is added; processing inherits that
stamped guid (or, online, re-derives the same raw payload). The persisted guid must equal
the disposition/checkpoint key or second-stage source resolution never matches.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata
from agent_actions.utils.id_generation import IDGenerator


def test_batch_ingestion_stamps_the_raw_payload_guid():
    # The stamped guid equals deriving over the RAW row (pre-envelope), NOT over the
    # enveloped record — so it is independent of the per-run target_id/batch_id and a
    # reserved-named user column (node_id here) is part of identity.
    row = {"id": "r1", "page_content": "body", "node_id": "graph_a"}
    built = _add_batch_metadata([dict(row)], batch_id="run", node_id="node_0")
    assert built[0]["source_guid"] == IDGenerator.derive_source_guid(dict(row))


def test_batch_guid_stable_across_runs():
    # Same raw row, a fresh per-run envelope each time → the same stamped guid.
    row = {"id": "r1", "page_content": "body"}
    a = _add_batch_metadata([dict(row)], batch_id="RUN_A", node_id="node_A")
    b = _add_batch_metadata([dict(row)], batch_id="RUN_B", node_id="node_B")
    assert a[0]["source_guid"] == b[0]["source_guid"]


def test_online_text_ingestion_guid_equals_processing_derive():
    # Ingestion (_prepare_online_data) stamps a {"content": text} wrapper; processing
    # (task_preparer) derives from the raw string. They must agree.
    text = "a paragraph of source text"
    ingestion_guid = IDGenerator.derive_source_guid({"content": text})
    processing_guid = IDGenerator.derive_source_guid(text)
    assert ingestion_guid == processing_guid
