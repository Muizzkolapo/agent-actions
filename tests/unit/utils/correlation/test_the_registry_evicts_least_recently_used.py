"""The version correlation registry evicts its least recently used entry at the cap."""

from agent_actions.utils.correlation import VersionIdGenerator


class TestVersionIdGeneratorLRUEviction:
    """LRU eviction must cap the registry at _MAX_REGISTRY_SIZE."""

    def setup_method(self):
        VersionIdGenerator.clear_version_correlation_registry()

    def teardown_method(self):
        VersionIdGenerator.clear_version_correlation_registry()

    def test_eviction_at_max_size(self):
        # Use a smaller cap for test speed
        original_max = VersionIdGenerator._MAX_REGISTRY_SIZE
        VersionIdGenerator._MAX_REGISTRY_SIZE = 100
        try:
            # Insert 101 entries
            for i in range(101):
                VersionIdGenerator.get_or_create_version_correlation_id(
                    source_guid=f"guid_{i}",
                    version_base_name="v1",
                    workflow_session_id="session_1",
                )

            assert len(VersionIdGenerator._version_correlation_registry) == 100

            # The first entry (guid_0) should have been evicted
            first_key = "session_1:v1:guid_0"
            assert first_key not in VersionIdGenerator._version_correlation_registry

            # The last entry (guid_100) should still be present
            last_key = "session_1:v1:guid_100"
            assert last_key in VersionIdGenerator._version_correlation_registry
        finally:
            VersionIdGenerator._MAX_REGISTRY_SIZE = original_max

    def test_lru_access_prevents_eviction(self):
        original_max = VersionIdGenerator._MAX_REGISTRY_SIZE
        VersionIdGenerator._MAX_REGISTRY_SIZE = 5
        try:
            # Insert 5 entries
            for i in range(5):
                VersionIdGenerator.get_or_create_version_correlation_id(
                    source_guid=f"guid_{i}",
                    version_base_name="v1",
                    workflow_session_id="sess",
                )

            # Access guid_0 to move it to end (most recently used)
            VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_0",
                version_base_name="v1",
                workflow_session_id="sess",
            )

            # Insert one more — guid_1 should be evicted (oldest), not guid_0
            VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_5",
                version_base_name="v1",
                workflow_session_id="sess",
            )

            assert "sess:v1:guid_0" in VersionIdGenerator._version_correlation_registry
            assert "sess:v1:guid_1" not in VersionIdGenerator._version_correlation_registry
        finally:
            VersionIdGenerator._MAX_REGISTRY_SIZE = original_max

    def test_deterministic_regeneration_after_eviction(self):
        """Evicted entry regenerates the same correlation ID."""
        original_max = VersionIdGenerator._MAX_REGISTRY_SIZE
        VersionIdGenerator._MAX_REGISTRY_SIZE = 2
        try:
            id_first = VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_a", version_base_name="v1", workflow_session_id="sess"
            )
            # Fill to evict guid_a
            VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_b", version_base_name="v1", workflow_session_id="sess"
            )
            VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_c", version_base_name="v1", workflow_session_id="sess"
            )

            # guid_a evicted; regenerate
            id_second = VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid="guid_a", version_base_name="v1", workflow_session_id="sess"
            )
            assert id_first == id_second
        finally:
            VersionIdGenerator._MAX_REGISTRY_SIZE = original_max
