"""A contributor index has to be one, at the boundary that declares it.

``source_index`` says which input produced an output. A scalar ``None`` means no
single input did. Anything else is a position in the input list, and four
consumers read it: reconciliation takes the first element as the parent,
disposition accounting takes every element, and lineage takes every element
again under its own bounds rule. Only the tool knows what it meant, so an
element that names no input is refused where the tool wrote it rather than
improvised over four times.

Too-big stays tolerant — a tool cannot always know how many records the guard
left it, every consumer already drops an index past the end, and the row still
resolves against the inputs that do exist.
"""

from __future__ import annotations

import pytest

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.utils.udf_management.registry import FileUDFResult


def _outputs(source_index):
    return [{"source_index": source_index, "data": {"g": "a"}}]


class TestABoolIsNotAnIndex:
    """``isinstance(True, int)`` is true, so a bool passes every check the four
    consumers make and resolves to input 1 — a real row, the wrong one, silently.
    """

    def test_a_bool_element_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([True]))

    def test_a_bare_true_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs(True))

    def test_a_bare_false_is_refused(self):
        """`False` is 0, so it resolves to the first input and looks correct."""
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs(False))


class TestNoneInsideAList:
    """A scalar ``None`` is the documented way to say no input produced a row.
    Inside a list it says a *contributor* is nothing, which names no input.
    """

    def test_a_list_holding_only_none_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([None]))

    def test_none_beside_a_real_contributor_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([None, 0]))

    def test_none_after_a_real_contributor_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([0, None]))

    def test_a_scalar_none_is_still_accepted(self):
        """The synthetic-row declaration has to keep working."""
        assert FileUDFResult(outputs=_outputs(None)).outputs[0]["source_index"] is None


class TestANegativeIndex:
    """Python would read it from the end of the list, so it names an input the
    tool did not mean and the two bounds rules disagree about whether it counts.
    """

    def test_a_negative_element_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([0, -1]))

    def test_a_negative_scalar_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs(-1))


class TestAnElementThatIsNotAnInteger:
    def test_a_string_element_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([1, "0"]))

    def test_a_float_element_is_refused(self):
        with pytest.raises(ValueError, match="output\\[0\\]"):
            FileUDFResult(outputs=_outputs([0, 1.5]))


class TestWhatStaysAccepted:
    def test_an_index_past_the_end_is_still_accepted(self):
        """The tolerance that is real: every consumer already drops it."""
        assert FileUDFResult(outputs=_outputs([0, 99])).outputs[0]["source_index"] == [0, 99]

    def test_a_scalar_past_the_end_is_still_accepted(self):
        assert FileUDFResult(outputs=_outputs(99)).outputs[0]["source_index"] == 99

    def test_an_ordinary_collapse_is_accepted(self):
        assert FileUDFResult(outputs=_outputs([0, 1, 2])).outputs[0]["source_index"] == [0, 1, 2]

    def test_a_scalar_index_is_accepted(self):
        assert FileUDFResult(outputs=_outputs(1)).outputs[0]["source_index"] == 1


class TestTheRefusalSaysWhichOutputAndWhatIsAllowed:
    def test_it_names_the_offending_output_not_the_first(self):
        with pytest.raises(ValueError, match="output\\[2\\]"):
            FileUDFResult(
                outputs=[
                    {"source_index": 0, "data": {"g": "a"}},
                    {"source_index": [1, 2], "data": {"g": "b"}},
                    {"source_index": [None], "data": {"g": "c"}},
                ]
            )

    def test_it_names_the_element_that_is_wrong(self):
        with pytest.raises(ValueError, match="-1"):
            FileUDFResult(outputs=_outputs([0, -1]))


class TestTheConsumerThatReadsEveryContributor:
    """Lineage bounds each contributor with an upper limit and no lower one,
    while disposition accounting bounds both. A negative index is therefore
    dropped from the accounting that tombstones a record and kept by the lineage
    that names it a contributor — one index, two answers, for the same row.
    """

    @staticmethod
    def _enriched(mapping):
        context = ProcessingContext(
            agent_config={"kind": "tool", "granularity": "file"}, agent_name="collect"
        )
        context.source_data = [
            {"source_guid": g, "node_id": f"n_{g}", "lineage": [f"n_{g}"], "content": {"prev": {}}}
            for g in ("G0", "G1", "G2")
        ]
        context.is_first_stage = False
        result = ProcessingResult.success(data=[{"content": {"collect": {}}}], source_guid=None)
        result.source_mapping = {0: mapping}
        result.is_expansion = False
        return LineageEnricher().enrich(result, context).data[0]

    def test_a_negative_contributor_is_not_read_from_the_end(self):
        row = self._enriched([0, -1])

        assert "n_G2" not in (row.get("lineage_sources") or [])

    def test_a_negative_contributor_is_dropped_like_one_past_the_end(self):
        """`[0, 99]` already resolves to G0 alone; `[0, -1]` has to match it."""
        assert self._enriched([0, -1]).get("lineage_sources") == self._enriched([0, 99]).get(
            "lineage_sources"
        )

    def test_a_contributor_that_is_not_an_integer_does_not_raise(self):
        """The comparison assumed an int, so a string raised TypeError here —
        caught upstream, leaving the row with no provenance at all."""
        assert "n_G1" in (self._enriched([0, 1]).get("lineage_sources") or [])
        self._enriched([0, "1"])

    def test_the_contributors_that_do_name_an_input_still_arrive(self):
        assert sorted(self._enriched([0, 1]).get("lineage_sources") or []) == ["n_G0", "n_G1"]
