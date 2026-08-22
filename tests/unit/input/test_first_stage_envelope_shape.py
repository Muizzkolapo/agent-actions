"""The first-stage batch envelope's literal shape + identity-through-task-prep.

Complements test_first_stage_namespace_boundary.py (which asserts via the resolved
`source.*` namespace) by pinning the *literal* record shape — a wrong impl that puts the
user payload directly under `content` (no `source` sub-key) still resolves cleanly via
SourceNamespaceBuilder's fallback, so the namespace-level tests alone don't catch it, but it
would collide with the `content[action_name]` convention downstream.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.utils.id_generation import IDGenerator


def test_record_content_is_literally_source_wrapped():
    # The payload must sit under content.source specifically — not directly under content
    # (which would collide with the content[action_name] namespace convention downstream).
    row = {"id": "1", "page_content": "x"}
    r = _add_batch_metadata([dict(row)], batch_id="run", node_id="n0")[0]
    assert isinstance(r["content"], dict)
    assert set(r["content"].keys()) == {"source"}, (
        f"content must hold only 'source': {r['content']}"
    )
    assert r["content"]["source"] == row


def test_user_column_named_content_nests_safely():
    # A user column literally named `content` must not collide with the envelope key — it
    # lands at content.source.content, preserved.
    r = _add_batch_metadata([{"content": "user text", "id": "1"}], batch_id="run", node_id="n0")[0]
    assert r["content"]["source"] == {"content": "user text", "id": "1"}


def test_task_prep_inherits_stamped_guid_not_rederive_over_wrapped():
    # Identity is stable through processing because task prep INHERITS the stamped guid.
    # Re-deriving over the wrapped record would move it — this pins that it must not.
    r = _add_batch_metadata([{"id": "1", "page_content": "x"}], batch_id="run", node_id="n0")[0]
    stamped = r["source_guid"]
    assert IDGenerator.derive_source_guid(r) != stamped, (
        "sanity: hashing the wrapped record differs from the stamped raw-payload guid"
    )
    ctx = PreparationContext(agent_config={}, agent_name="act", is_first_stage=True)
    _content, guid, _snapshot = TaskPreparer()._normalize_input(r, ctx)
    assert guid == stamped
