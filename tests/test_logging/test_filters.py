"""Tests for logging filters."""

import logging
import pytest

from agent_actions.logging.context import CorrelationContext
from agent_actions.logging.filters import ContextInjectingFilter, RedactingFilter


class TestContextInjectingFilter:
    """Tests for ContextInjectingFilter."""

    def setup_method(self):
        """Clear context before each test."""
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        CorrelationContext.clear_context()

    def test_filter_adds_empty_fields_without_context(self):
        """Test that filter adds empty fields when no context is set."""
        filter_instance = ContextInjectingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.correlation_id == ''
        assert record.workflow_name == ''
        assert record.agent_name == ''
        assert record.agent_index == -1
        assert record.batch_id == ''
        assert record.item_id == ''

    def test_filter_adds_context_fields(self):
        """Test that filter adds context fields when context is set."""
        CorrelationContext.start_workflow('test-workflow')
        CorrelationContext.set_agent('test-agent', 2)
        CorrelationContext.set_batch('batch-123')
        CorrelationContext.set_item('item-456')

        filter_instance = ContextInjectingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert len(record.correlation_id) == 8
        assert record.workflow_name == 'test-workflow'
        assert record.agent_name == 'test-agent'
        assert record.agent_index == 2
        assert record.batch_id == 'batch-123'
        assert record.item_id == 'item-456'

    def test_filter_adds_extra_context_fields(self):
        """Test that filter adds extra context fields."""
        CorrelationContext.start_workflow('test-workflow')
        CorrelationContext.add_extra('custom_field', 'custom_value')

        filter_instance = ContextInjectingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.custom_field == 'custom_value'

    def test_filter_does_not_overwrite_existing_record_attrs(self):
        """Test that filter doesn't overwrite existing record attributes."""
        CorrelationContext.start_workflow('test-workflow')
        CorrelationContext.add_extra('msg', 'should_not_overwrite')

        filter_instance = ContextInjectingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Original message',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        # msg should remain unchanged
        assert record.msg == 'Original message'

    def test_filter_handles_none_values_in_context(self):
        """Test that filter handles None values gracefully."""
        CorrelationContext.start_workflow('test-workflow')
        # Don't set agent, batch, or item - they remain None

        filter_instance = ContextInjectingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.workflow_name == 'test-workflow'
        assert record.agent_name == ''
        assert record.agent_index == -1
        assert record.batch_id == ''
        assert record.item_id == ''


class TestRedactingFilter:
    """Tests for RedactingFilter."""

    def test_redacts_api_key_patterns(self):
        """Test that API key patterns are redacted."""
        filter_instance = RedactingFilter()

        test_cases = [
            ('api_key=abc123', 'api_key=***'),
            ('API_KEY=abc123', 'api_key=***'),
            ('api-key=abc123', 'api_key=***'),
            ("api_key='abc123'", 'api_key=***'),
            ('api_key: abc123', 'api_key=***'),
        ]

        for input_msg, expected in test_cases:
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg=input_msg,
                args=(),
                exc_info=None,
            )
            filter_instance.filter(record)
            assert expected in record.msg or '***' in record.msg, f'Failed for: {input_msg}'

    def test_redacts_secret_patterns(self):
        """Test that secret patterns are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='secret=mysecretvalue',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'mysecretvalue' not in record.msg
        assert '***' in record.msg

    def test_redacts_token_patterns(self):
        """Test that token patterns are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='token=mytokenvalue',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'mytokenvalue' not in record.msg
        assert '***' in record.msg

    def test_redacts_password_patterns(self):
        """Test that password patterns are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='password=mypassword123',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'mypassword123' not in record.msg
        assert '***' in record.msg

    def test_redacts_openai_keys(self):
        """Test that OpenAI API keys are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Using key sk-abcdefghij1234567890abcdefghij12',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'sk-abcdefghij1234567890abcdefghij12' not in record.msg
        assert 'sk-***' in record.msg

    def test_redacts_anthropic_keys(self):
        """Test that Anthropic API keys are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Using key sk-ant-api03-abcdefghij1234567890',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'sk-ant-api03-abcdefghij1234567890' not in record.msg
        assert '***' in record.msg

    def test_redacts_google_keys(self):
        """Test that Google API keys are redacted."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Using key AIzaSyC1234567890abcdefghijklmnopqrstuv',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'AIzaSyC1234567890abcdefghijklmnopqrstuv' not in record.msg
        assert 'AIza***' in record.msg

    def test_multiple_patterns_in_single_message(self):
        """Test redacting multiple patterns in a single message."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='api_key=abc123 secret=xyz789 token=def456',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'abc123' not in record.msg
        assert 'xyz789' not in record.msg
        assert 'def456' not in record.msg
        assert record.msg.count('***') >= 3

    def test_preserves_non_sensitive_content(self):
        """Test that non-sensitive content is preserved."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Processing user johndoe with email john@example.com',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'johndoe' in record.msg
        assert 'john@example.com' in record.msg

    def test_custom_patterns(self):
        """Test using custom redaction patterns."""
        custom_patterns = [r'email=[^\s]+']
        filter_instance = RedactingFilter(patterns=custom_patterns)
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='User email=john@example.com logged in',
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert 'john@example.com' not in record.msg
        assert '***' in record.msg

    def test_filter_always_returns_true(self):
        """Test that filter always returns True to allow logging."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Any message',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True

    def test_handles_empty_message(self):
        """Test handling of empty log messages."""
        filter_instance = RedactingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='',
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.msg == ''

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case insensitive."""
        filter_instance = RedactingFilter()

        test_cases = [
            'API_KEY=value',
            'Api_Key=value',
            'api_key=value',
            'SECRET=value',
            'Secret=value',
            'secret=value',
        ]

        for msg in test_cases:
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None,
            )
            filter_instance.filter(record)
            assert '***' in record.msg, f'Failed for: {msg}'
