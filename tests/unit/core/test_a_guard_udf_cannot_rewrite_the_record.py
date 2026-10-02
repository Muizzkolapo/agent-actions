"""A `conditional_clause` UDF gets a read-only view, not the record itself.

Guard evaluation assembles its context by assigning the record's namespaces by reference,
and when no context is supplied `eval_data` IS the record. A UDF that writes to what it is
given rewrote the record mid-run: the action's input, the enricher and the skipped
tombstones all saw the new value, with nothing logged.
"""

import copy

import pytest

from agent_actions.guards import GuardBehavior
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.bus import Bus
from agent_actions.utils.udf_management.registry import udf_tool

_ran: list[str] = []
_taken: list[dict] = []

_GUARD = {"clause": "a1.tier == 'keep'", "behavior": "filter"}
# With no context the UDF receives the record as stored, `a1` under `content`; with one,
# the record's namespaces are promoted to the top. Every route is tried on both.
_CONTEXTS = pytest.mark.parametrize(
    "context", [None, {"other": 1}], ids=["no_context", "with_context"]
)


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


def _refused(error: TypeError) -> str:
    return "refused" if "read-only" in str(error) else f"refused without the guidance: {error}"


def _a1(root):
    """The `a1` namespace, wherever this evaluation put it."""
    return root["a1"] if "a1" in root else root["content"]["a1"]


def _try_write(namespace) -> bool:
    try:
        namespace["tier"] = "MUTATED"
    except TypeError as error:
        _ran.append(_refused(error))
    else:
        _ran.append("written")
    return True


def guard_probe_writes_directly(data):
    return _try_write(_a1(data))


def guard_probe_writes_via_dict(data):
    return _try_write(_a1(dict(data)))


def guard_probe_writes_via_unpack(data):
    return _try_write(_a1({**data}))


def guard_probe_writes_via_rebus(data):
    return _try_write(_a1(Bus(data)))


def guard_probe_writes_via_union(data):
    return _try_write(_a1(data | {}))


def guard_probe_writes_via_update_into(data):
    target: dict = {}
    target.update(data)
    return _try_write(_a1(target))


def guard_probe_writes_via_unbound_getitem(data):
    return _try_write(_a1({key: dict.__getitem__(data, key) for key in data}))


def guard_probe_writes_via_unbound_get(data):
    return _try_write(_a1({key: dict.get(data, key) for key in data}))


def guard_probe_writes_via_unbound_values(data):
    return _try_write(_a1(dict(zip(data, dict.values(data), strict=True))))


def guard_probe_writes_via_unbound_items(data):
    return _try_write(_a1(dict(dict.items(data))))


def guard_probe_writes_via_iteration(data):
    return _try_write(_a1({key: data[key] for key in data}))


_TOP_LEVEL_WRITES = {
    "setitem": lambda data: data.__setitem__("a1", {"tier": "MUTATED"}),
    "delitem": lambda data: data.__delitem__("source_guid"),
    "update": lambda data: data.update(a1={"tier": "MUTATED"}),
    "setdefault": lambda data: data.setdefault("new", {}),
    "pop": lambda data: data.pop("source_guid"),
    "popitem": lambda data: data.popitem(),
    "clear": lambda data: data.clear(),
}
_top_level_write: list[str] = []


def guard_probe_writes_top_level(data):
    try:
        _TOP_LEVEL_WRITES[_top_level_write[0]](data)
    except TypeError as error:
        _ran.append(_refused(error))
    else:
        _ran.append("written")
    return True


def guard_probe_merges_in_place(data):
    try:
        data |= {"a1": {"tier": "MUTATED"}}
    except TypeError as error:
        _ran.append(_refused(error))
    else:
        _ran.append("written")
    return True


def guard_probe_sidesteps_the_refusal(data):
    namespace = _a1({key: dict.__getitem__(data, key) for key in data})
    dict.__setitem__(namespace, "tier", "MUTATED")
    list.append(namespace["items"], "MUTATED")
    dict.__setitem__(namespace["items"][0]["inner"], "k", "MUTATED")
    _ran.append("written")
    return True


def _try_deep_write(namespace) -> bool:
    try:
        namespace["items"][0]["inner"]["k"].append("MUTATED")
    except TypeError as error:
        _ran.append(_refused(error))
    else:
        _ran.append("written")
    return True


def guard_probe_writes_deep_directly(data):
    return _try_deep_write(_a1(data))


def guard_probe_writes_deep_via_dict(data):
    return _try_deep_write(_a1(dict(data)))


def guard_probe_writes_deep_via_unpack(data):
    return _try_deep_write(_a1({**data}))


def guard_probe_writes_deep_via_unbound_getitem(data):
    return _try_deep_write(_a1({key: dict.__getitem__(data, key) for key in data}))


def _take(taken) -> bool:
    _taken.append(taken)
    return _try_write(_a1(taken))


def guard_probe_takes_copy_method(data):
    return _take(data.copy())


def guard_probe_takes_copy_copy(data):
    return _take(copy.copy(data))


def guard_probe_takes_deepcopy(data):
    return _take(copy.deepcopy(data))


def _write_deep(taken) -> bool:
    _taken.append(taken)
    items = _a1(taken)["items"]
    items[0]["n"] = 999
    items.append({"n": 3})
    _ran.append("written")
    return True


def guard_probe_writes_deep_into_copy_method(data):
    return _write_deep(data.copy())


def guard_probe_writes_deep_into_copy_copy(data):
    return _write_deep(copy.copy(data))


def guard_probe_writes_deep_into_deepcopy(data):
    return _write_deep(copy.deepcopy(data))


def guard_probe_reads_and_admits(data):
    _ran.append(_a1(data)["tier"])
    return True


def guard_probe_requires_keep(data):
    namespace = data.require("a1") if "a1" in data else data.require("content")["a1"]
    answer = namespace["tier"] == "keep"
    _ran.append("answered")
    return answer


def guard_probe_reads_with_a_keyword_default(data):
    namespace = data.get("a1", default=None) or data.get("content", default={}).get(
        "a1", default={}
    )
    answer = namespace.get("tier", default=None) == "keep"
    _ran.append("answered")
    return answer


def guard_probe_appends_to_a_top_level_list(data):
    try:
        dict(data)["tags"].append("MUTATED")
    except TypeError as error:
        _ran.append(_refused(error))
    else:
        _ran.append("written")
    return True


def guard_probe_indexes_items_and_values(data):
    items, values = data.items(), data.values()
    _ran.extend([type(items).__name__, type(values).__name__])
    position = list(data).index("a1")
    return items[position][1]["tier"] == values[position]["tier"] == "keep"


_PROBES = (
    guard_probe_mutates_raw,
    guard_probe_mutates_promoted,
    guard_probe_reads,
    guard_probe_writes_directly,
    guard_probe_writes_via_dict,
    guard_probe_writes_via_unpack,
    guard_probe_writes_via_rebus,
    guard_probe_writes_via_union,
    guard_probe_writes_via_update_into,
    guard_probe_writes_via_unbound_getitem,
    guard_probe_writes_via_unbound_get,
    guard_probe_writes_via_unbound_values,
    guard_probe_writes_via_unbound_items,
    guard_probe_writes_via_iteration,
    guard_probe_writes_top_level,
    guard_probe_merges_in_place,
    guard_probe_sidesteps_the_refusal,
    guard_probe_takes_copy_method,
    guard_probe_takes_copy_copy,
    guard_probe_takes_deepcopy,
    guard_probe_writes_deep_into_copy_method,
    guard_probe_writes_deep_into_copy_copy,
    guard_probe_writes_deep_into_deepcopy,
    guard_probe_reads_and_admits,
    guard_probe_requires_keep,
    guard_probe_appends_to_a_top_level_list,
    guard_probe_indexes_items_and_values,
    guard_probe_writes_deep_directly,
    guard_probe_writes_deep_via_dict,
    guard_probe_writes_deep_via_unpack,
    guard_probe_writes_deep_via_unbound_getitem,
    guard_probe_reads_with_a_keyword_default,
)


@pytest.fixture(autouse=True)
def _register_probes():
    """Registered per test, not at import.

    Any earlier test calling `clear_registry()` -- tests/cli/test_list_udfs.py does, around
    every test in it -- wiped an import-time registration, and a guard whose UDF is missing
    used to be swallowed as a warning and passed through. The record was then unmutated
    because the UDF never ran, so these tests passed without the view doing anything.
    """
    for fn in _PROBES:
        udf_tool(fn)
    _ran.clear()
    _taken.clear()
    _top_level_write.clear()
    yield


def _item(tier: str = "keep"):
    return {"source_guid": "g1", "content": {"a1": {"tier": tier}}}


def _deep_item() -> dict:
    """Five levels below a promoted namespace: deeper than any partial wrapping reaches."""
    return {
        "source_guid": "g1",
        "content": {"a1": {"tier": "keep", "items": [{"n": 1, "inner": {"k": [1]}}]}},
    }


def _evaluate(udf, item, context):
    return GuardEvaluator().evaluate(item, _GUARD, context=context, conditional_clause=udf.__name__)


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


class TestEveryRouteOutOfTheViewHandsOverReadOnlyNamespaces:
    """`dict(view)`, `{**view}`, `view | {}` and `Bus(view)` copy the view's storage
    without calling `__getitem__`, and the unbound `dict` methods read it directly. While
    that storage held the record's own containers, each of these handed one out writable,
    and the write reached the record with the guard returning normally and no warning.
    """

    @_CONTEXTS
    @pytest.mark.parametrize(
        "udf",
        [
            guard_probe_writes_directly,
            guard_probe_writes_via_dict,
            guard_probe_writes_via_unpack,
            guard_probe_writes_via_rebus,
            guard_probe_writes_via_union,
            guard_probe_writes_via_update_into,
            guard_probe_writes_via_unbound_getitem,
            guard_probe_writes_via_unbound_get,
            guard_probe_writes_via_unbound_values,
            guard_probe_writes_via_unbound_items,
            guard_probe_writes_via_iteration,
        ],
        ids=lambda udf: udf.__name__.removeprefix("guard_probe_"),
    )
    def test_a_write_is_refused_and_the_record_keeps_its_value(self, udf, context):
        item = _item()

        result = _evaluate(udf, item, context)

        assert _ran == ["refused"], "the write must be refused, not silently taken"
        assert item["content"]["a1"]["tier"] == "keep", item
        assert result.should_execute is True

    @_CONTEXTS
    def test_a_list_at_the_top_of_the_view_is_read_only_too(self, context):
        """Not every top-level value is a namespace: the record's own top-level fields sit
        beside them, and a list there was as reachable as a dict."""
        item = {"source_guid": "g1", "tags": ["a"], "content": {"a1": {"tier": "keep"}}}

        _evaluate(guard_probe_appends_to_a_top_level_list, item, context)

        assert _ran == ["refused"]
        assert item["tags"] == ["a"], item

    @_CONTEXTS
    @pytest.mark.parametrize("write", sorted(_TOP_LEVEL_WRITES))
    def test_a_write_to_the_view_itself_is_refused(self, write, context):
        item = _item()
        _top_level_write.append(write)

        _evaluate(guard_probe_writes_top_level, item, context)

        assert _ran == ["refused"], "the write must be refused, not silently taken"
        assert item == _item(), item

    @_CONTEXTS
    def test_an_in_place_merge_into_the_view_is_refused(self, context):
        """`view |= {...}` runs the C-level merge, not the refused `update` override."""
        item = _item()

        _evaluate(guard_probe_merges_in_place, item, context)

        assert _ran == ["refused"]
        assert item["content"]["a1"]["tier"] == "keep", item

    @_CONTEXTS
    @pytest.mark.parametrize(
        "udf",
        [
            guard_probe_writes_deep_directly,
            guard_probe_writes_deep_via_dict,
            guard_probe_writes_deep_via_unpack,
            guard_probe_writes_deep_via_unbound_getitem,
        ],
        ids=lambda udf: udf.__name__.removeprefix("guard_probe_"),
    )
    def test_a_write_several_levels_down_is_refused_and_the_record_is_untouched(self, udf, context):
        item = _deep_item()

        _evaluate(udf, item, context)

        assert _ran == ["refused"], "the write must be refused, not silently taken"
        assert item == _deep_item(), item

    @_CONTEXTS
    def test_the_record_is_out_of_reach_even_when_the_refusal_is_sidestepped(self, context):
        """Unbound `dict.__setitem__` and `list.append` skip the refusal, so each write
        lands; it must land on the view's own storage at every level, never on the record."""
        item = _deep_item()

        _evaluate(guard_probe_sidesteps_the_refusal, item, context)

        assert _ran == ["written"], "the UDF must have run to the writes"
        assert item == _deep_item(), item


class TestACopyOfTheViewIsAWritableDictThatSharesNothing:
    """`copy()`, `copy.copy` and `copy.deepcopy` all return a plain, deep, writable dict.

    That is the promise `ReadOnlyDict.copy()` makes one level down, and the type
    `Bus.copy()` returns.
    """

    @_CONTEXTS
    @pytest.mark.parametrize(
        "udf",
        [guard_probe_takes_copy_method, guard_probe_takes_copy_copy, guard_probe_takes_deepcopy],
        ids=["copy_method", "copy_copy", "copy_deepcopy"],
    )
    def test_a_write_to_the_copy_lands_on_the_copy_and_not_the_record(self, udf, context):
        item = _item()

        _evaluate(udf, item, context)

        assert _ran == ["written"], "the copy must be writable"
        (taken,) = _taken
        assert type(taken) is dict
        assert _a1(taken) == {"tier": "MUTATED"}
        assert item["content"]["a1"]["tier"] == "keep", item

    @_CONTEXTS
    @pytest.mark.parametrize(
        "udf",
        [
            guard_probe_writes_deep_into_copy_method,
            guard_probe_writes_deep_into_copy_copy,
            guard_probe_writes_deep_into_deepcopy,
        ],
        ids=["copy_method", "copy_copy", "copy_deepcopy"],
    )
    def test_the_copy_is_deep_so_a_nested_write_stays_on_the_copy(self, udf, context):
        item: dict = {"source_guid": "g1", "content": {"a1": {"tier": "keep", "items": [{"n": 1}]}}}

        _evaluate(udf, item, context)

        assert _ran == ["written"], "every level of the copy must be writable"
        (taken,) = _taken
        assert _a1(taken)["items"] == [{"n": 999}, {"n": 3}]
        assert item["content"]["a1"]["items"] == [{"n": 1}], item


class TestAReadingUdfStillDecidesTheGuard:
    @_CONTEXTS
    @pytest.mark.parametrize(
        ("tier", "should_execute", "behavior"),
        [("keep", True, None), ("drop", False, GuardBehavior.FILTER)],
    )
    def test_the_udf_reads_the_true_value_and_the_clause_still_decides(
        self, tier, should_execute, behavior, context
    ):
        result = _evaluate(guard_probe_reads_and_admits, _item(tier), context)

        assert _ran == [tier]
        assert (result.should_execute, result.behavior) == (should_execute, behavior)

    @_CONTEXTS
    @pytest.mark.parametrize(
        ("tier", "should_execute", "behavior"),
        [("keep", True, None), ("drop", False, GuardBehavior.SKIP)],
    )
    def test_require_reads_the_namespace_and_the_udf_answer_decides(
        self, tier, should_execute, behavior, context
    ):
        result = _evaluate(guard_probe_requires_keep, _item(tier), context)

        assert _ran == ["answered"], "a raising UDF is passed through, which looks like keep"
        assert (result.should_execute, result.behavior) == (should_execute, behavior)

    @_CONTEXTS
    @pytest.mark.parametrize(
        ("tier", "should_execute", "behavior"),
        [("keep", True, None), ("drop", False, GuardBehavior.SKIP)],
    )
    def test_get_with_a_keyword_default_reads_and_the_udf_answer_decides(
        self, tier, should_execute, behavior, context
    ):
        """`dict.get` takes `default` positionally only. A raising UDF is passed through,
        so a view that refused the keyword would admit every record the UDF rejects."""
        result = _evaluate(guard_probe_reads_with_a_keyword_default, _item(tier), context)

        assert _ran == ["answered"], "a raising UDF is passed through, which looks like keep"
        assert (result.should_execute, result.behavior) == (should_execute, behavior)

    @pytest.mark.parametrize(
        ("tier", "should_execute", "behavior"),
        [("keep", True, None), ("drop", False, GuardBehavior.SKIP)],
    )
    def test_items_and_values_index_like_a_readonly_dict(self, tier, should_execute, behavior):
        """Lists, as `ReadOnlyDict.items()`/`values()` are one level down. A UDF indexing
        them would otherwise raise, and a raising UDF is passed through on either tier."""
        result = _evaluate(guard_probe_indexes_items_and_values, _item(tier), {"other": 1})

        assert _ran == ["list", "list"]
        assert (result.should_execute, result.behavior) == (should_execute, behavior)
