"""Reserved-named user fields must not collapse distinct records' identity (spec 577).

`derive_source_guid` historically projected identity by *subtracting framework field
names* (`node_id`, `target_id`, `batch_id`, …) from the record. A user CSV/JSON column
that happens to share one of those names (e.g. a graph/edge export keyed on `node_id`)
was silently dropped from the hash, so two genuinely-distinct rows derived the SAME
`source_guid` and one was dropped by `INSERT OR IGNORE` on `UNIQUE(relative_path,
source_guid)`. See #788 follow-up F2.

Proper fix: identity is hashed over the RAW payload at ingestion, before the framework
envelope is added — nothing to subtract by name, so a user's reserved-named column is
legitimately part of identity. This must (a) distinguish rows that differ only in such a
column, while (b) leaving every existing guid for normal data unchanged (the 576 golden
values) and (c) preserving cross-run determinism and the 575 ingestion↔processing
agreement.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata
from agent_actions.utils.id_generation import IDGenerator

# The exact raw payloads whose derived guids 576 froze — used here to prove the fix is a
# strict no-op for normal data (identity unchanged wherever a row has no reserved column).
_GOLDEN = {
    "865e85c1-c292-5537-a9dc-aed6618263eb": {
        "content": "The mitochondria is the powerhouse of the cell."
    },
    "cac9d8de-ed99-5b95-948e-ebd0439e27e2": {
        "question": "What is 2+2?",
        "answer": "4",
        "metadata": {"src": "quiz.json", "row": 7},
    },
}


def test_batch_reserved_column_does_not_collide():
    """Two distinct rows differing ONLY in a reserved-named user column (node_id) must
    get distinct source_guids through the real batch ingestion function."""
    row1 = {"id": "edge", "content": "same body", "node_id": "n1"}
    row2 = {"id": "edge", "content": "same body", "node_id": "n2"}
    built = _add_batch_metadata([dict(row1), dict(row2)], batch_id="run", node_id="node_0")
    g1, g2 = built[0]["source_guid"], built[1]["source_guid"]
    assert g1 != g2, (
        "distinct rows differing only in a reserved-named user column collapsed to one "
        f"source_guid ({g1}) — the reserved-field collision (silent record loss)"
    )


def test_derive_includes_reserved_named_user_fields():
    """Identity must reflect a reserved-named user field (the online/JSON stamp path)."""
    a = {"content": "c", "node_id": "n1"}
    b = {"content": "c", "node_id": "n2"}
    assert IDGenerator.derive_source_guid(a) != IDGenerator.derive_source_guid(b)


def test_batch_identity_is_noop_for_normal_rows():
    """Regression guard: for a row with no reserved column, the batch guid is unchanged
    from the 576 golden value — the fix must not move any existing identity."""
    for gold, raw in _GOLDEN.items():
        built = _add_batch_metadata([dict(raw)], batch_id="run", node_id="node_0")
        assert built[0]["source_guid"] == gold, f"identity moved for {raw!r}"


def test_cross_run_determinism_survives_volatile_envelope():
    """Same raw content across two runs (fresh target_id/batch_id each run) → same guid.
    Identity must not depend on the per-run framework envelope."""
    raw = {"id": "r1", "content": "body"}
    run_a = _add_batch_metadata([dict(raw)], batch_id="RUN_A", node_id="node_A")
    run_b = _add_batch_metadata([dict(raw)], batch_id="RUN_B", node_id="node_B")
    assert run_a[0]["source_guid"] == run_b[0]["source_guid"]
