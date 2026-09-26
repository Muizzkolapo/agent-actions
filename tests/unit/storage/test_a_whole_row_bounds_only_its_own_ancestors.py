"""A row stored whole supersedes what came before it, not what ran beside it.

Reconstruction stops above an upstream row stored whole, because such a row
carries the content of everything above it. That holds for an ancestor and not
for a peer, which carries namespaces the boundary never held. The dependency
graph records every earlier level as upstream of every later action, so a fan-in
over parallel start nodes is the ordinary shape here.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _backend(tmp_path, execution_order, dependency_graph):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    b.save_metadata("execution_order", json.dumps(execution_order))
    b.save_metadata("dependency_graph", json.dumps(dependency_graph))
    return b


def _row(content):
    return [{"source_guid": "G0", "_state": "processed", "_schema_version": 1, "content": content}]


class TestAFanInOverParallelStartNodes:
    """Levels [[a1, b1], [c1]], which the graph records as c1 <- [a1, b1] and
    b1 <- []. b1 is stored whole because nothing upstream holds its identity."""

    @pytest.fixture
    def fan_in(self, tmp_path):
        b = _backend(tmp_path, ["a1", "b1", "c1"], {"a1": [], "b1": [], "c1": ["a1", "b1"]})
        b.write_target(
            "a1", "f.json", _row({"source": {"t": 1}, "a1": {"v": 1}}), is_first_action=True
        )
        b.write_target("b1", "f.json", _row({"source": {"t": 1}, "b1": {"v": 2}}))
        b.write_target(
            "c1",
            "f.json",
            _row({"source": {"t": 1}, "a1": {"v": 1}, "b1": {"v": 2}, "c1": {"v": 3}}),
        )
        return b

    def test_the_peer_that_is_not_the_boundary_still_reaches_the_fan_in(self, fan_in):
        assert sorted(fan_in.read_target("c1", "f.json")[0]["content"]) == [
            "a1",
            "b1",
            "c1",
            "source",
        ]

    def test_the_peers_own_namespaces_are_both_intact(self, fan_in):
        content = fan_in.read_target("c1", "f.json")[0]["content"]

        assert content["a1"] == {"v": 1}
        assert content["b1"] == {"v": 2}


class TestAnAncestorStoredWholeStillBounds:
    """The other half: where the boundary is an ancestor, it must still cut. Its
    row carries everything above it, and merging that content again would
    resurrect namespaces it was stored without."""

    @pytest.fixture
    def chain(self, tmp_path):
        b = _backend(tmp_path, ["a1", "a2", "a3"], {"a1": [], "a2": ["a1"], "a3": ["a1", "a2"]})
        b.write_target(
            "a1", "f.json", _row({"source": {"t": 1}, "a1": {"v": 1}}), is_first_action=True
        )
        # Stored whole and deliberately without a1: the boundary's promise.
        b.write_target(
            "a2",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "_delta_mode": "full",
                    "content": {"source": {"t": 1}, "a2": {"v": 2}},
                }
            ],
        )
        b.write_target("a3", "f.json", _row({"source": {"t": 1}, "a2": {"v": 2}, "a3": {"v": 3}}))
        return b

    def test_the_namespace_the_boundary_dropped_is_not_resurrected(self, chain):
        assert sorted(chain.read_target("a3", "f.json")[0]["content"]) == [
            "a2",
            "a3",
            "source",
        ]


class TestThreeParallelStartNodes:
    """Two roots stored whole, not one: whichever becomes the boundary, neither
    supersedes the other, so no peer may be cut."""

    @pytest.fixture
    def three_roots(self, tmp_path):
        b = _backend(
            tmp_path,
            ["a1", "b1", "b2", "c1"],
            {"a1": [], "b1": [], "b2": [], "c1": ["a1", "b1", "b2"]},
        )
        b.write_target(
            "a1", "f.json", _row({"source": {"t": 1}, "a1": {"v": 1}}), is_first_action=True
        )
        b.write_target("b1", "f.json", _row({"source": {"t": 1}, "b1": {"v": 2}}))
        b.write_target("b2", "f.json", _row({"source": {"t": 1}, "b2": {"v": 3}}))
        b.write_target(
            "c1",
            "f.json",
            _row(
                {
                    "source": {"t": 1},
                    "a1": {"v": 1},
                    "b1": {"v": 2},
                    "b2": {"v": 3},
                    "c1": {"v": 4},
                }
            ),
        )
        return b

    def test_both_whole_peers_and_the_first_action_all_reach_the_fan_in(self, three_roots):
        assert sorted(three_roots.read_target("c1", "f.json")[0]["content"]) == [
            "a1",
            "b1",
            "b2",
            "c1",
            "source",
        ]

    def test_which_peer_is_chosen_as_the_boundary_cannot_change_the_answer(self, three_roots):
        """Two upstream actions hold a whole row for one identity, and the pick
        between them follows storage row order."""
        content = three_roots.read_target("c1", "f.json")[0]["content"]

        assert (content["b1"], content["b2"]) == ({"v": 2}, {"v": 3})


class TestABoundaryThatIsAPeerWithAnAncestorAboveIt:
    """The shape a 1->N expansion fanning back in actually makes: one root, three
    expanding peers, a fan-in below them. The boundary is a peer of two actions
    and a descendant of a third, so neither cutting at its position nor refusing
    to cut at all is right — only cutting at what it supersedes.
    """

    @pytest.fixture
    def expansion_fan_in(self, tmp_path):
        b = _backend(
            tmp_path,
            ["s", "e1", "e2", "e3", "c"],
            {"s": [], "e1": ["s"], "e2": ["s"], "e3": ["s"], "c": ["s", "e1", "e2", "e3"]},
        )
        b.write_target(
            "s", "f.json", _row({"source": {"t": 1}, "s": {"v": 0}}), is_first_action=True
        )
        b.write_target("e1", "f.json", _row({"source": {"t": 1}, "s": {"v": 0}, "e1": {"v": 1}}))
        # The whole row: an expansion stores its minted rows this way, and this one
        # carries everything above e2 and nothing of e1 or e3.
        b.write_target(
            "e2",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "_delta_mode": "full",
                    "content": {"source": {"t": 1}, "s": {"v": 0}, "e2": {"v": 2}},
                }
            ],
        )
        b.write_target("e3", "f.json", _row({"source": {"t": 1}, "s": {"v": 0}, "e3": {"v": 3}}))
        b.write_target(
            "c",
            "f.json",
            _row(
                {
                    "source": {"t": 1},
                    "s": {"v": 0},
                    "e1": {"v": 1},
                    "e2": {"v": 2},
                    "e3": {"v": 3},
                    "c": {"v": 4},
                }
            ),
        )
        return b

    def test_the_peers_above_and_below_the_boundary_both_survive(self, expansion_fan_in):
        """Cutting at the boundary's position keeps e3 and drops e1."""
        assert sorted(expansion_fan_in.read_target("c", "f.json")[0]["content"]) == [
            "c",
            "e1",
            "e2",
            "e3",
            "s",
            "source",
        ]

    def test_the_root_the_boundary_supersedes_still_arrives_through_it(self, expansion_fan_in):
        """`s` is not merged — the boundary supersedes it — so the boundary's own
        row is what carries it, which is the premise the cut relies on."""
        content = expansion_fan_in.read_target("c", "f.json")[0]["content"]

        assert content["s"] == {"v": 0}
        assert content["source"] == {"t": 1}


class TestWhichWholeRowBecomesTheBoundary:
    """Two upstream actions hold a whole row for one identity. Storage offers them
    in no defined order, so the choice has to come from the graph — and it is the
    shallower one, which supersedes the least.

    `z_merge` sorts after both roots while sitting below them in the graph, so a
    choice made by the order storage happens to return rows in lands on the deeper
    action and cuts `r1` away. Naming it `m` would hide that: sorted last would
    then be `r2`, which is the action the graph rule picks anyway.
    """

    @pytest.fixture
    def two_boundaries(self, tmp_path):
        b = _backend(
            tmp_path,
            ["r1", "r2", "z_merge", "c"],
            {"r1": [], "r2": [], "z_merge": ["r1", "r2"], "c": ["r1", "r2", "z_merge"]},
        )
        b.write_target(
            "r1", "f.json", _row({"source": {"t": 1}, "r1": {"v": 1}}), is_first_action=True
        )
        # r2 has no upstream, so it is stored whole in its own right.
        b.write_target("r2", "f.json", _row({"source": {"t": 1}, "r2": {"v": 2}}))
        # A correlated merge stores its rows whole, and this one never read r1.
        b.write_target(
            "z_merge",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "_delta_mode": "full",
                    "content": {"source": {"t": 1}, "r2": {"v": 2}, "z_merge": {"v": 3}},
                }
            ],
        )
        b.write_target(
            "c",
            "f.json",
            _row(
                {
                    "source": {"t": 1},
                    "r1": {"v": 1},
                    "r2": {"v": 2},
                    "z_merge": {"v": 3},
                    "c": {"v": 4},
                }
            ),
        )
        return b

    def test_the_deeper_boundary_does_not_supersede_the_root_it_never_read(self, two_boundaries):
        """Bounding at `z_merge` would drop `r1`, which its row does not carry."""
        assert sorted(two_boundaries.read_target("c", "f.json")[0]["content"]) == [
            "c",
            "r1",
            "r2",
            "source",
            "z_merge",
        ]


class TestAGraphEntryThatNamesItself:
    """Nothing the coordinator writes looks like this, but the graph is metadata a
    store can hold, and superseding the boundary itself empties the merge."""

    @pytest.fixture
    def self_naming(self, tmp_path):
        b = _backend(
            tmp_path, ["a1", "b1", "c1"], {"a1": [], "b1": ["a1", "b1"], "c1": ["a1", "b1"]}
        )
        b.write_target(
            "a1", "f.json", _row({"source": {"t": 1}, "a1": {"v": 1}}), is_first_action=True
        )
        b.write_target(
            "b1",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "_delta_mode": "full",
                    "content": {"source": {"t": 1}, "a1": {"v": 1}, "b1": {"v": 2}},
                }
            ],
        )
        b.write_target(
            "c1",
            "f.json",
            _row({"source": {"t": 1}, "a1": {"v": 1}, "b1": {"v": 2}, "c1": {"v": 3}}),
        )
        return b

    def test_the_boundary_still_merges_itself(self, self_naming):
        assert sorted(self_naming.read_target("c1", "f.json")[0]["content"]) == [
            "a1",
            "b1",
            "c1",
            "source",
        ]
