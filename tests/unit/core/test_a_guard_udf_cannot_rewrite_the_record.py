"""A `conditional_clause` UDF gets a read-only view, not the record itself.

Guard evaluation assembles its context by assigning the record's namespaces by reference,
and when no context is supplied `eval_data` IS the record. A UDF that writes to what it is
given rewrote the record mid-run: the action's input, the enricher and the skipped
tombstones all saw the new value, with nothing logged.
"""

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.registry import udf_tool


@udf_tool
def guard_probe_mutates_raw(data):
    data["content"]["a1"]["tier"] = "MUTATED"
    return True


@udf_tool
def guard_probe_mutates_promoted(data):
    data["a1"]["tier"] = "MUTATED"
    return True


@udf_tool
def guard_probe_reads(data):
    return data.require("content")["a1"]["tier"] == "keep"


def _item():
    return {"source_guid": "g1", "content": {"a1": {"tier": "keep"}}}


class TestAMutatingUdfCannotReachTheRecord:
    def test_the_record_survives_a_mutating_udf_with_no_context(self):
        """context=None means eval_data IS the record — the worst of the two paths."""
        item = _item()
        GuardEvaluator().evaluate(
            item,
            {"clause": "a1.tier == 'keep'", "on_false": "filter"},
            conditional_clause="guard_probe_mutates_raw",
        )

        assert item["content"]["a1"]["tier"] == "keep", item

    def test_the_record_survives_a_mutating_udf_with_a_context(self):
        """With a context the namespaces are promoted, still by reference."""
        item = _item()
        GuardEvaluator().evaluate(
            item,
            {"clause": "a1.tier == 'keep'", "on_false": "filter"},
            context={"source": {}},
            conditional_clause="guard_probe_mutates_promoted",
        )

        assert item["content"]["a1"]["tier"] == "keep", item

    def test_a_reading_udf_still_works_and_keeps_require(self):
        """The view must not break the UDFs that behave — including Bus.require()."""
        item = _item()
        result = GuardEvaluator().evaluate(
            item,
            {"clause": "a1.tier == 'keep'", "on_false": "filter"},
            conditional_clause="guard_probe_reads",
        )

        assert result.should_execute is True
        assert item["content"]["a1"]["tier"] == "keep"
