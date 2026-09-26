"""A row is only storable as a delta if its identity joins something upstream.

Two ways a row reaches the delta branch with nothing to join: its identity was
minted, so no upstream action holds it; or the action has no upstream at all yet
is not ``execution_order[0]``, so the ``first`` mode that keeps ``source`` does
not apply to it either. A second independent root is the latter, and needs no
minting to get there. Either way the stored row keeps its own namespace alone.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

UPSTREAM = {"source": {"t": "v1"}, "a1": {"v": 1}}


def _backend(tmp_path, execution_order, dependency_graph):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    b.save_metadata("execution_order", json.dumps(execution_order))
    b.save_metadata("dependency_graph", json.dumps(dependency_graph))
    return b


@pytest.fixture
def chain(tmp_path):
    """a1 -> a2, with a1 holding G0."""
    b = _backend(tmp_path, ["a1", "a2"], {"a1": [], "a2": ["a1"]})
    b.write_target(
        "a1",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": dict(UPSTREAM),
            }
        ],
    )
    return b


def _row(source_guid, action, **extra):
    return {
        "source_guid": source_guid,
        "_state": "processed",
        "_schema_version": 1,
        "content": {**UPSTREAM, action: {"x": 1}},
        **extra,
    }


def _modes(backend, action):
    return [r.get("_delta_mode") for r in backend._read_target_raw(action, "f.json")]


def _namespaces(backend, action):
    return [sorted(r.get("content", {})) for r in backend.read_target(action, "f.json")]


class TestAnIdentityNoUpstreamActionHolds:
    def test_it_is_stored_whole(self, chain):
        chain.write_target("a2", "f.json", [_row("MINTED", "a2")])

        assert _modes(chain, "a2") == ["full"]

    def test_its_upstream_namespaces_survive_the_round_trip(self, chain):
        chain.write_target("a2", "f.json", [_row("MINTED", "a2")])

        assert _namespaces(chain, "a2") == [["a1", "a2", "source"]]

    def test_a_row_already_stamped_whole_is_left_alone(self, chain):
        """The stamp short-circuits before the check, so minting sites that do
        remember are unaffected by it."""
        chain.write_target("a2", "f.json", [_row("MINTED", "a2", _delta_mode="full")])

        assert _modes(chain, "a2") == ["full"]
        assert _namespaces(chain, "a2") == [["a1", "a2", "source"]]

    def test_it_is_decided_per_row_not_per_batch(self, chain):
        """A minted row written beside a joinable one must not drag it to full,
        or the joinable row stops following its upstream."""
        chain.write_target("a2", "f.json", [_row("G0", "a2"), _row("MINTED", "a2")])

        assert _modes(chain, "a2") == ["delta", "full"]


class TestAnActionWithNoUpstreamThatIsNotTheFirst:
    """A second independent root: nothing upstream to join, and `first` mode —
    which would have kept `source` — belongs to execution_order[0] alone."""

    @pytest.fixture
    def two_roots(self, tmp_path):
        b = _backend(tmp_path, ["a1", "b1"], {"a1": [], "b1": []})
        # The peer holds G0 too, so only "does b1's own upstream hold it" answers
        # no — "does any action hold it" does not.
        b.write_target(
            "a1",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {"source": {"t": "v1"}, "a1": {"v": 1}},
                }
            ],
            is_first_action=True,
        )
        return b

    def test_its_row_is_stored_whole(self, two_roots):
        two_roots.write_target(
            "b1",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {"source": {"t": "v1"}, "b1": {"v": 1}},
                }
            ],
        )

        assert _modes(two_roots, "b1") == ["full"]

    def test_its_source_namespace_survives(self, two_roots):
        two_roots.write_target(
            "b1",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {"source": {"t": "v1"}, "b1": {"v": 1}},
                }
            ],
        )

        assert _namespaces(two_roots, "b1") == [["b1", "source"]]


class TestAnIdentityItsUpstreamDoesHold:
    """The other half: storing every row whole would cost the delta scheme its
    point and freeze each row's upstream content at the moment it was written."""

    def test_it_is_still_stored_as_a_delta(self, chain):
        chain.write_target("a2", "f.json", [_row("G0", "a2")])

        assert _modes(chain, "a2") == ["delta"]

    def test_it_still_follows_its_upstream_after_that_upstream_changes(self, chain):
        chain.write_target("a2", "f.json", [_row("G0", "a2")])
        chain.write_target(
            "a1",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {"source": {"t": "v2"}, "a1": {"v": 2}},
                }
            ],
        )

        read_back = chain.read_target("a2", "f.json")[0]

        assert read_back["content"]["source"] == {"t": "v2"}
        assert read_back["content"]["a1"] == {"v": 2}

    def test_the_first_action_keeps_its_own_mode(self, chain):
        """`first` already keeps `source`, so the check must not displace it."""
        assert _modes(chain, "a1") == ["first"]


class TestTheRuleIsNotKeyedToOneActionName:
    """Named actions differ from the fixture's throughout: a check that keyed off
    `a2`, or off being second in the order, would pass the tests above."""

    @pytest.fixture
    def deeper(self, tmp_path):
        b = _backend(
            tmp_path,
            ["stage_one", "stage_two", "stage_three"],
            # Every earlier level is upstream of every later action, which is what
            # the coordinator records. A direct-parent graph would leave this
            # chain's delta rows unable to rejoin `source` at all.
            {
                "stage_one": [],
                "stage_two": ["stage_one"],
                "stage_three": ["stage_one", "stage_two"],
            },
        )
        b.write_target(
            "stage_one",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {"source": {"t": "v1"}, "stage_one": {"v": 1}},
                }
            ],
        )
        b.write_target(
            "stage_two",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {
                        "source": {"t": "v1"},
                        "stage_one": {"v": 1},
                        "stage_two": {"v": 2},
                    },
                }
            ],
        )
        return b

    def test_a_minted_row_three_actions_deep_is_stored_whole(self, deeper):
        deeper.write_target(
            "stage_three",
            "f.json",
            [
                {
                    "source_guid": "MINTED",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {
                        "source": {"t": "v1"},
                        "stage_one": {"v": 1},
                        "stage_two": {"v": 2},
                        "stage_three": {"v": 3},
                    },
                }
            ],
        )

        assert _modes(deeper, "stage_three") == ["full"]
        assert _namespaces(deeper, "stage_three") == [
            ["source", "stage_one", "stage_three", "stage_two"]
        ]

    def test_a_joinable_row_three_actions_deep_is_still_a_delta(self, deeper):
        deeper.write_target(
            "stage_three",
            "f.json",
            [
                {
                    "source_guid": "G0",
                    "_state": "processed",
                    "_schema_version": 1,
                    "content": {
                        "source": {"t": "v1"},
                        "stage_one": {"v": 1},
                        "stage_two": {"v": 2},
                        "stage_three": {"v": 3},
                    },
                }
            ],
        )

        assert _modes(deeper, "stage_three") == ["delta"]
        assert _namespaces(deeper, "stage_three") == [
            ["source", "stage_one", "stage_three", "stage_two"]
        ]


class TestAnUpstreamRowHoldingTheIdentityButNoContent:
    """Presence of the identity upstream is not the question — whether anything
    would be rejoined under it is. A row stored without this action's namespace is
    stored whole with no content, so it answers the first and not the second."""

    @pytest.fixture
    def empty_upstream(self, tmp_path):
        b = _backend(tmp_path, ["a1", "a2"], {"a1": [], "a2": ["a1"]})
        b.write_target(
            "a1",
            "f.json",
            [{"source_guid": "G0", "_state": "processed", "_schema_version": 1, "content": {}}],
            is_first_action=True,
        )
        return b

    def test_the_row_below_it_is_stored_whole(self, empty_upstream):
        empty_upstream.write_target("a2", "f.json", [_row("G0", "a2")])

        assert _modes(empty_upstream, "a2") == ["full"]

    def test_its_namespaces_survive_the_round_trip(self, empty_upstream):
        """Stored as a delta it would rejoin an empty namespace and come back
        holding a2 alone."""
        empty_upstream.write_target("a2", "f.json", [_row("G0", "a2")])

        assert _namespaces(empty_upstream, "a2") == [["a1", "a2", "source"]]
