"""Tests for logging filters."""

import logging

import pytest

from agent_actions.logging.filters import RedactingFilter, _redact_sensitive_data


class TestRedactingFilter:
    """Tests for RedactingFilter."""

    def test_redacts_api_key_patterns(self):
        """Test that API key patterns are redacted."""
        filter_instance = RedactingFilter()

        test_cases = [
            ("api_key=abc123", "api_key=***"),
            ("API_KEY=abc123", "api_key=***"),
            ("api-key=abc123", "api_key=***"),
            ("api_key='abc123'", "api_key=***"),
            ("api_key: abc123", "api_key=***"),
        ]

        for input_msg, expected in test_cases:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=input_msg,
                args=(),
                exc_info=None,
            )
            filter_instance.filter(record)
            assert expected in record.msg or "***" in record.msg, f"Failed for: {input_msg}"

    @pytest.mark.parametrize(
        "msg,sensitive_value",
        [
            pytest.param("secret=mysecretvalue", "mysecretvalue", id="secret"),
            pytest.param("token=mytokenvalue", "mytokenvalue", id="token"),
            pytest.param("password=mypassword123", "mypassword123", id="password"),
            pytest.param(
                "Using key sk-ant-api03-abcdefghij1234567890",
                "sk-ant-api03-abcdefghij1234567890",
                id="anthropic_key",
            ),
        ],
    )
    def test_redacts_sensitive_patterns(self, msg, sensitive_value):
        """Test that various sensitive patterns are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        filter_instance.filter(record)
        assert sensitive_value not in record.msg
        assert "***" in record.msg

    def test_redacts_openai_keys(self):
        """Test that OpenAI API keys are redacted with sk-*** prefix."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Using key sk-abcdefghij1234567890abcdefghij12",
            args=(),
            exc_info=None,
        )
        filter_instance.filter(record)
        assert "sk-abcdefghij1234567890abcdefghij12" not in record.msg
        assert "sk-***" in record.msg

    def test_redacts_google_keys(self):
        """Test that Google API keys are redacted with AIza*** prefix."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Using key AIzaSyC1234567890abcdefghijklmnopqrstuv",
            args=(),
            exc_info=None,
        )
        filter_instance.filter(record)
        assert "AIzaSyC1234567890abcdefghijklmnopqrstuv" not in record.msg
        assert "AIza***" in record.msg

    def test_multiple_patterns_in_single_message(self):
        """Test redacting multiple patterns in a single message."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="api_key=abc123 secret=xyz789 token=def456",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert "abc123" not in record.msg
        assert "xyz789" not in record.msg
        assert "def456" not in record.msg
        assert record.msg.count("***") >= 3

    def test_preserves_non_sensitive_content(self):
        """Test that non-sensitive content is preserved."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Processing user johndoe with email john@example.com",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert "johndoe" in record.msg
        assert "john@example.com" in record.msg

    def test_invalid_regex_pattern_logs_warning(self):
        """Test that an invalid regex pattern emits a warning instead of silently skipping."""
        import agent_actions.logging.filters as filters_mod

        warnings: list[str] = []
        original_warning = filters_mod.logger.warning

        def capture_warning(msg, *args):
            warnings.append(msg % args)

        filters_mod.logger.warning = capture_warning  # type: ignore[assignment]
        try:
            invalid_patterns = [r"[invalid(", r"secret=[^\s]+"]
            filter_instance = RedactingFilter(patterns=invalid_patterns)
        finally:
            filters_mod.logger.warning = original_warning  # type: ignore[assignment]

        # Invalid pattern should produce a warning
        assert any("Skipping invalid redaction pattern" in msg for msg in warnings)
        assert any("[invalid(" in msg for msg in warnings)

        # Valid pattern should still work
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="secret=mysecret", args=(), exc_info=None,
        )
        filter_instance.filter(record)
        assert "mysecret" not in record.msg
        assert "***" in record.msg

    def test_custom_patterns(self):
        """Test using custom redaction patterns."""
        custom_patterns = [r"email=[^\s]+"]
        filter_instance = RedactingFilter(patterns=custom_patterns)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="User email=john@example.com logged in",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert "john@example.com" not in record.msg
        assert "***" in record.msg

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case insensitive."""
        filter_instance = RedactingFilter()

        test_cases = [
            "API_KEY=value",
            "Api_Key=value",
            "api_key=value",
            "SECRET=value",
            "Secret=value",
            "secret=value",
        ]

        for msg in test_cases:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None,
            )
            filter_instance.filter(record)
            assert "***" in record.msg, f"Failed for: {msg}"

    def test_redacts_extra_fields_with_sensitive_keys(self):
        """Test that extra fields with sensitive key names are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing extra field redaction",
            args=(),
            exc_info=None,
        )
        # Add extra fields that should be redacted
        record.api_key = "sk-1234567890abcdefghij"
        record.secret_token = "my-secret-value"
        record.password = "plaintext-password"

        filter_instance.filter(record)

        assert record.api_key == "[REDACTED]"
        assert record.secret_token == "[REDACTED]"
        assert record.password == "[REDACTED]"

    def test_redacts_nested_dict_in_extra_fields(self):
        """Test that nested dictionaries in extra fields are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing nested dict redaction",
            args=(),
            exc_info=None,
        )
        # Add extra field with nested dict containing sensitive data
        record.config = {
            "model": "gpt-4",
            "api_key": "sk-abcdefghij1234567890",
            "settings": {"timeout": 30, "secret": "nested-secret-value"},
        }

        filter_instance.filter(record)

        # api_key and secret should be redacted, other fields preserved
        assert record.config["model"] == "gpt-4"
        assert record.config["api_key"] == "[REDACTED]"
        assert record.config["settings"]["timeout"] == 30
        assert record.config["settings"]["secret"] == "[REDACTED]"

    def test_redacts_list_of_dicts_in_extra_fields(self):
        """Test that lists of dictionaries in extra fields are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing list redaction",
            args=(),
            exc_info=None,
        )
        # Add extra field with list of dicts
        record.items = [
            {"name": "item1", "api_key": "sk-key1"},
            {"name": "item2", "token": "token-value"},
        ]

        filter_instance.filter(record)

        assert record.items[0]["name"] == "item1"
        assert record.items[0]["api_key"] == "[REDACTED]"
        assert record.items[1]["name"] == "item2"
        assert record.items[1]["token"] == "[REDACTED]"

    def test_preserves_non_sensitive_extra_fields(self):
        """Test that non-sensitive extra fields are not redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing preservation",
            args=(),
            exc_info=None,
        )
        # Add non-sensitive extra fields
        record.batch_id = "batch-123"
        record.model_name = "gpt-4"
        record.duration = 1.5
        record.status = "completed"

        filter_instance.filter(record)

        # All non-sensitive fields should be preserved
        assert record.batch_id == "batch-123"
        assert record.model_name == "gpt-4"
        assert record.duration == 1.5
        assert record.status == "completed"

    def test_redacts_string_values_in_extra_fields(self):
        """Test that string values containing sensitive patterns are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing string value redaction",
            args=(),
            exc_info=None,
        )
        # Add extra field with string containing API key
        record.auth_header = "Bearer sk-abcdefghij1234567890abcdefghij12"

        filter_instance.filter(record)

        # API key pattern should be redacted from the string
        assert "sk-abcdefghij1234567890abcdefghij12" not in record.auth_header
        assert "sk-***" in record.auth_header

    def test_redacts_correlation_context_extra_fields(self):
        """Test redaction works with correlation context fields present."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Testing with context",
            args=(),
            exc_info=None,
        )
        # Add correlation context fields (should not be redacted)
        record.correlation_id = "corr-123"
        record.workflow_name = "test-workflow"
        record.agent_name = "test-agent"
        record.batch_id = "batch-456"
        # Add sensitive field
        record.api_key = "sk-sensitive"

        filter_instance.filter(record)

        # Context fields preserved
        assert record.correlation_id == "corr-123"
        assert record.workflow_name == "test-workflow"
        assert record.agent_name == "test-agent"
        assert record.batch_id == "batch-456"
        # Sensitive field redacted
        assert record.api_key == "[REDACTED]"


class TestStandaloneRedactSensitiveData:
    """Tests for the standalone _redact_sensitive_data function (2-A)."""

    def test_redacts_dict_keys(self):
        """Sensitive dict keys are replaced with [REDACTED]."""
        data = {"model": "gpt-4", "api_key": "sk-secret", "timeout": 30}
        result = _redact_sensitive_data(data)
        assert result["model"] == "gpt-4"
        assert result["api_key"] == "[REDACTED]"
        assert result["timeout"] == 30

    def test_redacts_nested_dicts(self):
        """Nested dicts are redacted recursively."""
        data = {"config": {"secret": "val", "name": "ok"}}
        result = _redact_sensitive_data(data)
        assert result["config"]["secret"] == "[REDACTED]"
        assert result["config"]["name"] == "ok"

    def test_redacts_lists(self):
        """Lists of dicts are redacted element-wise."""
        data = [{"token": "abc"}, {"name": "safe"}]
        result = _redact_sensitive_data(data)
        assert result[0]["token"] == "[REDACTED]"
        assert result[1]["name"] == "safe"

    def test_redacts_string_patterns(self):
        """API key patterns in strings are redacted."""
        data = "key is sk-abcdefghij1234567890abcdefghij12"
        result = _redact_sensitive_data(data)
        assert "sk-abcdefghij1234567890abcdefghij12" not in result
        assert "sk-[REDACTED]" in result

    def test_no_baseclient_import(self):
        """filters.py must not import from llm providers."""
        import inspect

        import agent_actions.logging.filters as mod

        source = inspect.getsource(mod)
        assert "from agent_actions.llm.providers" not in source
