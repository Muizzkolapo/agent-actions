"""Tests for lifecycle_read validation helper."""

import pytest

from agent_actions.errors.configuration import ConfigurationError
from agent_actions.record.lifecycle_read import validate_lifecycle, validate_lifecycle_batch
from agent_actions.record.state import RecordState


def _record(state: str = "active", **kwargs) -> dict:
    return {"_state": state, "_state_schema_version": 1, "source_guid": "sg-1", **kwargs}


class TestValidateLifecycle:
    def test_valid_record_passes(self):
        validate_lifecycle(_record(), action_name="my_action")

    def test_all_valid_states_pass(self):
        for state in RecordState:
            validate_lifecycle(_record(state.value), action_name="act")

    def test_missing_state_raises(self):
        record = {"source_guid": "sg-1", "content": {}}
        with pytest.raises(ConfigurationError, match="_state") as exc:
            validate_lifecycle(record, action_name="my_action")
        assert "my_action" in str(exc.value)
        assert "sg-1" in str(exc.value)
        assert "re-run" in str(exc.value)

    def test_unknown_state_value_raises(self):
        record = {"_state": "bogus", "source_guid": "sg-2"}
        with pytest.raises(ConfigurationError, match="unrecognised.*bogus"):
            validate_lifecycle(record, action_name="act")

    def test_unsupported_schema_version_raises(self):
        record = {"_state": "active", "_state_schema_version": 99, "source_guid": "sg-3"}
        with pytest.raises(ConfigurationError, match="unsupported.*99"):
            validate_lifecycle(record, action_name="act")

    def test_missing_schema_version_passes(self):
        record = {"_state": "active", "source_guid": "sg-4"}
        validate_lifecycle(record, action_name="act")

    def test_missing_source_guid_shows_question_mark(self):
        record = {"_state": "bogus"}
        with pytest.raises(ConfigurationError, match="source_guid='\\?'"):
            validate_lifecycle(record, action_name="act")

    def test_action_name_in_error_message(self):
        record = {"content": {}}
        with pytest.raises(ConfigurationError, match="action='specific_action'"):
            validate_lifecycle(record, action_name="specific_action")


class TestValidateLifecycleBatch:
    def test_all_valid_passes(self):
        records = [_record("active"), _record("processed"), _record("guard_skipped")]
        validate_lifecycle_batch(records, action_name="act")

    def test_empty_list_passes(self):
        validate_lifecycle_batch([], action_name="act")

    def test_first_invalid_raises(self):
        records = [_record(), {"source_guid": "bad"}, _record()]
        with pytest.raises(ConfigurationError, match="_state"):
            validate_lifecycle_batch(records, action_name="act")

    def test_last_invalid_raises(self):
        records = [_record(), _record(), {"source_guid": "bad-last"}]
        with pytest.raises(ConfigurationError, match="_state"):
            validate_lifecycle_batch(records, action_name="act")
