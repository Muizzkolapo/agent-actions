"""Unit tests for the unified metadata system.

Tests cover:
- ResponseMetadata dataclass
- RetryMetadata dataclass
- UnifiedMetadata dataclass
- MetadataExtractor service
- MetadataTimer context manager
"""

import pytest
import time
from typing import Dict, Any

from agent_actions.utilities.metadata import (
    ResponseMetadata,
    RetryMetadata,
    UnifiedMetadata,
    MetadataExtractor,
    MetadataTimer,
)


class TestResponseMetadata:
    """Tests for ResponseMetadata dataclass."""

    def test_default_values(self):
        """Test that ResponseMetadata has correct default values."""
        metadata = ResponseMetadata()
        assert metadata.model is None
        assert metadata.finish_reason is None
        assert metadata.status_code is None
        assert metadata.provider is None
        assert metadata.usage is None
        assert metadata.latency_ms is None
        assert metadata.request_id is None
        assert metadata.raw == {}

    def test_to_dict_excludes_none(self):
        """Test that to_dict only includes non-None values."""
        metadata = ResponseMetadata(model="gpt-4", finish_reason="stop")
        result = metadata.to_dict()

        assert result == {"model": "gpt-4", "finish_reason": "stop"}
        assert "status_code" not in result
        assert "provider" not in result

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all set fields."""
        metadata = ResponseMetadata(
            model="claude-3",
            finish_reason="end_turn",
            status_code=200,
            provider="anthropic",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            latency_ms=150.5,
            request_id="req-123",
            raw={"type": "message"},
        )
        result = metadata.to_dict()

        assert result["model"] == "claude-3"
        assert result["finish_reason"] == "end_turn"
        assert result["status_code"] == 200
        assert result["provider"] == "anthropic"
        assert result["usage"]["total_tokens"] == 30
        assert result["latency_ms"] == 150.5
        assert result["request_id"] == "req-123"
        assert result["raw"]["type"] == "message"

    def test_from_dict(self):
        """Test that from_dict correctly creates instance."""
        data = {
            "model": "gpt-4",
            "finish_reason": "stop",
            "status_code": 200,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        metadata = ResponseMetadata.from_dict(data)

        assert metadata.model == "gpt-4"
        assert metadata.finish_reason == "stop"
        assert metadata.status_code == 200
        assert metadata.usage["total_tokens"] == 150

    def test_from_dict_empty(self):
        """Test from_dict with empty dict."""
        metadata = ResponseMetadata.from_dict({})
        assert metadata.model is None
        assert metadata.raw == {}


class TestRetryMetadata:
    """Tests for RetryMetadata dataclass."""

    def test_default_values(self):
        """Test default values for RetryMetadata."""
        metadata = RetryMetadata()
        assert metadata.was_retried is False
        assert metadata.retry_attempts == 0
        assert metadata.original_batch_id is None
        assert metadata.final_batch_id is None
        assert metadata.retry_reason is None

    def test_to_dict_minimal(self):
        """Test to_dict with only required fields."""
        metadata = RetryMetadata()
        result = metadata.to_dict()

        assert result["was_retried"] is False
        assert result["retry_attempts"] == 0
        assert "original_batch_id" not in result
        assert "final_batch_id" not in result

    def test_to_dict_with_batch_ids(self):
        """Test to_dict with batch IDs."""
        metadata = RetryMetadata(
            was_retried=True,
            retry_attempts=2,
            original_batch_id="batch-001",
            final_batch_id="batch-003",
            retry_reason="rate_limit",
        )
        result = metadata.to_dict()

        assert result["was_retried"] is True
        assert result["retry_attempts"] == 2
        assert result["original_batch_id"] == "batch-001"
        assert result["final_batch_id"] == "batch-003"
        assert result["retry_reason"] == "rate_limit"

    def test_from_dict(self):
        """Test from_dict creates correct instance."""
        data = {
            "was_retried": True,
            "retry_attempts": 3,
            "original_batch_id": "orig-001",
        }
        metadata = RetryMetadata.from_dict(data)

        assert metadata.was_retried is True
        assert metadata.retry_attempts == 3
        assert metadata.original_batch_id == "orig-001"
        assert metadata.final_batch_id is None


class TestUnifiedMetadata:
    """Tests for UnifiedMetadata dataclass."""

    def test_default_values(self):
        """Test default values."""
        metadata = UnifiedMetadata()
        assert metadata.response is None
        assert metadata.retry is None

    def test_to_dict_empty(self):
        """Test to_dict with no data."""
        metadata = UnifiedMetadata()
        result = metadata.to_dict()
        assert result == {}

    def test_to_dict_with_response(self):
        """Test to_dict with response metadata only."""
        response = ResponseMetadata(model="gpt-4", provider="openai")
        metadata = UnifiedMetadata(response=response)
        result = metadata.to_dict()

        assert "response" in result
        assert result["response"]["model"] == "gpt-4"
        assert "retry" not in result

    def test_to_dict_with_both(self):
        """Test to_dict with both response and retry metadata."""
        response = ResponseMetadata(model="claude-3")
        retry = RetryMetadata(was_retried=True, retry_attempts=1)
        metadata = UnifiedMetadata(response=response, retry=retry)
        result = metadata.to_dict()

        assert result["response"]["model"] == "claude-3"
        assert result["retry"]["was_retried"] is True

    def test_from_dict(self):
        """Test from_dict creates correct nested structure."""
        data = {
            "response": {"model": "gpt-4", "finish_reason": "stop"},
            "retry": {"was_retried": False, "retry_attempts": 0},
        }
        metadata = UnifiedMetadata.from_dict(data)

        assert metadata.response.model == "gpt-4"
        assert metadata.retry.was_retried is False


class TestMetadataExtractor:
    """Tests for MetadataExtractor service."""

    def test_extract_from_response_none(self):
        """Test extraction with None response."""
        metadata = MetadataExtractor.extract_from_response(
            response=None,
            provider="openai",
            model="gpt-4",
        )
        assert metadata.provider == "openai"
        assert metadata.model == "gpt-4"

    def test_extract_from_dict_response(self):
        """Test extraction from dict response."""
        response = {
            "model": "gpt-4-turbo",
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        metadata = MetadataExtractor.extract_from_response(
            response=response,
            provider="openai",
        )

        assert metadata.model == "gpt-4-turbo"
        assert metadata.finish_reason == "stop"
        assert metadata.provider == "openai"
        assert metadata.usage["total_tokens"] == 150

    def test_extract_model_from_config(self):
        """Test model extraction from agent_config."""
        metadata = MetadataExtractor.extract_from_response(
            response=None,
            agent_config={"model_name": "gpt-4", "model_vendor": "openai"},
        )

        assert metadata.model == "gpt-4"
        assert metadata.provider == "openai"

    def test_normalize_provider(self):
        """Test provider name normalization."""
        # Test various aliases
        providers = [
            ("openai", "openai"),
            ("azure", "openai"),
            ("anthropic", "anthropic"),
            ("claude", "anthropic"),
            ("ollama", "ollama"),
            ("gemini", "google"),
            ("vertexai", "google"),
        ]

        for input_provider, expected in providers:
            metadata = MetadataExtractor.extract_from_response(
                response=None,
                provider=input_provider,
            )
            assert metadata.provider == expected, f"Failed for {input_provider}"

    def test_extract_with_latency(self):
        """Test latency extraction."""
        metadata = MetadataExtractor.extract_from_response(
            response=None,
            latency_ms=250.5,
        )
        assert metadata.latency_ms == 250.5

    def test_build_retry_metadata(self):
        """Test building retry metadata."""
        retry = MetadataExtractor.build_retry_metadata(
            was_retried=True,
            retry_attempts=2,
            original_batch_id="batch-001",
            final_batch_id="batch-003",
        )

        assert isinstance(retry, RetryMetadata)
        assert retry.was_retried is True
        assert retry.retry_attempts == 2
        assert retry.original_batch_id == "batch-001"
        assert retry.final_batch_id == "batch-003"

    def test_build_retry_metadata_defaults(self):
        """Test building retry metadata with defaults."""
        retry = MetadataExtractor.build_retry_metadata()

        assert retry.was_retried is False
        assert retry.retry_attempts == 0
        assert retry.original_batch_id is None

    def test_build_unified_metadata(self):
        """Test building unified metadata container."""
        response = ResponseMetadata(model="gpt-4")
        retry = RetryMetadata(was_retried=False)

        unified = MetadataExtractor.build_unified_metadata(
            response_metadata=response,
            retry_metadata=retry,
        )

        assert isinstance(unified, UnifiedMetadata)
        assert unified.response.model == "gpt-4"
        assert unified.retry.was_retried is False


class TestMetadataTimer:
    """Tests for MetadataTimer context manager."""

    def test_context_manager(self):
        """Test timer as context manager."""
        with MetadataTimer() as timer:
            time.sleep(0.01)  # 10ms

        assert timer.elapsed_ms is not None
        assert timer.elapsed_ms >= 10  # At least 10ms

    def test_manual_start_stop(self):
        """Test manual start/stop."""
        timer = MetadataTimer()
        timer.start()
        time.sleep(0.01)
        elapsed = timer.stop()

        assert elapsed >= 10

    def test_elapsed_before_start(self):
        """Test elapsed_ms before timer is started."""
        timer = MetadataTimer()
        assert timer.elapsed_ms is None

    def test_elapsed_during_execution(self):
        """Test getting elapsed during execution."""
        timer = MetadataTimer()
        timer.start()
        time.sleep(0.01)

        # Should return current elapsed without stopping
        elapsed1 = timer.elapsed_ms
        time.sleep(0.01)
        elapsed2 = timer.elapsed_ms

        assert elapsed2 > elapsed1


class TestMetadataIntegration:
    """Integration tests for metadata consistency between batch and online modes."""

    def test_batch_online_consistency(self):
        """Test that batch and online modes produce consistent metadata structure."""
        # Simulate batch mode metadata
        batch_response = ResponseMetadata(
            model="gpt-4",
            finish_reason="stop",
            provider="openai",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        batch_retry = MetadataExtractor.build_retry_metadata(
            was_retried=True,
            retry_attempts=1,
            original_batch_id="batch-001",
            final_batch_id="batch-002",
        )

        # Simulate online mode metadata
        online_response = MetadataExtractor.extract_from_response(
            response={"model": "gpt-4", "finish_reason": "stop"},
            provider="openai",
        )
        online_retry = MetadataExtractor.build_retry_metadata(
            was_retried=False,
            retry_attempts=0,
        )

        # Both should produce valid dict structures
        batch_dict = batch_response.to_dict()
        online_dict = online_response.to_dict()

        # Common fields should exist in both
        assert "model" in batch_dict
        assert "model" in online_dict
        assert "finish_reason" in batch_dict
        assert "finish_reason" in online_dict

        # Retry metadata structure should be consistent
        batch_retry_dict = batch_retry.to_dict()
        online_retry_dict = online_retry.to_dict()

        assert "was_retried" in batch_retry_dict
        assert "was_retried" in online_retry_dict
        assert "retry_attempts" in batch_retry_dict
        assert "retry_attempts" in online_retry_dict

    def test_empty_metadata_structure(self):
        """Test that empty metadata still has valid structure."""
        response = MetadataExtractor.extract_from_response(response=None)
        retry = MetadataExtractor.build_retry_metadata()

        response_dict = response.to_dict()
        retry_dict = retry.to_dict()

        # Should be valid dicts (even if mostly empty)
        assert isinstance(response_dict, dict)
        assert isinstance(retry_dict, dict)

        # Retry should always have these fields
        assert "was_retried" in retry_dict
        assert "retry_attempts" in retry_dict
