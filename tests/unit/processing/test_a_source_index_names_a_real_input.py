"""A contributor index has to be one, at the boundary that declares it.

``source_index`` names which input produced a row. Six readers take it apart
under three different bounds rules, so an element naming no input is refused
where the tool wrote it rather than guessed at six times. An index past the end
is still accepted, but only a contributor may be dropped — a parent that does
not resolve fails rather than being invented.
"""

from __future__ import annotations

import pytest

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.strategies.file_tool import _accounted_source_guids
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.record.tracking import is_input_position
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline_file_mode import _parent_index, reconcile_outputs


def _outputs(source_index):
    return [{"source_index": source_index, "data": {"g": "a"}}]


class TestABoolIsNotAnIndex:
    """``isinstance(True, int)`` is true, so a bool passes every check the readers
    make and resolves to input 1 — a real row, the wrong one, silently.
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

    @pytest.mark.parametrize(
        "source_index",
        [[[0, 1]], [(0,)], [{0}], [b"0"]],
        ids=["a-list", "a-tuple", "a-set", "bytes"],
    )
    def test_a_container_of_positions_is_refused(self, source_index):
        """A tool that wraps its index list once too often writes ``[[0, 1]]``, which
        reads as one contributor that is itself a list. Nothing named that shape, though
        the rule already refuses it.

        These add breadth rather than closing a hole: ``test_a_value_that_is_only_index_like_is_refused``
        above already fails if the rule is rewritten as a denylist of the refused types,
        which is how a container would get through to ``_resolve_input_record`` and be
        reported as an index out of a range it was never in.
        """
        with pytest.raises(ValueError, match="non-negative int"):
            FileUDFResult(outputs=_outputs(source_index))


class TestWhatStaysAccepted:
    def test_an_index_past_the_end_is_still_accepted(self):
        """A tool cannot always know how many records the guard left it."""
        assert FileUDFResult(outputs=_outputs([0, 99])).outputs[0]["source_index"] == [0, 99]

    def test_a_scalar_past_the_end_is_still_accepted(self):
        assert FileUDFResult(outputs=_outputs(99)).outputs[0]["source_index"] == 99

    def test_an_ordinary_collapse_is_accepted(self):
        assert FileUDFResult(outputs=_outputs([0, 1, 2])).outputs[0]["source_index"] == [0, 1, 2]

    def test_a_scalar_index_is_accepted(self):
        assert FileUDFResult(outputs=_outputs(1)).outputs[0]["source_index"] == 1


class TestAnIntegralValueThatIsNotABuiltinInt:
    """A numpy or pandas index is integral without being an ``int``. Accepted, it
    was counted by lineage and not by the accounting — the split this refuses.
    """

    class Position(int):
        """Stands in for numpy's integer: an int subclass, still an int."""

    def test_an_int_subclass_is_accepted(self):
        assert FileUDFResult(outputs=_outputs([self.Position(0)])).outputs[0]["source_index"] == [0]

    def test_a_value_that_is_only_index_like_is_refused(self):
        class Integral:
            def __index__(self):
                return 0

        with pytest.raises(ValueError, match="non-negative int"):
            FileUDFResult(outputs=_outputs([Integral()]))


class TestWhereATooBigIndexIsAndIsNotTolerated:
    """Accepting it at the boundary is not the same as tolerating it everywhere.
    A contributor past the end is dropped; a *parent* past the end is refused,
    because the alternative is giving the row a parent the tool never named.
    """

    @staticmethod
    def _records(n=3):
        return [{"source_guid": f"G{i}", "content": {"prev": {"id": i}}} for i in range(n)]

    def test_a_contributor_past_the_end_is_dropped_and_the_row_survives(self):
        rows, _ = reconcile_outputs(FileUDFResult(outputs=_outputs([0, 99])), "a2", self._records())

        assert [r["source_guid"] for r in rows] == ["G0"]

    def test_a_parent_past_the_end_is_refused_rather_than_invented(self):
        with pytest.raises(IndexError, match="does not name one of the 3"):
            reconcile_outputs(FileUDFResult(outputs=_outputs([99, 0])), "a2", self._records())

    def test_a_scalar_past_the_end_is_refused_for_the_same_reason(self):
        with pytest.raises(IndexError, match="does not name one of the 3"):
            reconcile_outputs(FileUDFResult(outputs=_outputs(99)), "a2", self._records())


class TestTheSharedRuleItself:
    """Six readers defer to this one predicate, so its own edges need pinning —
    an off-by-one here is an `IndexError` in two of them.
    """

    def test_the_last_real_position_is_one_below_the_count(self):
        assert is_input_position(1, 2) is True

    def test_the_count_itself_is_not_a_position(self):
        assert is_input_position(2, 2) is False

    def test_an_empty_input_list_has_no_positions(self):
        assert is_input_position(0, 0) is False

    def test_without_a_count_the_upper_bound_is_not_checked(self):
        assert is_input_position(99) is True

    def test_a_bool_is_never_a_position(self):
        assert is_input_position(True, 5) is False
        assert is_input_position(False, 5) is False

    def test_a_negative_is_never_a_position(self):
        assert is_input_position(-1, 5) is False

    def test_a_non_integer_is_never_a_position(self):
        assert is_input_position("0", 5) is False
        assert is_input_position(None, 5) is False
        assert is_input_position(1.0, 5) is False


class TestTheAccountingReaderRefusesABoolToo:
    """`_accounted_source_guids` decides which inputs a row covers, and so which
    are tombstoned as dropped. A bool counted as position 1 there would report a
    record as covered by a row that never named it."""

    @staticmethod
    def _records():
        return [{"source_guid": f"G{i}", "content": {}} for i in range(3)]

    def test_a_bool_accounts_for_no_record(self):
        accounted = _accounted_source_guids([{"source_guid": "G0"}], {0: True}, self._records())

        assert "G1" not in accounted

    def test_a_real_index_still_accounts_for_its_record(self):
        accounted = _accounted_source_guids([{"source_guid": "G0"}], {0: 1}, self._records())

        assert "G1" in accounted

    def test_a_bool_names_no_parent(self):
        """`_parent_index` chose the row's parent; `True` selected input 1."""
        assert _parent_index(0, [{}], {0: True}, self._records()) is None

    def test_a_real_index_still_names_its_parent(self):
        assert _parent_index(0, [{}], {0: 1}, self._records()) == 1


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
        """Anchored to the element, not the list: a message quoting the whole
        list would satisfy a bare `-1` match without naming what is wrong."""
        with pytest.raises(ValueError, match=r"source_index\[1\].*non-negative int.*-1"):
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

    def test_the_contributor_that_does_name_an_input_is_still_kept(self):
        """Paired with the test above: dropping the -1 must not collapse the
        whole lineage, which "no lineage_sources" alone would also satisfy."""
        assert self._enriched([0, -1])["lineage"][0] == "n_G0"

    def test_a_negative_contributor_is_dropped_like_one_past_the_end(self):
        """`[0, 99]` already resolves to G0 alone; `[0, -1]` has to match it."""
        assert self._enriched([0, -1]).get("lineage_sources") == self._enriched([0, 99]).get(
            "lineage_sources"
        )

    def test_a_contributor_that_is_not_an_integer_is_dropped_not_raised(self):
        """The comparison assumed an int, so a string raised TypeError here —
        caught upstream, leaving the row with no provenance at all."""
        row = self._enriched([0, "1"])

        assert row["lineage"][0] == "n_G0"
        assert "n_G1" not in (row.get("lineage_sources") or [])

    def test_the_contributors_that_do_name_an_input_still_arrive(self):
        assert sorted(self._enriched([0, 1]).get("lineage_sources") or []) == ["n_G0", "n_G1"]

    def test_a_bool_handed_straight_to_the_reader_resolves_to_nothing(self):
        """The reported symptom, at the reader rather than the boundary: `True`
        is an int, so this branch read `source_data[True]` and gave the row the
        second input's ancestry. Pinned here because the boundary refusing bools
        does not stop this line from being rewritten."""
        row = self._enriched(True)

        assert row["lineage"] == [row["node_id"]]
        assert "n_G1" not in row["lineage"]
