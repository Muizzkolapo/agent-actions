"""The read-only view handed to a guard UDF: it must refuse every way in, and stay usable.

A shallow guard is no guard -- `data["a1"]["tier"] = x` reaches straight through one --
and a view that breaks well-behaved UDFs is not shippable either.
"""

from typing import Any

import pytest

from agent_actions.utils.readonly import ReadOnlyDict, ReadOnlyList, readonly_view


class TestTheViewRefusesEveryWayIn:
    """A shallow guard is no guard: `data["a1"]["tier"] = x` reaches straight through one."""

    def test_a_top_level_write_is_refused(self):
        with pytest.raises(TypeError, match="read-only"):
            readonly_view({"a": 1})["a"] = 2

    def test_a_nested_write_is_refused(self):
        with pytest.raises(TypeError, match="read-only"):
            readonly_view({"a": {"b": 1}})["a"]["b"] = 2

    def test_a_write_through_items_is_refused(self):
        view = readonly_view({"a": {"b": 1}})
        for _, value in view.items():
            with pytest.raises(TypeError, match="read-only"):
                value["b"] = 2

    def test_a_list_mutation_is_refused(self):
        with pytest.raises(TypeError, match="read-only"):
            readonly_view({"xs": [1, 2]})["xs"].append(3)

    def test_a_write_to_a_dict_inside_a_list_is_refused(self):
        with pytest.raises(TypeError, match="read-only"):
            readonly_view({"xs": [{"n": 1}]})["xs"][0]["n"] = 2

    def test_a_write_through_iteration_of_a_list_is_refused(self):
        view = readonly_view({"xs": [{"n": 1}]})
        for entry in view["xs"]:
            with pytest.raises(TypeError, match="read-only"):
                entry["n"] = 2

    def test_in_place_operators_are_refused(self):
        """`|=` and `+=` are C-level and do NOT route through update/extend — measured:
        with only those overridden, both mutate the underlying container in place."""
        view = readonly_view({"a": 1, "xs": [1]})
        with pytest.raises(TypeError, match="read-only"):
            view |= {"b": 2}
        # Bound first: `view["xs"] += [2]` would raise in __setitem__ regardless, so it
        # does not isolate __iadd__.
        xs = view["xs"]
        with pytest.raises(TypeError, match="read-only"):
            xs += [2]

    def test_pop_and_update_are_refused(self):
        view = readonly_view({"a": 1})
        for call in (lambda: view.pop("a"), lambda: view.update({"a": 2}), view.clear):
            with pytest.raises(TypeError, match="read-only"):
                call()

    def test_setdefault_and_a_sets_add_and_in_place_or_are_refused(self):
        view = readonly_view({"a": 1, "s": {1}})
        with pytest.raises(TypeError, match="read-only"):
            view.setdefault("b", 2)

        members = view["s"]
        with pytest.raises(TypeError, match="read-only"):
            members.add(2)
        with pytest.raises(TypeError, match="read-only"):
            members |= {2}

        assert "b" not in view
        assert view["s"] == {1}


class TestTheViewStaysUsable:
    """It is handed to user code, so the shapes that code relies on must keep working."""

    def test_it_is_still_a_dict_for_isinstance_and_json(self):
        import json

        view = readonly_view({"a": {"b": 1}})

        assert isinstance(view, dict)
        assert json.loads(json.dumps(view)) == {"a": {"b": 1}}

    def test_reads_and_membership_work(self):
        view = readonly_view({"a": {"b": 1}, "xs": [1]})

        assert view["a"]["b"] == 1
        assert view.get("missing", "dflt") == "dflt"
        assert "a" in view and len(view) == 2
        assert list(view["xs"]) == [1]

    def test_copy_returns_something_writable(self):
        """The message tells the author to copy; that has to actually work."""
        view = readonly_view({"a": {"b": 1}})
        writable = view.copy()
        writable["a"] = 2

        assert writable["a"] == 2
        assert view["a"]["b"] == 1

    def test_the_wrappers_are_the_declared_types(self):
        view = readonly_view({"xs": [{"n": 1}]})

        assert isinstance(view, ReadOnlyDict)
        assert isinstance(view["xs"], ReadOnlyList)
        assert isinstance(view["xs"][0], ReadOnlyDict)


class TestTakingACopyCannotReachTheRecord:
    """The module promises a write cannot reach the record "at any depth". Three documented
    ways of taking a copy broke that promise, and the escape hatch the error message
    recommends was one of them.

    `dict(view)` and `{**view}` read the underlying storage through a C fast path that no
    Python override intercepts, so the fix is what the storage holds: wrapped values, not
    the record's own containers.
    """

    @staticmethod
    def _record():
        return {"ns": {"inner": {"x": 1}}, "xs": [{"n": 1}]}

    def test_copy_copy_does_not_raise(self):
        """It raised: `copy` rebuilds a dict subclass by assigning into a new instance, and
        `__setitem__` refuses. The author is told to copy and then cannot."""
        import copy

        record = self._record()
        copy.copy(readonly_view(record))

    def test_copy_deepcopy_does_not_raise(self):
        import copy

        record = self._record()
        copy.deepcopy(readonly_view(record))

    def test_copy_copy_yields_a_copy_a_nested_write_cannot_escape(self):
        import copy

        record = self._record()
        taken = copy.copy(readonly_view(record))
        try:
            taken["ns"]["inner"]["x"] = 999
        except TypeError:
            pass
        assert record["ns"]["inner"]["x"] == 1

    def test_the_documented_copy_is_deep(self):
        """`copy()` is what the error message tells a UDF author to use, so a nested write
        through it must land on the copy -- writable, and not the record."""
        record = self._record()
        writable = readonly_view(record).copy()
        writable["ns"]["inner"]["x"] = 999

        assert record["ns"]["inner"]["x"] == 1
        assert writable["ns"]["inner"]["x"] == 999

    def test_a_nested_write_through_dict_of_the_view_cannot_reach_the_record(self):
        record = self._record()
        shallow = dict(readonly_view(record))
        try:
            shallow["ns"]["inner"]["x"] = 999
        except TypeError:
            pass
        assert record["ns"]["inner"]["x"] == 1

    def test_a_nested_write_through_splatting_the_view_cannot_reach_the_record(self):
        record = self._record()
        shallow = {**readonly_view(record)}
        try:
            shallow["xs"][0]["n"] = 999
        except TypeError:
            pass
        assert record["xs"][0]["n"] == 1


class TestContainersThatAreNotDictsOrLists:
    """`_readonly` knew dict and list, so a mutable container reached by any other route
    was handed over raw. A tuple is immutable but what it holds need not be, and a set is
    mutable itself. Both appear in records built by Python UDF tools, which are not
    restricted to JSON shapes.
    """

    def test_a_dict_inside_a_tuple_is_wrapped(self):
        record = {"t": ({"a": 1},)}
        view = readonly_view(record)
        with pytest.raises(TypeError, match="read-only"):
            view["t"][0]["a"] = 99
        assert record["t"][0]["a"] == 1

    def test_a_set_refuses_mutation(self):
        record = {"s": {1, 2}}
        view = readonly_view(record)
        with pytest.raises(TypeError, match="read-only"):
            view["s"].add(99)
        assert record["s"] == {1, 2}

    def test_a_list_inside_a_tuple_is_wrapped(self):
        record = {"t": ([1, 2],)}
        view = readonly_view(record)
        with pytest.raises(TypeError, match="read-only"):
            view["t"][0].append(3)
        assert record["t"][0] == [1, 2]

    def test_a_copy_does_not_share_a_tuple_wrapped_dict(self):
        """`copy()` promises it shares nothing mutable with the record."""
        record = {"t": ({"a": 1},)}
        writable = readonly_view(record).copy()
        writable["t"][0]["a"] = 99

        assert record["t"][0]["a"] == 1

    def test_a_copy_does_not_share_a_set(self):
        record = {"s": {1, 2}}
        writable = readonly_view(record).copy()
        writable["s"].add(99)

        assert record["s"] == {1, 2}

    def test_a_tuple_is_still_a_tuple_and_a_set_still_a_set(self):
        """Wrapping must not change the type a reading UDF sees."""
        view = readonly_view({"t": (1, 2), "s": {1}, "fs": frozenset({1})})

        assert isinstance(view["t"], tuple)
        assert isinstance(view["s"], set)
        assert isinstance(view["fs"], frozenset)
        assert view["t"] == (1, 2)
        assert view["s"] == {1}


class TestACyclicRecordIsWrappedWithoutRecursing:
    """Wrapping is eager, so construction walks the whole structure. Without a memo a record
    holding a reference back to itself recursed until the stack ran out, and `copy()` would
    have done the same once construction stopped raising. A UDF tool builds records in
    Python, so it can hand back a cycle.
    """

    def test_a_self_referential_record_is_wrapped_and_a_nested_write_is_still_refused(self):
        record: dict[str, Any] = {"a": {"b": 1}}
        record["self"] = record

        view = readonly_view(record)

        assert view["self"]["self"]["a"]["b"] == 1
        with pytest.raises(TypeError, match="read-only"):
            view["self"]["a"]["b"] = 99
        assert record["a"]["b"] == 1

    def test_the_cycle_in_the_view_points_back_at_the_view_and_not_at_the_record(self):
        record: dict[str, Any] = {"a": 1}
        record["self"] = record

        view = readonly_view(record)

        assert view["self"] is view
        assert view["self"] is not record

    def test_a_mutually_referential_pair_is_wrapped_and_refuses_a_write(self):
        a: dict[str, Any] = {"name": "a"}
        b = {"name": "b", "a": a}
        a["b"] = b

        view = readonly_view({"a": a})

        assert view["a"]["b"]["a"]["name"] == "a"
        assert view["a"]["b"]["a"] is view["a"]
        with pytest.raises(TypeError, match="read-only"):
            view["a"]["b"]["name"] = "mutated"
        assert b["name"] == "b"

    def test_a_cycle_through_a_list_is_wrapped_and_refuses_a_write(self):
        inner: list[Any] = [{"n": 1}]
        inner.append(inner)

        view = readonly_view({"xs": inner})

        assert view["xs"][1] is view["xs"]
        assert view["xs"][1][1][0]["n"] == 1
        with pytest.raises(TypeError, match="read-only"):
            view["xs"][1][0]["n"] = 99
        assert inner[0]["n"] == 1

    def test_a_cycle_through_a_value_inside_a_tuple_is_wrapped_and_refuses_a_write(self):
        record: dict[str, Any] = {"n": 1}
        record["t"] = ({"back": record},)

        view = readonly_view(record)

        assert view["t"][0]["back"] is view
        with pytest.raises(TypeError, match="read-only"):
            view["t"][0]["back"]["n"] = 99
        assert record["n"] == 1

    def test_a_cycle_whose_entry_point_is_the_tuple_itself_is_wrapped(self):
        """A tuple cannot be memoised before its items are wrapped, so the walk meets it a
        second time on the way round; it must still terminate."""
        holder: list[Any] = [{"n": 1}]
        pair = (holder,)
        holder.append(pair)

        view = readonly_view({"t": pair})

        assert view["t"][0][0]["n"] == 1
        with pytest.raises(TypeError, match="read-only"):
            view["t"][0][0]["n"] = 99
        assert holder[0]["n"] == 1

    def test_copy_of_a_cyclic_record_terminates_and_is_writable(self):
        record: dict[str, Any] = {"a": {"b": 1}}
        record["self"] = record

        writable = readonly_view(record).copy()
        writable["a"]["b"] = 99

        assert writable["a"]["b"] == 99
        assert writable["self"] is writable
        assert record["a"]["b"] == 1

    def test_a_cycle_through_nested_tuples_is_wrapped_and_refuses_a_write(self):
        """Nested tuples on the cycle multiply the re-walk -- each is re-entered before it can
        be memoised -- so the depth a cycle costs grows with the nesting. Shallow nesting must
        still come back wrapped; `_readonly`'s tuple branch records the measured ceiling."""
        lists: list[list[Any]] = [[] for _ in range(5)]
        node: Any = lists[0]
        for lst in lists[1:]:
            node = (node, lst)
        top = (node,)
        for lst in lists:
            lst.append(top)
        lists[0].append({"n": 1})

        view = readonly_view({"t": top})

        deepest = view["t"][0][0][0][0][0]
        assert deepest[1]["n"] == 1
        with pytest.raises(TypeError, match="read-only"):
            deepest[1]["n"] = 99
        with pytest.raises(TypeError, match="read-only"):
            deepest.append("x")
        assert lists[0][1]["n"] == 1

    def test_copy_of_a_cycle_through_a_list_terminates_and_is_writable(self):
        """The copy walk has its own list branch, so a dict-only cycle does not exercise it."""
        inner: list[Any] = [{"n": 1}]
        inner.append(inner)

        writable = readonly_view({"xs": inner}).copy()
        writable["xs"][0]["n"] = 99

        assert writable["xs"][1] is writable["xs"]
        assert writable["xs"][0]["n"] == 99
        assert inner[0]["n"] == 1

    def test_copy_of_a_cycle_that_runs_through_a_tuple_terminates_and_is_writable(self):
        """The cycle has to pass THROUGH the tuple, not merely sit beside one: a record holding
        a tuple and a cycle separately runs the copy walk's tuple branch but never meets the
        cycle there, and that branch recursing without the memo is what reinstates the crash."""
        record: dict[str, Any] = {"n": 1}
        record["t"] = ({"back": record},)

        writable = readonly_view(record).copy()
        writable["n"] = 99

        assert writable["t"][0]["back"] is writable
        assert writable["t"][0]["back"]["n"] == 99
        assert record["n"] == 1

    def test_copy_on_a_nested_list_view_terminates_on_a_cycle_through_that_list(self):
        """`ReadOnlyList.copy` is a second entry point into the copy walk, reached when a UDF
        copies a namespace's list rather than the whole view."""
        inner: list[Any] = [{"n": 1}]
        inner.append(inner)

        writable = readonly_view({"xs": inner})["xs"].copy()
        writable[0]["n"] = 99

        assert writable[1] is writable
        assert writable[1][0]["n"] == 99
        assert inner[0]["n"] == 1

    def test_copy_on_a_nested_list_view_keeps_a_repeated_element_shared(self):
        shared = {"n": 1}

        writable = readonly_view({"xs": [shared, shared]})["xs"].copy()
        writable[0]["n"] = 99

        assert writable[0] is writable[1]
        assert writable[1]["n"] == 99
        assert shared["n"] == 1

    def test_the_c_fast_path_copies_of_a_cyclic_view_still_carry_wrappers(self):
        """`dict(view)`, `{**view}` and `list(view)` copy what the storage holds, so the memo
        must have put wrappers there and not the record's own containers."""
        record: dict[str, Any] = {"ns": {"x": 1}, "xs": [{"n": 1}]}
        record["self"] = record
        view = readonly_view(record)

        with pytest.raises(TypeError, match="read-only"):
            dict(view)["ns"]["x"] = 99
        with pytest.raises(TypeError, match="read-only"):
            {**view}["self"]["ns"]["x"] = 99
        with pytest.raises(TypeError, match="read-only"):
            list(view["xs"])[0]["n"] = 99

        assert record["ns"]["x"] == 1
        assert record["xs"][0]["n"] == 1

    def test_the_escape_hatches_on_a_cyclic_record_share_no_mutable_with_the_record(self):
        import copy as copy_module

        record: dict[str, Any] = {
            "ns": {"inner": {"x": 1}},
            "xs": [{"n": 1}],
            "t": ({"a": 1},),
            "s": {1},
        }
        record["self"] = record
        view = readonly_view(record)

        for taken in (view.copy(), copy_module.copy(view), copy_module.deepcopy(view)):
            taken["ns"]["inner"]["x"] = 999
            taken["xs"][0]["n"] = 888
            taken["t"][0]["a"] = 777
            taken["s"].add(666)
            assert taken["ns"]["inner"]["x"] == 999
            assert taken["xs"][0]["n"] == 888
            assert taken["t"][0]["a"] == 777
            assert taken["s"] == {1, 666}

        assert record["ns"]["inner"]["x"] == 1
        assert record["xs"][0]["n"] == 1
        assert record["t"][0]["a"] == 1
        assert record["s"] == {1}


class TestAliasingInsideTheRecord:
    """The memo that terminates a cycle also means a shared dict, list or set is wrapped once,
    so aliasing inside the record survives into the view -- and into `copy()`, as `deepcopy`
    does. Wrapping a shared container twice would hand a UDF two views of one object that
    compare equal and are not the same.

    A tuple is the exception, pinned below so the limit is recorded rather than rediscovered:
    `__getitem__` re-runs the wrapping and a tuple is rebuilt rather than returned as stored,
    so two keys holding one tuple give two tuple objects -- as does the same key read twice.

    Every view-side test here also asserts the result refuses a write, and every copy-side
    test that the record is unchanged. Identity alone is satisfied by a view that wraps nothing
    at all, which is the vulnerability the module exists to close.
    """

    def test_two_keys_holding_the_same_dict_wrap_to_the_same_read_only_view(self):
        shared = {"n": 1}

        view = readonly_view({"p": shared, "q": shared})

        assert view["p"] is view["q"]
        with pytest.raises(TypeError, match="read-only"):
            view["p"]["n"] = 99
        assert shared["n"] == 1

    def test_two_keys_holding_the_same_list_wrap_to_the_same_read_only_view(self):
        shared = [{"n": 1}]

        view = readonly_view({"p": shared, "q": shared})

        assert view["p"] is view["q"]
        with pytest.raises(TypeError, match="read-only"):
            view["p"].append(2)
        with pytest.raises(TypeError, match="read-only"):
            view["p"][0]["n"] = 99
        assert shared == [{"n": 1}]

    def test_two_keys_holding_the_same_set_wrap_to_the_same_read_only_view(self):
        shared = {1, 2}

        view = readonly_view({"p": shared, "q": shared})

        assert view["p"] is view["q"]
        with pytest.raises(TypeError, match="read-only"):
            view["p"].add(3)
        assert shared == {1, 2}

    def test_two_keys_holding_different_equal_dicts_still_wrap_separately(self):
        view = readonly_view({"p": {"n": 1}, "q": {"n": 1}})

        assert view["p"] == view["q"]
        assert view["p"] is not view["q"]
        with pytest.raises(TypeError, match="read-only"):
            view["p"]["n"] = 99
        with pytest.raises(TypeError, match="read-only"):
            view["q"]["n"] = 99
        assert view["p"] == {"n": 1}

    def test_a_write_through_a_shared_view_is_refused(self):
        shared = {"n": 1}
        view = readonly_view({"p": shared, "q": shared})

        with pytest.raises(TypeError, match="read-only"):
            view["q"]["n"] = 99
        assert shared["n"] == 1

    def test_a_copy_keeps_the_sharing_and_shares_nothing_with_the_record(self):
        shared = {"n": 1}

        writable = readonly_view({"p": shared, "q": shared}).copy()
        writable["p"]["n"] = 99

        assert writable["q"]["n"] == 99
        assert shared["n"] == 1

    def test_a_copy_keeps_two_keys_holding_the_same_list_shared(self):
        shared = [{"n": 1}]

        writable = readonly_view({"p": shared, "q": shared}).copy()
        writable["p"].append(2)

        assert writable["q"] == [{"n": 1}, 2]
        assert writable["p"] is writable["q"]
        assert shared == [{"n": 1}]

    def test_a_copy_keeps_two_keys_holding_the_same_set_shared(self):
        """`readonly.py` makes the shared-container claim for the copy side too, and the copy
        walk has its own set branch -- pinning only the view side left it free to diverge."""
        shared = {1, 2}

        writable = readonly_view({"p": shared, "q": shared}).copy()
        writable["p"].add(3)

        assert writable["q"] == {1, 2, 3}
        assert writable["p"] is writable["q"]
        assert shared == {1, 2}

    def test_a_copy_keeps_two_keys_holding_the_same_frozenset_shared(self):
        shared = frozenset({1, 2})
        view = readonly_view({"p": shared, "q": shared})

        with pytest.raises(TypeError, match="read-only"):
            view["p"] = frozenset()

        writable = view.copy()

        assert writable["p"] is writable["q"]
        assert type(writable["p"]) is frozenset
        assert writable["p"] == {1, 2}

    def test_a_copy_keeps_one_shared_frozenset_subclass_instance_one_object(self):
        """For an exact frozenset `frozenset(x)` returns x; for a subclass it builds a new
        object, so only the memo keeps the two keys pointing at one."""

        class Tags(frozenset):
            pass

        shared = Tags({1, 2})

        writable = readonly_view({"p": shared, "q": shared}).copy()

        assert writable["p"] is writable["q"]
        assert writable["p"] == {1, 2}

    def test_a_shared_tuple_is_rebuilt_per_access_so_its_view_identity_is_not_stable(self):
        """The limit of the memo on the view side. `__getitem__` re-runs `_readonly`, and the
        tuple branch builds a new tuple every time; what the tuple HOLDS is still the one
        shared wrapper, and what the storage holds is one tuple -- only the object handed out
        per access is fresh."""
        shared = ({"n": 1},)
        view = readonly_view({"p": shared, "q": shared})

        assert view["p"] is not view["q"]
        assert view["p"] is not view["p"]
        assert view["p"] == view["q"]

        assert view["p"][0] is view["q"][0]
        stored = dict(view)
        assert stored["p"] is stored["q"]

        with pytest.raises(TypeError, match="read-only"):
            view["p"][0]["n"] = 99
        assert shared[0]["n"] == 1

    def test_a_copy_keeps_two_keys_holding_the_same_tuple_shared(self):
        """Unlike the view, `copy()` is one walk with one memo and is never re-run, so the
        tuple's sharing does survive into it."""
        shared = ({"n": 1},)

        writable = readonly_view({"p": shared, "q": shared}).copy()
        writable["p"][0]["n"] = 99

        assert writable["p"] is writable["q"]
        assert writable["q"][0]["n"] == 99
        assert shared[0]["n"] == 1


class TestTheMemoHoldsWhereTheResultIsStillEmpty:
    """A container is registered in the memo before its items are walked, so on a cycle the
    entry found can be an empty dict or list. A memo hit read by truthiness misses it and
    recurses forever; every other cyclic test puts an item before the back-reference."""

    def test_a_view_of_an_empty_self_referential_dict(self):
        record: dict[str, Any] = {}
        record["self"] = record

        view = readonly_view(record)

        assert view["self"] is view
        with pytest.raises(TypeError, match="read-only"):
            view["self"]["x"] = 1
        assert record == {"self": record}

    def test_a_copy_of_an_empty_self_referential_dict(self):
        record: dict[str, Any] = {}
        record["self"] = record

        writable = readonly_view(record).copy()

        assert writable["self"] is writable
        assert writable is not record

    def test_a_copy_of_an_empty_self_referential_list(self):
        items: list[Any] = []
        items.append(items)

        writable = readonly_view({"xs": items})["xs"].copy()

        assert writable[0] is writable
        assert writable is not items


class TestACopyIsWalkedFromStorageAndKeepsItsTypes:
    def test_one_tuple_stored_twice_in_a_list_stays_one_object_in_the_copy(self):
        """Walking the list's wrapper instead of its storage rebuilds the tuple per item."""
        shared = ({"n": 1},)

        writable = readonly_view({"xs": [shared, shared]})["xs"].copy()

        assert writable[0] is writable[1]

    def test_a_tuple_in_the_copy_is_still_a_tuple(self):
        """`copy()` is the hatch `_MESSAGE` points authors to; a tuple turning into a list
        there changes equality and hashability under them."""
        writable = readonly_view({"pair": (1, 2), "t": ({"a": 1},)}).copy()

        assert type(writable["pair"]) is tuple
        assert writable["pair"] == (1, 2)
        assert type(writable["t"]) is tuple
        assert hash(writable["pair"]) == hash((1, 2))
