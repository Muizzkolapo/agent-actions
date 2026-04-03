"""Tests for extract_runtime_warnings scanner function."""

import json

import pytest

from agent_actions.tooling.docs.scanner.data_scanners import extract_runtime_warnings


@pytest.fixture
def events_file(tmp_path):
    """Create a temporary events.json file."""
    path = tmp_path / "events.json"

    def _write(events):
        path.write_text("\n".join(json.dumps(e) for e in events))
        return path

    return _write


class TestExtractRuntimeWarnings:
    def test_extracts_warn_events(self, events_file):
        path = events_file(
            [
                {
                    "event_type": "LogEvent",
                    "level": "warn",
                    "category": "processing",
                    "message": "All records filtered by guard",
                    "meta": {
                        "timestamp": "2026-04-03T09:44:13Z",
                        "action_name": "generate_summary",
                        "workflow_name": "incident_triage",
                    },
                    "data": {},
                },
            ]
        )
        result = extract_runtime_warnings(path)
        assert len(result["runtime_warnings"]) == 1
        assert result["runtime_warnings"][0]["target"] == "generate_summary"
        assert "filtered by guard" in result["runtime_warnings"][0]["message"]
        assert len(result["runtime_errors"]) == 0

    def test_extracts_error_events(self, events_file):
        path = events_file(
            [
                {
                    "event_type": "ActionFailedEvent",
                    "level": "error",
                    "category": "action",
                    "message": "Action failed: 401 Unauthorized",
                    "meta": {
                        "timestamp": "2026-04-03T10:00:00Z",
                        "action_name": "extract_claims",
                        "workflow_name": "review_analyzer",
                    },
                    "data": {},
                },
            ]
        )
        result = extract_runtime_warnings(path)
        assert len(result["runtime_errors"]) == 1
        assert result["runtime_errors"][0]["target"] == "extract_claims"
        assert len(result["runtime_warnings"]) == 0

    def test_skips_info_and_debug(self, events_file):
        path = events_file(
            [
                {"event_type": "X", "level": "info", "message": "ok", "meta": {}, "data": {}},
                {"event_type": "X", "level": "debug", "message": "trace", "meta": {}, "data": {}},
            ]
        )
        result = extract_runtime_warnings(path)
        assert len(result["runtime_warnings"]) == 0
        assert len(result["runtime_errors"]) == 0

    def test_skips_validation_events(self, events_file):
        """Validation events are already captured by scan_logs — don't duplicate."""
        path = events_file(
            [
                {
                    "event_type": "ValidationErrorEvent",
                    "level": "error",
                    "message": "Missing field",
                    "meta": {"action_name": "act"},
                    "data": {},
                },
                {
                    "event_type": "ValidationWarningEvent",
                    "level": "warn",
                    "message": "Unused dep",
                    "meta": {"action_name": "act"},
                    "data": {},
                },
            ]
        )
        result = extract_runtime_warnings(path)
        assert len(result["runtime_warnings"]) == 0
        assert len(result["runtime_errors"]) == 0

    def test_target_fallback_to_workflow_name(self, events_file):
        path = events_file(
            [
                {
                    "event_type": "WorkflowFailedEvent",
                    "level": "error",
                    "message": "Workflow failed",
                    "meta": {"workflow_name": "my_workflow"},
                    "data": {},
                },
            ]
        )
        result = extract_runtime_warnings(path)
        assert result["runtime_errors"][0]["target"] == "my_workflow"

    def test_target_fallback_to_category(self, events_file):
        path = events_file(
            [
                {
                    "event_type": "SomeEvent",
                    "level": "warn",
                    "category": "cache",
                    "message": "Cache miss",
                    "meta": {},
                    "data": {},
                },
            ]
        )
        result = extract_runtime_warnings(path)
        assert result["runtime_warnings"][0]["target"] == "cache"

    def test_empty_file(self, events_file):
        path = events_file([])
        result = extract_runtime_warnings(path)
        assert result == {"runtime_warnings": [], "runtime_errors": []}

    def test_nonexistent_file(self, tmp_path):
        result = extract_runtime_warnings(tmp_path / "missing.json")
        assert result == {"runtime_warnings": [], "runtime_errors": []}

    def test_mixed_events(self, events_file):
        path = events_file(
            [
                {"event_type": "X", "level": "info", "message": "ok", "meta": {}, "data": {}},
                {
                    "event_type": "X",
                    "level": "warn",
                    "message": "w1",
                    "meta": {"action_name": "a"},
                    "data": {},
                },
                {
                    "event_type": "X",
                    "level": "error",
                    "message": "e1",
                    "meta": {"action_name": "b"},
                    "data": {},
                },
                {
                    "event_type": "X",
                    "level": "warn",
                    "message": "w2",
                    "meta": {"action_name": "c"},
                    "data": {},
                },
                {"event_type": "X", "level": "debug", "message": "d", "meta": {}, "data": {}},
            ]
        )
        result = extract_runtime_warnings(path)
        assert len(result["runtime_warnings"]) == 2
        assert len(result["runtime_errors"]) == 1
