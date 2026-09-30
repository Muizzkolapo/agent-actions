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
