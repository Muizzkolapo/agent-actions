"""The read-only view is built by a loop, not by recursion, and replaces each container once.

So depth costs no interpreter frames, a cycle in the record is the same cycle in the view,
and a container held in two places is walked once. These pin that, and what the walk reads.
"""

import copy
import signal
import threading
from collections import namedtuple

import pytest

from agent_actions.utils.readonly import ReadOnlyDict, ReadOnlyList, ReadOnlySet, readonly_view
from agent_actions.utils.udf_management.bus import ReadOnlyBus


@pytest.fixture(autouse=True)
def _a_walk_that_does_not_end_fails_here():
    """Without the memo a cycle is walked for ever, taking memory as it goes. Stopped
    here, that is one failed test and not a run that never reports."""
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(*_):
        raise AssertionError("the walk did not end within ten seconds")

    before = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, 10)
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, before)


# Past every interpreter's recursion limit.
DEPTH = 5000


def _nested(kind: str, depth: int = DEPTH):
    value: object = {"leaf": 1}
    for level in range(depth):
        if kind == "dicts" or (kind == "alternating" and level % 2):
            value = {"in": value}
        elif kind == "tuples":
            value = (value,)
        else:
            value = [value]
    return value


def _descend(value):
    """The innermost container and how many were passed on the way, without recursion."""
    passed = 0
    while True:
        inner = value["in"] if isinstance(value, dict) and "in" in value else None
        if inner is None and isinstance(value, list | tuple):
            inner = value[0]
        if inner is None:
            return value, passed
        value, passed = inner, passed + 1


@pytest.mark.parametrize("kind", ["dicts", "lists", "tuples", "alternating"])
class TestDepthCostsNoFrames:
    def test_a_record_deeper_than_the_recursion_limit_is_viewed_to_the_bottom(self, kind):
        view = readonly_view({"deep": _nested(kind)})

        bottom, passed = _descend(view["deep"])

        assert passed == DEPTH
        assert isinstance(bottom, ReadOnlyDict)
        with pytest.raises(TypeError, match="read-only"):
            bottom["leaf"] = 2

    def test_its_copy_is_plain_to_the_bottom(self, kind):
        record = {"deep": _nested(kind)}

        taken = readonly_view(record).copy()
        bottom, passed = _descend(taken["deep"])
        bottom["leaf"] = 2

        assert passed == DEPTH
        assert type(bottom) is dict
        assert _descend(record["deep"])[0] == {"leaf": 1}, "the copy shares with the record"


class TestACycleIsTheSameCycle:
    def test_a_dict_that_holds_itself(self):
        record: dict = {"tier": "keep"}
        record["me"] = record

        view = readonly_view(record)

        assert view["me"] is view
        assert view["me"]["me"]["tier"] == "keep"

    def test_a_list_that_holds_itself(self):
        rows: list = [1]
        rows.append(rows)

        view = readonly_view({"rows": rows})

        assert view["rows"][1] is view["rows"]
        assert isinstance(view["rows"], ReadOnlyList)

    def test_a_cycle_through_a_tuple(self):
        record: dict = {"tier": "keep"}
        record["pair"] = (record, 1)

        view = readonly_view(record)

        assert view["pair"][0] is view
        assert type(view["pair"]) is tuple

    def test_nothing_on_the_cycle_is_the_record_s(self):
        child: dict = {"n": 1}
        record = {"child": child}
        child["parent"] = record

        view = readonly_view(record)

        assert view["child"]["parent"] is view
        assert view["child"] is not child
        with pytest.raises(TypeError, match="read-only"):
            view["child"]["parent"]["child"]["n"] = 2
        assert child["n"] == 1

    @pytest.mark.parametrize("take", [lambda v: v.copy(), copy.copy, copy.deepcopy])
    def test_a_copy_keeps_the_cycle_and_is_plain(self, take):
        record: dict = {"rows": [1]}
        record["me"] = record
        record["rows"].append(record["rows"])

        taken = take(readonly_view(record))

        assert type(taken) is dict and type(taken["rows"]) is list
        assert taken["me"] is taken
        assert taken["rows"][1] is taken["rows"]
        taken["rows"].append(2)
        assert record["rows"][0] == 1 and len(record["rows"]) == 2


class TestASharedContainerIsWalkedOnce:
    def test_two_keys_holding_one_container_hold_one_wrapper(self):
        shared = {"n": 1}

        view = readonly_view({"p": shared, "q": shared, "xs": [shared]})

        assert view["p"] is view["q"] is view["xs"][0]
        assert view["p"] is not shared

    @pytest.mark.parametrize("empty", [{}, []], ids=["an empty dict", "an empty list"])
    def test_an_empty_container_held_twice_is_one_wrapper_too(self, empty):
        """It is found in the memo while still empty, so the memo cannot be read by truth."""
        view = readonly_view({"p": empty, "q": empty})

        assert view["p"] is view["q"]

    def test_sharing_at_every_level_costs_one_wrapper_a_level(self):
        """Wrapped once per reference, eighteen levels are half a million wrappers."""
        levels = 18
        value: object = {"leaf": 1}
        for _ in range(levels):
            value = {"left": value, "right": value}

        view = readonly_view(value)

        seen, queue = set(), [view]
        while queue:
            node = queue.pop()
            if id(node) not in seen and isinstance(node, dict):
                seen.add(id(node))
                queue.extend(dict.values(node))
        assert len(seen) == levels + 1

    def test_a_copy_has_the_record_s_shape_as_deepcopy_gives(self):
        shared = {"n": 1}
        record = {"p": shared, "q": shared}

        taken = readonly_view(record).copy()
        plain = copy.deepcopy(record)

        assert taken["p"] is taken["q"]
        assert plain["p"] is plain["q"], "copy.deepcopy no longer keeps sharing"
        taken["p"]["n"] = 99
        assert shared["n"] == 1


class TestTheWalkReadsStorageNotAccessors:
    """A subclass's accessors are user code: they can raise, or build a new container on
    every call, which a walk that trusted them would follow for ever."""

    def test_a_dict_subclass_is_read_as_stored(self):
        class Fabricates(dict):
            def __iter__(self):
                raise AssertionError("the walk ran a subclass accessor")

            def keys(self):
                raise AssertionError("the walk ran a subclass accessor")

            def items(self):
                raise AssertionError("the walk ran a subclass accessor")

            def __getitem__(self, key):
                return Fabricates(again=Fabricates())

        view = readonly_view({"ns": Fabricates(a={"n": 1})})

        assert type(view["ns"]) is ReadOnlyDict
        assert dict.items(view["ns"]) == {"a": {"n": 1}}.items()
        assert isinstance(view["ns"]["a"], ReadOnlyDict)

    def test_a_list_subclass_is_read_as_stored(self):
        class Fabricates(list):
            def __iter__(self):
                raise AssertionError("the walk ran a subclass accessor")

            def __getitem__(self, index):
                raise AssertionError("the walk ran a subclass accessor")

            def copy(self):
                raise AssertionError("the walk ran a subclass accessor")

        view = readonly_view({"xs": Fabricates([{"n": 1}])})

        assert type(view["xs"]) is ReadOnlyList
        assert isinstance(view["xs"][0], ReadOnlyDict)

    def test_a_tuple_subclass_is_read_as_stored(self):
        class YieldsItself(tuple):
            def __iter__(self):
                yield self

        view = readonly_view({"t": YieldsItself(({"n": 1},))})

        assert type(view["t"]) is tuple
        assert isinstance(view["t"][0], ReadOnlyDict)

    def test_a_tuple_subclass_nested_in_a_tuple_is_read_as_stored_too(self):
        class Raises(tuple):
            def __iter__(self):
                raise AssertionError("the walk ran a subclass accessor")

        view = readonly_view({"t": (Raises(({"n": 1},)), 2)})

        assert isinstance(view["t"][0][0], ReadOnlyDict)

    def test_a_dict_that_grows_while_its_keys_are_hashed_is_read_as_it_was(self):
        """The storage is read all at once, so it cannot change size under the loop."""
        grown: dict = {}

        class Grows:
            def __init__(self) -> None:
                self.hashed = 0

            def __hash__(self) -> int:
                self.hashed += 1
                if self.hashed == 2:
                    grown["added"] = {"n": 2}
                return 5

        grown[Grows()] = {"n": 1}

        view = readonly_view({"ns": grown})

        assert len(view["ns"]) == 1

    def test_a_subclass_handed_straight_to_a_wrapper_is_read_as_stored_too(self):
        class Raises(dict):
            def keys(self):
                raise AssertionError("the walk ran a subclass accessor")

            def __iter__(self):
                raise AssertionError("the walk ran a subclass accessor")

        class RaisesToo(list):
            def __iter__(self):
                raise AssertionError("the walk ran a subclass accessor")

        assert ReadOnlyDict(Raises(a={"n": 1}))["a"]["n"] == 1
        assert ReadOnlyList(RaisesToo([{"n": 1}]))[0]["n"] == 1
        assert ReadOnlyBus(Raises(a1={"n": 1})).require("a1")["n"] == 1

    def test_pairs_are_still_accepted_where_a_dict_is_built_from_them(self):
        assert ReadOnlyDict([("a", {"n": 1})])["a"]["n"] == 1
        assert ReadOnlyList(iter([{"n": 1}]))[0]["n"] == 1


class TestAValueThatOnlyClaimsToBeAContainer:
    """`isinstance` believes a `weakref.proxy` to a dict, and a mock with `spec=dict`.
    Neither has a dict's storage. Handed over raw, a proxy would let a write through to
    what it stands for, so the view is not built at all."""

    def test_a_proxy_to_a_dict_is_refused_not_handed_over(self):
        import weakref

        class Weakable(dict):
            pass

        held = Weakable(a=[1])

        with pytest.raises(TypeError):
            readonly_view({"ns": weakref.proxy(held)})


Point = namedtuple("Point", "x y")


class TestTuples:
    def test_a_tuple_holding_no_container_is_handed_over_as_it_is(self):
        """It is immutable and so is everything in it, and rebuilt it would lose its type."""
        point = Point(1, 2)

        view = readonly_view({"pt": point})

        assert view["pt"] is point
        assert view["pt"].x == 1

    def test_a_tuple_holding_a_container_is_rebuilt_around_a_wrapper(self):
        inner = {"n": 1}

        view = readonly_view({"t": (inner, "x")})

        assert isinstance(view["t"][0], ReadOnlyDict)
        assert view["t"][0] is not inner
        assert view["t"][1] == "x"


class TestASliceIsReadOnlyToo:
    """Whatever is read from a view is read-only until `copy()` is called on it, and
    that copy is the deep one. A slice is no exception."""

    def test_it_holds_the_view_s_own_items_and_refuses_a_write(self):
        view = readonly_view({"xs": [{"n": 1}, {"n": 2}]})

        head = view["xs"][:1]

        assert isinstance(head, ReadOnlyList)
        assert head[0] is view["xs"][0]
        with pytest.raises(TypeError, match="read-only"):
            head.append("mine")
        with pytest.raises(TypeError, match="read-only"):
            head[0]["n"] = 9

    def test_its_copy_is_deep_and_writable(self):
        record = {"xs": [{"n": 1}, {"n": 2}]}

        taken = readonly_view(record)["xs"][:1].copy()
        taken[0]["n"] = 9
        taken.append("mine")

        assert type(taken) is list and type(taken[0]) is dict
        assert record == {"xs": [{"n": 1}, {"n": 2}]}

    def test_a_negative_or_stepped_slice_is_what_a_list_gives(self):
        view = readonly_view({"xs": [1, 2, 3, 4]})

        assert view["xs"][::-2] == [4, 2]
        assert view["xs"][-1] == 4


def _iadd(target, other):
    target += other


def _imul(target, other):
    target *= other


def _ior(target, other):
    target |= other


def _iand(target, other):
    target &= other


def _isub(target, other):
    target -= other


def _ixor(target, other):
    target ^= other


_WRITES = {
    "dict": {
        "setitem": lambda d: d.__setitem__("k", 1),
        "delitem": lambda d: d.__delitem__("a"),
        "ior": lambda d: _ior(d, {"k": 1}),
        "clear": lambda d: d.clear(),
        "pop": lambda d: d.pop("a"),
        "popitem": lambda d: d.popitem(),
        "setdefault": lambda d: d.setdefault("k", 1),
        "update": lambda d: d.update(k=1),
    },
    "list": {
        "setitem": lambda xs: xs.__setitem__(0, 9),
        "delitem": lambda xs: xs.__delitem__(0),
        "iadd": lambda xs: _iadd(xs, [9]),
        "imul": lambda xs: _imul(xs, 2),
        "append": lambda xs: xs.append(9),
        "clear": lambda xs: xs.clear(),
        "extend": lambda xs: xs.extend([9]),
        "insert": lambda xs: xs.insert(0, 9),
        "pop": lambda xs: xs.pop(),
        "remove": lambda xs: xs.remove(1),
        "reverse": lambda xs: xs.reverse(),
        "sort": lambda xs: xs.sort(),
    },
    "set": {
        "iand": lambda m: _iand(m, {1}),
        "ior": lambda m: _ior(m, {9}),
        "isub": lambda m: _isub(m, {1}),
        "ixor": lambda m: _ixor(m, {1}),
        "add": lambda m: m.add(9),
        "clear": lambda m: m.clear(),
        "difference_update": lambda m: m.difference_update({1}),
        "discard": lambda m: m.discard(1),
        "intersection_update": lambda m: m.intersection_update({1}),
        "pop": lambda m: m.pop(),
        "remove": lambda m: m.remove(1),
        "symmetric_difference_update": lambda m: m.symmetric_difference_update({1}),
        "update": lambda m: m.update({9}),
    },
}


@pytest.mark.parametrize(
    "kind, write",
    [(kind, name) for kind, writes in _WRITES.items() for name in writes],
)
def test_every_way_of_writing_to_a_view_is_refused(kind, write):
    record = {"dict": {"a": 1}, "list": [1, 2], "set": {1, 2}}

    with pytest.raises(TypeError, match="read-only"):
        _WRITES[kind][write](readonly_view(record)[kind])

    assert record == {"dict": {"a": 1}, "list": [1, 2], "set": {1, 2}}


class TestASetIsReadOnlyWhereverItSits:
    @pytest.mark.parametrize(
        "holder",
        [lambda s: [s], lambda s: (s, 1), lambda s: {"k": s}],
        ids=["list", "tuple", "dict"],
    )
    def test_a_set_held_in_any_container_refuses_a_write(self, holder):
        members = {1, 2}

        view = readonly_view({"h": holder(members)})
        held = view["h"]["k"] if isinstance(view["h"], dict) else view["h"][0]

        assert isinstance(held, ReadOnlySet)
        with pytest.raises(TypeError, match="read-only"):
            held.add(3)
        assert members == {1, 2}


class TestEveryCopyIsPlainAndDeep:
    @pytest.mark.parametrize("take", [lambda v: v.copy(), copy.copy, copy.deepcopy])
    def test_a_list_view(self, take):
        record = {"xs": [{"n": 1}]}

        taken = take(readonly_view(record)["xs"])
        taken[0]["n"] = 9
        taken.append("mine")

        assert type(taken) is list and type(taken[0]) is dict
        assert record == {"xs": [{"n": 1}]}

    @pytest.mark.parametrize("take", [lambda v: v.copy(), copy.copy, copy.deepcopy])
    def test_a_set_view(self, take):
        record = {"tags": {"a", "b"}}

        taken = take(readonly_view(record)["tags"])
        taken.add("c")

        assert type(taken) is set
        assert record["tags"] == {"a", "b"}


class TestValuesAndItemsAreLists:
    """A guard that indexes them must not raise: a guard whose UDF raises passes its record."""

    def test_below_the_top_level_too(self):
        namespace = readonly_view({"ns": {"a": {"n": 1}}})["ns"]

        assert namespace.values()[0]["n"] == 1
        assert namespace.items()[0][0] == "a"
        assert isinstance(namespace.values()[0], ReadOnlyDict)


class TestTheBusIsTheViewOfItsContext:
    def test_a_context_that_holds_itself_is_the_bus_all_the_way_round(self):
        context: dict = {"a1": {"tier": "keep"}}
        context["self"] = context
        context["a1"]["up"] = context

        bus = ReadOnlyBus(context)

        assert bus["self"] is bus
        assert bus["a1"]["up"] is bus
        assert bus.require("a1")["tier"] == "keep"

    def test_its_copy_is_one_plain_dict_with_the_same_shape(self):
        context: dict = {"a1": {"tier": "keep"}}
        context["self"] = context

        taken = ReadOnlyBus(context).copy()
        taken["a1"]["tier"] = "mine"

        assert type(taken) is dict
        assert taken["self"] is taken
        assert context["a1"]["tier"] == "keep"

    def test_keyword_namespaces_are_still_accepted(self):
        bus = ReadOnlyBus({"a1": {"n": 1}}, other={"n": 2})

        assert bus["other"]["n"] == 2
        with pytest.raises(TypeError, match="read-only"):
            bus["other"]["n"] = 3


class _Swaps:
    """A dict key whose second hashing, which the walk causes, runs *swap*."""

    def __init__(self, swap) -> None:
        self.swap = swap
        self.hashed = 0

    def __hash__(self) -> int:
        self.hashed += 1
        if self.hashed == 2:
            self.swap()
        return 11


class TestAReplacedContainerIsKeptAliveForTheWalk:
    """The memo is keyed by `id()`, which is unique only among live objects. Freed during
    the walk, a container's address goes to the next one built, which would then be handed
    the first one's replacement."""

    @pytest.mark.parametrize(
        "old, new",
        [
            (lambda: ("old", {"n": 1}), lambda i: ("new", {"n": i})),
            (lambda: {"old", "x"}, lambda i: {"new", i}),
            (lambda: {"old": 1}, lambda i: {"new": i}),
        ],
        ids=["a tuple", "a set", "a dict"],
    )
    def test_one_freed_mid_walk_does_not_lend_its_replacement(self, old, new):
        # Laid out so the walk has replaced `first`'s item, and has read every container
        # before the key, by the time the key is hashed: nothing the walk still holds from
        # reading them keeps the item alive, only the memo's own hold can. `target` is
        # nested deep enough to be read last.
        target: list = []
        record: dict = {"first": [old()], "second": [None], "later": [[[target]]]}

        def swap():
            # Nothing else holds what `first` held; these are built where it was. A list,
            # not a generator: its frame would take the freed address first.
            record["first"].clear()
            target.extend([new(i) for i in range(50)])

        record["second"][0] = {_Swaps(swap): 1}

        view = readonly_view(record)
        seen = view["later"][0][0][0]

        assert len(seen) == 50
        assert all("new" in item for item in seen), "a freed container's replacement"
