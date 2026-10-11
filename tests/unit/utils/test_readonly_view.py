"""The read-only view handed to a guard UDF: it must refuse every way in, and stay usable.

A shallow guard is no guard -- `data["a1"]["tier"] = x` reaches straight through one --
and a view that breaks well-behaved UDFs is not shippable either.
"""

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
