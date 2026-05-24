"""Tests for schema-echo detection in online and batch paths.

When an LLM returns the JSON Schema definition itself instead of conforming
data, the schema-echo guard must detect and replace the response with a
``_parse_error`` dict.
"""

from agent_actions.processing.helpers import (
    _is_schema_echo,
    _reject_schema_echo_items,
)

# ---------------------------------------------------------------------------
# Fixture: exact schema-echo payloads from production bug evidence
# ---------------------------------------------------------------------------

FULL_ECHO = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"distractor_explanation_1": {"type": "string"}},
    "required": [],
    "additionalProperties": False,
}

PARTIAL_ECHO = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"optimal_code": {"type": "string"}},
    "required": ["optimal_code"],
    "additionalProperties": False,
}

VALID_OUTPUT = {
    "distractor_explanation_1": "The earth is not flat because...",
    "score": 0.95,
}

PARSE_ERROR = {
    "raw_response": "invalid json",
    "_parse_error": "Failed to parse JSON from LLM response",
}


# ---------------------------------------------------------------------------
# _is_schema_echo
# ---------------------------------------------------------------------------


class TestIsSchemaEcho:
    """Unit tests for the low-level schema-echo detector."""

    def test_full_echo_detected(self):
        assert _is_schema_echo(FULL_ECHO) is True

    def test_partial_echo_detected(self):
        assert _is_schema_echo(PARTIAL_ECHO) is True

    def test_valid_output_not_detected(self):
        assert _is_schema_echo(VALID_OUTPUT) is False

    def test_parse_error_not_detected(self):
        assert _is_schema_echo(PARSE_ERROR) is False

    def test_empty_dict_not_detected(self):
        assert _is_schema_echo({}) is False

    def test_no_title_not_detected(self):
        """Missing 'title' key — not a schema echo."""
        data = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert _is_schema_echo(data) is False

    def test_type_not_object_not_detected(self):
        """type != 'object' — not a schema echo."""
        data = {"title": "X", "type": "array", "properties": {"x": {"type": "string"}}}
        assert _is_schema_echo(data) is False

    def test_properties_not_dict_not_detected(self):
        """properties is a list, not dict — not a schema echo."""
        data = {"title": "X", "type": "object", "properties": ["x"]}
        assert _is_schema_echo(data) is False

    def test_user_data_with_title_field(self):
        """Real user data that happens to have a 'title' field — NOT a schema echo."""
        data = {"title": "My Document", "body": "Some text content"}
        assert _is_schema_echo(data) is False

    def test_non_dict_returns_false(self):
        assert _is_schema_echo("not a dict") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _reject_schema_echo_items (online path)
# ---------------------------------------------------------------------------


class TestRejectSchemaEchoItems:
    """Tests for the online-path schema-echo rejection wrapper."""

    def test_replaces_echo_with_parse_error(self):
        response = [FULL_ECHO]
        result = _reject_schema_echo_items(response, "test_action")
        assert len(result) == 1
        assert "_parse_error" in result[0]
        assert "raw_response" in result[0]
        assert "Schema-echo" in result[0]["_parse_error"]

    def test_preserves_valid_items(self):
        response = [VALID_OUTPUT]
        result = _reject_schema_echo_items(response, "test_action")
        assert result is response  # unchanged — same object
        assert result[0] == VALID_OUTPUT

    def test_mixed_response_replaces_only_echoes(self):
        response = [VALID_OUTPUT, FULL_ECHO]
        result = _reject_schema_echo_items(response, "test_action")
        assert result[0] == VALID_OUTPUT
        assert "_parse_error" in result[1]
        assert "Schema-echo" in result[1]["_parse_error"]

    def test_non_list_passthrough(self):
        """Non-list responses pass through unchanged."""
        result = _reject_schema_echo_items("not a list", "test_action")
        assert result == "not a list"

    def test_empty_list_passthrough(self):
        result = _reject_schema_echo_items([], "test_action")
        assert result == []

    def test_all_echoes_replaced(self):
        response = [FULL_ECHO, PARTIAL_ECHO]
        result = _reject_schema_echo_items(response, "test_action")
        assert all("_parse_error" in item for item in result)
