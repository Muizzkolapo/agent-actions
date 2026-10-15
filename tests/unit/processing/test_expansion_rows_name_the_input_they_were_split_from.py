"""An expanded row names the one input it was split from, and none when it read several."""

from unittest.mock import MagicMock

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus

INPUTS = [{"source_guid": "A"}, {"source_guid": "B"}]


def _enrich(source_mapping):
    rows = [{"source_guid": "A", "content": str(i)} for i in range(len(source_mapping))]
    context = MagicMock(spec=ProcessingContext)
    context.action_name = context.agent_name = "act"
    context.is_first_stage = False
    context.source_data = INPUTS
    context.parent_records = []
    context.record_index = 0
    context.agent_config = {}
    result = ProcessingResult(
        data=rows,
        status=ProcessingStatus.SUCCESS,
        is_expansion=True,
        source_guid="A",
        source_mapping=source_mapping,
    )
    return LineageEnricher().enrich(result, context).data


def test_each_row_read_from_one_input_names_it():
    rows = _enrich({0: 0, 1: 0})

    assert [r.get("split_from_source_guid") for r in rows] == ["A", "A"]


def test_a_row_read_from_several_inputs_names_none():
    rows = _enrich({0: [0, 1], 1: [0, 1]})

    assert [r.get("split_from_source_guid") for r in rows] == [None, None]
