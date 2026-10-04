"""A guard UDF is put to every record, whatever shape the record has.

The view the UDF is handed was built by a walk that recursed once per level, inside the
`try` that calls the UDF. A record nested a few hundred levels deep, which JSON allows, or
one holding a reference back to itself, raised `RecursionError` there, and a guard whose
UDF raises passes its record. The UDF never ran and the record went to the action.
"""

import json

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.registry import udf_tool
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

# Past every interpreter's recursion limit, and still a record `json.loads` returns.
DEPTH = 5000
_seen: list[str] = []


def shape_probe_rejects_everything(data):
    _seen.append("ran")
    return False


def shape_probe_admits_everything(data):
    _seen.append("ran")
    return True


@pytest.fixture(autouse=True)
def _register():
    for probe in (shape_probe_rejects_everything, shape_probe_admits_everything):
        udf_tool(probe)
    _seen.clear()


def _nested(kind: str, depth: int = DEPTH):
    """*depth* containers one inside the next, built without recursion."""
    value: object = "leaf"
    for level in range(depth):
        if kind == "dicts" or (kind == "alternating" and level % 2):
            value = {"in": value}
        else:
            value = [value]
    return value


def _cyclic(kind: str):
    if kind == "a dict that holds itself":
        ns: dict = {"tier": "keep"}
        ns["me"] = ns
        return ns
    if kind == "a list that holds itself":
        rows: list = [1]
        rows.append(rows)
        return {"rows": rows}
    if kind == "a cycle through a tuple":
        ns = {"tier": "keep"}
        ns["pair"] = (ns, 1)
        return ns
    ns = {"tier": "keep", "child": {}}
    ns["child"]["parent"] = ns
    return ns


def _record(namespace):
    return {"source_guid": "g1", "content": {"a1": namespace}}


def _verdict(udf, record, context=None):
    return GuardEvaluator().evaluate(record, None, context=context, conditional_clause=udf.__name__)


SHAPES = {
    "nested dicts": lambda: {"deep": _nested("dicts")},
    "nested lists": lambda: {"deep": _nested("lists")},
    "dicts and lists alternating": lambda: {"deep": _nested("alternating")},
    "a json document nested as deep as json allows": lambda: json.loads(
        '{"deep": ' + "[" * 900 + "1" + "]" * 900 + "}"
    ),
    "a dict that holds itself": lambda: _cyclic("a dict that holds itself"),
    "a list that holds itself": lambda: _cyclic("a list that holds itself"),
    "a cycle through a tuple": lambda: _cyclic("a cycle through a tuple"),
    "a child that points back at its parent": lambda: _cyclic("parent"),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("context", [None, {"other": 1}], ids=["no_context", "with_context"])
class TestTheGuardIsPutToTheRecord:
    def test_a_rejecting_guard_rejects_it(self, shape, context):
        result = _verdict(shape_probe_rejects_everything, _record(SHAPES[shape]()), context)

        assert _seen == ["ran"], "the guard UDF was never called"
        assert result.should_execute is False

    def test_an_admitting_guard_admits_it_having_run(self, shape, context):
        result = _verdict(shape_probe_admits_everything, _record(SHAPES[shape]()), context)

        assert _seen == ["ran"]
        assert result.should_execute is True


class _HashesOnce:
    """A key that can be stored and not looked at again: nothing can build a view over it."""

    def __init__(self) -> None:
        self.hashed = 0

    def __hash__(self) -> int:
        self.hashed += 1
        if self.hashed > 1:
            raise OSError("this key cannot be read twice")
        return 7


def _unviewable():
    return _record({_HashesOnce(): {"n": 1}})


class TestARecordTheGuardCouldNotBeShown:
    """Not judged is not passed. Whatever stops the view being built is the framework's
    failure, not the UDF's, so the rule that passes a record whose UDF raised does not apply."""

    def test_it_is_not_admitted(self):
        with pytest.raises(ProcessingError) as raised:
            _verdict(shape_probe_admits_everything, _unviewable())

        assert type(raised.value).__name__ == "GuardNotAppliedError"
        assert _seen == [], "the UDF ran on a view that could not be built"

    def test_the_error_names_the_guard_and_what_went_wrong(self):
        with pytest.raises(ProcessingError) as raised:
            _verdict(shape_probe_rejects_everything, _unviewable())

        message = str(raised.value)
        assert "shape_probe_rejects_everything" in message
        assert "this key cannot be read twice" in message

    def test_the_pre_filter_names_the_record(self):
        records = [
            {"source_guid": "g-first", "content": {"a1": {"tier": "keep"}}},
            {**_unviewable(), "source_guid": "g-second"},
        ]

        with pytest.raises(ProcessingError) as raised:
            prefilter_by_guard(
                records,
                {"conditional_clause": "shape_probe_admits_everything"},
                "decide",
            )

        message = str(raised.value)
        assert "Record 2 of 2" in message
        assert "g-second" in message

    def test_a_udf_that_raises_still_passes_its_record(self):
        """The legacy rule for the UDF's own errors is untouched."""

        def shape_probe_raises(data):
            raise ValueError("the guard's own bug")

        udf_tool(shape_probe_raises)

        result = _verdict(shape_probe_raises, _record({"tier": "keep"}))

        assert result.should_execute is True
