"""Clearing the correlation registry must leave behind one the read path can use.

Both getters touch an ordered structure on a cache hit (``move_to_end``) and the
eviction helper pops from the front (``popitem(last=False)``). A clear that mutates
whatever object it finds cannot restore that contract once something else has
replaced the attribute.
"""

from collections import OrderedDict

from agent_actions.utils.correlation import VersionIdGenerator


def _replace_the_registry_with_a_plain_dict() -> None:
    """Install the wrong type on purpose: a caller can, and one in this suite does."""
    VersionIdGenerator._version_correlation_registry = {"stale": "value"}  # type: ignore[assignment]


class TestAClearedRegistryStillServesACacheHit:
    def setup_method(self):
        _replace_the_registry_with_a_plain_dict()
        VersionIdGenerator.clear_version_correlation_registry()

    def teardown_method(self):
        VersionIdGenerator._version_correlation_registry = OrderedDict()

    def test_a_repeated_source_guid_keeps_one_id(self):
        first = VersionIdGenerator.get_or_create_version_correlation_id("g1", "v1", "sess")
        second = VersionIdGenerator.get_or_create_version_correlation_id("g1", "v1", "sess")

        assert second == first

    def test_a_repeated_position_keeps_one_id(self):
        first = VersionIdGenerator.get_or_create_position_based_version_correlation_id(
            0, "v1", "sess", file_context="f"
        )
        second = VersionIdGenerator.get_or_create_position_based_version_correlation_id(
            0, "v1", "sess", file_context="f"
        )

        assert second == first


class TestAClearedRegistryStillEvictsOldestFirst:
    def setup_method(self):
        _replace_the_registry_with_a_plain_dict()
        VersionIdGenerator.clear_version_correlation_registry()
        self._original_max = VersionIdGenerator._MAX_REGISTRY_SIZE
        VersionIdGenerator._MAX_REGISTRY_SIZE = 3

    def teardown_method(self):
        VersionIdGenerator._MAX_REGISTRY_SIZE = self._original_max
        VersionIdGenerator._version_correlation_registry = OrderedDict()

    def test_the_oldest_entry_goes_when_the_cap_is_passed(self):
        for i in range(4):
            VersionIdGenerator.get_or_create_version_correlation_id(f"g{i}", "v1", "sess")

        registry = VersionIdGenerator._version_correlation_registry
        assert "sess:v1:g0" not in registry
        assert "sess:v1:g3" in registry
        assert len(registry) == 3


class TestTheRegistryIsEmptyAfterAClear:
    """The reason the production caller clears at all: no ids carry across runs."""

    def teardown_method(self):
        VersionIdGenerator._version_correlation_registry = OrderedDict()

    def test_an_id_minted_before_a_clear_is_not_returned_after_it(self):
        VersionIdGenerator._version_correlation_registry = OrderedDict()
        before = VersionIdGenerator.get_or_create_version_correlation_id("g1", "v1", "sess_a")

        VersionIdGenerator.clear_version_correlation_registry()

        assert VersionIdGenerator._version_correlation_registry == {}
        after = VersionIdGenerator.get_or_create_version_correlation_id("g1", "v1", "sess_b")
        assert after != before
