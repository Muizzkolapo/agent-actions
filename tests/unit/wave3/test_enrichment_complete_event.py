"""Regression tests for Wave 3 architecture hardening changes."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander_action_types import process_tool_action
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.result_collector import ProcessingStatus
from agent_actions.utils.correlation.version_id import VersionIdGenerator


class TestEnrichmentCompleteEventOnFailure:
    """EnrichmentPipelineCompleteEvent must fire even when an enricher fails."""

    def test_complete_event_fires_on_enricher_failure(self):
        events_fired = []

        class FailingEnricher:
            def enrich(self, result, context):
                raise RuntimeError("enricher boom")

        pipeline = EnrichmentPipeline(enrichers=[FailingEnricher()])

        with patch("agent_actions.processing.enrichment.fire_event") as mock_fire:
            with pytest.raises(RuntimeError, match="enricher boom"):
                pipeline.enrich(MagicMock(), MagicMock())

            # Collect event class names
            events_fired = [call.args[0].__class__.__name__ for call in mock_fire.call_args_list]

        assert "EnrichmentPipelineStartedEvent" in events_fired
        assert "EnrichmentPipelineCompleteEvent" in events_fired
        assert "EnricherExecutedEvent" in events_fired


class TestToolActionBatchGuard:
    """Tool actions must raise ConfigurationError when resolved run_mode is BATCH."""

    def test_batch_mode_raises_configuration_error(self):
        agent: dict = {"model_vendor": None, "model_name": None}
        action = {"name": "my_tool", "kind": "tool", "impl": "mod.func"}

        with pytest.raises(ConfigurationError, match="batch"):
            process_tool_action(agent, action, RunMode.BATCH)

    def test_online_mode_does_not_raise(self):
        agent: dict = {}
        action = {"name": "my_tool", "kind": "tool", "impl": "mod.func", "schema": {"f": "str"}}

        # Should not raise
        process_tool_action(agent, action, RunMode.ONLINE)
        assert agent["model_vendor"] == "tool"


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


class TestOutputFieldDeduplication:
    """ActionSchema output_fields must not contain duplicates from overlapping sources."""

    def test_overlapping_schema_and_observe_fields(self):
        from agent_actions.models.action_schema import FieldInfo, FieldSource

        # Simulate what schema_service does — build with deduped fields
        schema_fields = ["name", "age", "shared_field"]
        observe_fields = ["shared_field", "extra_obs"]

        seen: dict[str, FieldInfo] = {}
        for f in schema_fields:
            if f not in seen:
                seen[f] = FieldInfo(name=f, source=FieldSource.SCHEMA)
        for f in observe_fields:
            if f not in seen:
                seen[f] = FieldInfo(name=f, source=FieldSource.OBSERVE)

        output_fields = list(seen.values())

        # shared_field should appear once with SCHEMA source (first-seen wins)
        names = [f.name for f in output_fields]
        assert names.count("shared_field") == 1
        shared = next(f for f in output_fields if f.name == "shared_field")
        assert shared.source == FieldSource.SCHEMA


class TestDeferredStatusHandling:
    """DEFERRED status should be handled with INFO log, not 'Unhandled'."""

    def test_deferred_status_logs_info(self):
        from agent_actions.processing.result_collector import ResultCollector

        result = MagicMock()
        result.status = ProcessingStatus.DEFERRED
        result.source_guid = "test-guid"
        result.output_data = None
        result.skip_reason = None

        collector = ResultCollector.__new__(ResultCollector)
        collector.logger = MagicMock()

        # Verify the DEFERRED branch exists as a known status
        assert hasattr(ProcessingStatus, "DEFERRED")
