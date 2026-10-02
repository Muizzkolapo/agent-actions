"""A `conditional_clause` UDF gets a read-only view, not the record itself.

Guard evaluation assembles its context by assigning the record's namespaces by reference,
and when no context is supplied `eval_data` IS the record. A UDF that writes to what it is
given rewrote the record mid-run: the action's input, the enricher and the skipped
tombstones all saw the new value, with nothing logged.
"""

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.registry import udf_tool

_ran: list[str] = []


def guard_probe_mutates_raw(data):
    _ran.append("raw")
    data["content"]["a1"]["tier"] = "MUTATED"
    return True


def guard_probe_mutates_promoted(data):
    _ran.append("promoted")
    data["a1"]["tier"] = "MUTATED"
    return True


def guard_probe_reads(data):
    _ran.append("reads")
    return data.require("content")["a1"]["tier"] == "keep"


@pytest.fixture(autouse=True)
def _register_probes():
    """Registered per test, not at import.

    Any earlier test calling `clear_registry()` -- tests/cli/test_list_udfs.py does, around
    every test in it -- wiped an import-time registration, and a guard whose UDF is missing
    used to be swallowed as a warning and passed through. The record was then unmutated
    because the UDF never ran, so these tests passed without the view doing anything.
    """
    for fn in (guard_probe_mutates_raw, guard_probe_mutates_promoted, guard_probe_reads):
        udf_tool(fn)
    _ran.clear()
    yield


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

        assert _ran == ["raw"], "the UDF must have run, or the record survived for no reason"
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

        assert _ran == ["promoted"], "the UDF must have run"
        assert item["content"]["a1"]["tier"] == "keep", item

    def test_a_reading_udf_still_works_and_keeps_require(self):
        """The view must not break the UDFs that behave — including Bus.require()."""
        item = _item()
        result = GuardEvaluator().evaluate(
            item,
            {"clause": "a1.tier == 'keep'", "on_false": "filter"},
            conditional_clause="guard_probe_reads",
        )

        assert _ran == ["reads"], "the UDF must have run"
        assert result.should_execute is True
        assert item["content"]["a1"]["tier"] == "keep"
