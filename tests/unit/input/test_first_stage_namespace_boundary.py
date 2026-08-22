"""First-stage user payload lives in its own namespace — framework can't touch it.

The batch envelope used to spread the user row FLAT alongside framework fields, so a user
column named like a framework field (`node_id`/`target_id`/…) was overwritten in storage, and
the whole flat record (framework ids included) leaked into the `source` namespace. 584 wraps
the user payload under `content.source`, so the value is preserved and `source.*` is exactly
the user payload — nothing more, nothing less.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    _add_batch_metadata,
    _prepare_text_chunks_batch,
)
from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder


def _source(record) -> dict:
    """The user-facing `source.*` namespace the framework resolves for a first-stage record."""
    return SourceNamespaceBuilder.build(record, "act") or {}


def test_reserved_named_user_column_value_preserved():
    # A graph/edge row keyed on node_id — the framework must not overwrite the user's value.
    built = _add_batch_metadata(
        [{"node_id": "user_A", "page_content": "x"}], batch_id="run", node_id="node_0"
    )
    assert _source(built[0])["node_id"] == "user_A"


def test_source_namespace_is_exactly_the_user_payload_no_framework_leak():
    # The user provided no target_id/batch_id/source_guid — none may appear in source.*.
    built = _add_batch_metadata(
        [{"id": "1", "page_content": "x"}], batch_id="run", node_id="node_0"
    )
    src = _source(built[0])
    assert set(src.keys()) == {"id", "page_content"}, (
        f"framework leaked into source.*: {sorted(src)}"
    )


def test_two_rows_differing_only_in_reserved_column_keep_both_values():
    # 577/#792 already gives distinct source_guids; 584 additionally preserves both values.
    b = _add_batch_metadata(
        [{"node_id": "A", "page_content": "x"}, {"node_id": "B", "page_content": "x"}],
        batch_id="run",
        node_id="node_0",
    )
    assert b[0]["source_guid"] != b[1]["source_guid"]
    assert _source(b[0])["node_id"] == "A"
    assert _source(b[1])["node_id"] == "B"


def test_text_chunk_source_parity_no_framework_leak():
    # Text chunks must expose source.* the same way as structured rows — no framework leak.
    built = _prepare_text_chunks_batch(
        "a single short chunk.",
        {"chunk_config": {"chunk_size": 4000, "overlap": 0}},
        batch_id="run",
        node_id="node_0",
    )
    src = _source(built[0])
    assert set(src.keys()) == {"content"}, f"framework leaked into text source.*: {sorted(src)}"
    assert src["content"] == "a single short chunk."


def test_source_guid_golden_no_op():
    # 584 must not move any persisted source_guid — hashing the raw row stays unchanged.
    built = _add_batch_metadata(
        [{"question": "What is 2+2?", "answer": "4", "metadata": {"src": "quiz.json", "row": 7}}],
        batch_id="run",
        node_id="node_0",
    )
    assert built[0]["source_guid"] == "cac9d8de-ed99-5b95-948e-ebd0439e27e2"
