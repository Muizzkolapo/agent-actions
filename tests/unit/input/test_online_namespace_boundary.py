"""Online first-stage records use the same content.source envelope as batch (584 online parity).

Online ingestion used to emit FLAT records (`{**item, source_guid}`), so `get_existing_content`
stripped a reserved-named user column (e.g. node_id) by name and source_guid leaked into
`source.*`. Wrapping the user payload under `content.source` — matching the batch path — fixes
both and makes the two modes share one pathway.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _add_batch_metadata,
    _prepare_online_data,
)
from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder
from agent_actions.utils.content import get_existing_content
from agent_actions.utils.id_generation import IDGenerator


def _online_json(items):
    ctx = DataPreparationContext(
        content=items, file_type=".json", agent_config={}, file_path="/tmp/d.json", agent_name="a"
    )
    return _prepare_online_data(ctx)


def _source(record) -> dict:
    return SourceNamespaceBuilder.build(record, "a") or {}


def test_online_json_record_is_source_wrapped():
    _dc, st = _online_json([{"id": "r1", "page_content": "x", "node_id": "USER_A"}])
    rec = st[0]
    assert isinstance(rec.get("content"), dict)
    assert set(rec.get("content", {}).keys()) == {"source"}
    assert rec["content"]["source"] == {"id": "r1", "page_content": "x", "node_id": "USER_A"}


def test_online_reserved_column_survives_get_existing_content():
    # get_existing_content is the shared content chokepoint; it must NOT strip node_id by name.
    _dc, st = _online_json([{"id": "r1", "page_content": "x", "node_id": "USER_A"}])
    src = get_existing_content(st[0], is_first_stage=True).get("source", {})
    assert src.get("node_id") == "USER_A"


def test_online_source_namespace_is_exactly_user_payload_no_leak():
    _dc, st = _online_json([{"id": "r1", "page_content": "x"}])
    assert set(_source(st[0]).keys()) == {"id", "page_content"}, "source_guid leaked into source.*"


def test_online_and_batch_produce_identical_source_wrap():
    # Same pathway: online JSON and batch JSON wrap the user payload identically.
    row = {"id": "r1", "page_content": "x", "node_id": "n1"}
    online = _online_json([dict(row)])[1][0]
    batch = _add_batch_metadata([dict(row)], batch_id="run", node_id="node_0")[0]
    assert online["content"] == batch["content"]


def test_online_text_source_wrapped_no_leak():
    ctx = DataPreparationContext(
        content="a short text chunk.",
        file_type=".txt",
        agent_config={"chunk_config": {"chunk_size": 4000, "overlap": 0}},
        file_path="/tmp/d.txt",
        agent_name="a",
    )
    _dc, st = _prepare_online_data(ctx)
    src = _source(st[0])
    assert set(src.keys()) == {"content"}
    assert src["content"] == "a short text chunk."


def test_online_source_guid_unchanged():
    # No persisted guid moves — still hashed over the raw item.
    _dc, st = _online_json([{"id": "r1", "page_content": "x"}])
    assert st[0]["source_guid"] == IDGenerator.derive_source_guid({"id": "r1", "page_content": "x"})
