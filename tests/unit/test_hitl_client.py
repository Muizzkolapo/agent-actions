"""Tests for HITL client."""

from unittest.mock import Mock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.hitl.client import HitlClient


def test_hitl_client_invoke_missing_config():
    """Test that missing hitl config raises ConfigurationError."""
    agent_config = {"name": "test_action"}
    context_data = {"test": "data"}

    with pytest.raises(ConfigurationError, match="HITL action requires 'hitl' configuration"):
        HitlClient.invoke(agent_config, context_data)


def test_hitl_client_invoke_with_config():
    """Test HitlClient.invoke with valid config."""
    agent_config = {
        "name": "test_action",
        "hitl": {
            "port": 3001,
            "instructions": "Review the data",
            "timeout": 300,
        },
    }
    context_data = {"test": "data", "value": 42}

    # Mock the HitlServer
    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "Looks good",
            "timestamp": "2026-02-12T10:00:00",
        }
        mock_server_class.return_value = mock_server

        result = HitlClient.invoke(agent_config, context_data)

        # Verify server was created with correct params
        mock_server_class.assert_called_once_with(
            port=3001,
            instructions="Review the data",
            context_data={"test": "data", "value": 42},
            timeout=300,
            require_comment_on_reject=True,
            field_order=[],
            state_file=None,
        )

        # Verify start_and_wait was called
        mock_server.start_and_wait.assert_called_once()

        # Verify response
        assert result["hitl_status"] == "approved"
        assert result["user_comment"] == "Looks good"
        assert "timestamp" in result


def test_hitl_client_invoke_with_string_context():
    """Test HitlClient.invoke with string context data."""
    agent_config = {
        "name": "test_action",
        "hitl": {
            "port": 3002,
            "instructions": "Check this",
            "timeout": 100,
        },
    }
    context_data = '{"key": "value", "number": 123}'

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "rejected",
            "user_comment": "Needs work",
            "timestamp": "2026-02-12T10:00:00",
        }
        mock_server_class.return_value = mock_server

        result = HitlClient.invoke(agent_config, context_data)

        # Verify context was parsed from JSON
        call_args = mock_server_class.call_args
        assert call_args[1]["context_data"] == {"key": "value", "number": 123}

        assert result["hitl_status"] == "rejected"


def test_hitl_client_invoke_with_invalid_json_string():
    """Test HitlClient.invoke with invalid JSON string context."""
    agent_config = {
        "name": "test_action",
        "hitl": {"port": 3001, "instructions": "Review"},
    }
    context_data = "not valid json {{"

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "timeout",
            "user_comment": None,
            "timestamp": "2026-02-12T10:00:00",
        }
        mock_server_class.return_value = mock_server

        result = HitlClient.invoke(agent_config, context_data)

        # Verify invalid JSON wrapped in {"raw": ...}
        call_args = mock_server_class.call_args
        assert call_args[1]["context_data"] == {"raw": "not valid json {{"}

        assert result["hitl_status"] == "timeout"


def test_hitl_client_invoke_uses_default_timeout():
    """Test HitlClient.invoke uses default timeout when not specified."""
    agent_config = {
        "name": "test_action",
        "hitl": {
            "port": 3001,
            "instructions": "Review",
            # timeout not specified
        },
    }
    context_data = {}

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "",
            "timestamp": "2026-02-12T10:00:00",
        }
        mock_server_class.return_value = mock_server

        HitlClient.invoke(agent_config, context_data)

        # Verify default timeout (300) was used
        call_args = mock_server_class.call_args
        assert call_args[1]["timeout"] == 300


def test_hitl_client_invoke_honors_require_comment_on_reject_flag():
    """Test HitlClient.invoke forwards require_comment_on_reject setting."""
    agent_config = {
        "name": "test_action",
        "hitl": {
            "port": 3001,
            "instructions": "Review",
            "require_comment_on_reject": False,
        },
    }
    context_data = {"test": "data"}

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "",
            "timestamp": "2026-02-12T10:00:00Z",
        }
        mock_server_class.return_value = mock_server

        HitlClient.invoke(agent_config, context_data)

        call_args = mock_server_class.call_args
        assert call_args[1]["require_comment_on_reject"] is False


def test_hitl_client_passes_field_order_from_observe():
    """Test HitlClient.invoke extracts field_order from context_scope.observe."""
    agent_config = {
        "name": "test_action",
        "hitl": {"port": 3001, "instructions": "Review"},
        "context_scope": {
            "observe": [
                "upstream.question_text",
                "upstream.answer",
                "source.url",
            ]
        },
    }
    context_data = {"question_text": "Q1", "answer": "A1", "url": "https://example.com"}

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "",
            "timestamp": "2026-02-12T10:00:00Z",
        }
        mock_server_class.return_value = mock_server

        HitlClient.invoke(agent_config, context_data)

        call_args = mock_server_class.call_args
        assert call_args[1]["field_order"] == [
            "upstream.question_text",
            "upstream.answer",
            "source.url",
        ]


def test_hitl_client_filters_wildcard_from_field_order():
    """Wildcard observe refs like 'action.*' should not leak into field_order."""
    agent_config = {
        "name": "test_action",
        "hitl": {"port": 3001, "instructions": "Review"},
        "context_scope": {
            "observe": ["upstream.*"],
        },
    }
    context_data = {"a": 1}

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "",
            "timestamp": "2026-02-12T10:00:00Z",
        }
        mock_server_class.return_value = mock_server

        HitlClient.invoke(agent_config, context_data)

        call_args = mock_server_class.call_args
        assert call_args[1]["field_order"] == []


def test_hitl_client_preserves_distinct_refs_with_same_field_name():
    """Refs from different deps with the same field name stay distinct in field_order."""
    agent_config = {
        "name": "test_action",
        "hitl": {"port": 3001, "instructions": "Review"},
        "context_scope": {
            "observe": ["dep_a.title", "dep_b.title", "dep_a.body"],
        },
    }
    context_data = {"title": "T", "body": "B"}

    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as mock_server_class:
        mock_server = Mock()
        mock_server.start_and_wait.return_value = {
            "hitl_status": "approved",
            "user_comment": "",
            "timestamp": "2026-02-12T10:00:00Z",
        }
        mock_server_class.return_value = mock_server

        HitlClient.invoke(agent_config, context_data)

        call_args = mock_server_class.call_args
        assert call_args[1]["field_order"] == ["dep_a.title", "dep_b.title", "dep_a.body"]
