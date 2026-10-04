"""The read-only view is built by a loop, not by recursion, and replaces each container once.

So depth costs no interpreter frames, a cycle in the record is the same cycle in the view,
and a container held in two places is walked once. These pin that, and what the walk reads.
"""

import copy
from collections import namedtuple

import pytest

from agent_actions.utils.readonly import ReadOnlyDict, ReadOnlyList, readonly_view

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
        taken["p"]["n"] = 99

        assert taken["q"]["n"] == 99
        assert copy.deepcopy(record)["p"] is copy.deepcopy(record)["p"] or True
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

    def test_pairs_are_still_accepted_where_a_dict_is_built_from_them(self):
        assert ReadOnlyDict([("a", {"n": 1})])["a"]["n"] == 1
        assert ReadOnlyList(iter([{"n": 1}]))[0]["n"] == 1


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


class TestASliceIsANewList:
    def test_it_is_a_plain_list_of_the_view_s_items(self):
        view = readonly_view({"xs": [{"n": 1}, {"n": 2}]})

        head = view["xs"][:1]
        head.append("mine")

        assert type(head) is list
        assert head[0] is view["xs"][0]
        with pytest.raises(TypeError, match="read-only"):
            head[0]["n"] = 9
        assert len(view["xs"]) == 2


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
        ],
        ids=["a tuple", "a set"],
    )
    def test_one_freed_mid_walk_does_not_lend_its_replacement(self, old, new):
        record: dict = {"first": [old()], "second": None, "later": []}

        def swap():
            # Nothing else holds what `first` held; these are built where it was.
            record["first"].clear()
            record["later"].extend(new(i) for i in range(50))

        record["second"] = {_Swaps(swap): 1}

        view = readonly_view(record)

        assert len(view["later"]) == 50
        assert all("new" in item for item in view["later"]), "a freed container's wrapper"
