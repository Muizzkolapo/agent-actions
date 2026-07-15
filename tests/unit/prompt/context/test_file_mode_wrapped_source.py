"""FILE-mode source.* resolves against the wrapped content.source envelope (spec 584).

When first-stage records nest the user payload under content.source, a downstream FILE-mode
action that observes source.<field> must still resolve it. Guards the double-nesting bug:
without the fix, _resolve_source_content returns {"source": {...}} and source.page_content
never resolves, so the record is silently skipped (observe_field_missing).
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import _add_batch_metadata
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records


def test_file_mode_observe_resolves_wrapped_source():
    # A first-stage source record (content.source envelope) as it lands in source_data.
    src = _add_batch_metadata(
        [{"page_content": "the source body", "id": "1"}], batch_id="run", node_id="n0"
    )[0]
    sguid = src["source_guid"]
    # A downstream record referencing that source by guid, observing source.page_content.
    downstream = {"content": {"prior": {"x": 1}}, "source_guid": sguid}

    enriched, skipped = apply_context_scope_for_records(
        [downstream],
        {"observe": ["source.page_content"]},
        "act",
        source_data=[src],
    )

    assert skipped == [], f"source.page_content failed to resolve (double-nesting): {skipped}"
    assert len(enriched) == 1
