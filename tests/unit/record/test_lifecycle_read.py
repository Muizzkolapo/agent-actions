"""Tests for fail-closed target record lifecycle validation."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.record.lifecycle_read import require_frozen_record_lifecycle
from agent_actions.record.state import STATE_SCHEMA_VERSION, RecordState


class TestRequireFrozenRecordLifecycle:
    def test_missing_state_raises(self):
        with pytest.raises(ConfigurationError, match="missing '_state'"):
            require_frozen_record_lifecycle(
                {"source_guid": "g1", "content": {}},
                action_name="my_action",
            )

    def test_missing_schema_version_raises(self):
        with pytest.raises(ConfigurationError, match="missing '_state_schema_version'"):
            require_frozen_record_lifecycle(
                {"_state": RecordState.PROCESSED.value, "source_guid": "g1"},
                action_name="my_action",
            )

    def test_unsupported_schema_version_raises(self):
        with pytest.raises(ConfigurationError, match="Unsupported _state_schema_version"):
            require_frozen_record_lifecycle(
                {
                    "_state": RecordState.PROCESSED.value,
                    "_state_schema_version": 999,
                    "source_guid": "g1",
                },
                action_name="my_action",
            )

    def test_unknown_state_raises(self):
        with pytest.raises(ConfigurationError, match="unknown _state value"):
            require_frozen_record_lifecycle(
                {
                    "_state": "not_a_real_state",
                    "_state_schema_version": STATE_SCHEMA_VERSION,
                },
                action_name="my_action",
            )

    def test_valid_record_passes(self):
        require_frozen_record_lifecycle(
            {
                "_state": RecordState.PROCESSED.value,
                "_state_schema_version": STATE_SCHEMA_VERSION,
                "source_guid": "g1",
            },
            action_name="my_action",
        )
