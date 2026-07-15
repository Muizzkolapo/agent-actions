"""Online data_chunk (the processor's input) is wrapped, and the processor inherits (584).

`_process_online_mode_with_record_processor` consumes `data_chunk` (return[0] of
`_prepare_online_data`), NOT `src_text` (return[1]). These pin that `data_chunk` itself is
the wrapped record (a wrap-only-src_text regression would ship the flat record to the
processor) AND that task_preparer INHERITS the stamped guid over the wrapped envelope rather
than re-deriving (which would move it).
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_online_data,
)
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.utils.id_generation import IDGenerator


def _online(items, file_type=".json", agent_config=None):
    ctx = DataPreparationContext(
        content=items,
        file_type=file_type,
        agent_config=agent_config or {},
        file_path="/tmp/d" + file_type,
        agent_name="a",
    )
    return _prepare_online_data(ctx)


def test_online_json_data_chunk_is_the_wrapped_processor_input():
    # The processor consumes data_chunk (return[0]); pin it IS the wrapped record.
    dc, st = _online([{"id": "r1", "page_content": "x", "node_id": "USER_A"}])
    assert dc is st, "data_chunk (processor input) must be the same wrapped object as src_text"
    assert dc[0]["content"]["source"]["node_id"] == "USER_A"


def test_online_text_data_chunk_is_wrapped():
    dc, st = _online(
        "a short chunk.",
        file_type=".txt",
        agent_config={"chunk_config": {"chunk_size": 4000, "overlap": 0}},
    )
    assert dc is st
    assert dc[0]["content"]["source"] == {"content": "a short chunk."}


def test_online_processor_inherits_stamped_guid_not_rederive():
    # task_preparer must INHERIT the stamped guid over the wrapped envelope; re-deriving the
    # wrapped record would move it (this is why the ingestion stamp is load-bearing).
    dc, _st = _online([{"id": "r1", "page_content": "x"}])
    rec = dc[0]
    stamped = rec["source_guid"]
    assert IDGenerator.derive_source_guid(rec) != stamped, (
        "sanity: hashing the wrapped record differs from the stamped raw-payload guid"
    )
    ctx = PreparationContext(agent_config={}, agent_name="a", is_first_stage=True)
    _content, guid, _snapshot = TaskPreparer()._normalize_input(rec, ctx)
    assert guid == stamped
