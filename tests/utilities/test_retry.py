"""Unit tests for retry utility."""

import pytest
import time
import asyncio
from unittest.mock import Mock, call
from agent_actions.utilities.retry import RetryStrategy, retry


class CustomError(Exception):
    pass


def test_retry_strategy_initialization():
    """Test RetryStrategy initialization with defaults and custom values."""
    strategy = RetryStrategy()
    assert strategy.max_attempts == 3
    assert strategy.delay == 1.0
    assert strategy.backoff == 2.0

    custom = RetryStrategy(max_attempts=5, delay=0.1, backoff=1.5)
    assert custom.max_attempts == 5
    assert custom.delay == 0.1
    assert custom.backoff == 1.5


def test_retry_sync_success():
    """Test successful execution without retries."""
    mock_func = Mock(return_value="success")

    @retry(max_attempts=3, delay=0.01)
    def decorated_func():
        return mock_func()

    result = decorated_func()
    assert result == "success"
    assert mock_func.call_count == 1


def test_retry_sync_failure_then_success():
    """Test retries on failure eventually succeeding."""
    mock_func = Mock(side_effect=[ValueError("fail"), ValueError("fail"), "success"])

    @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
    def decorated_func():
        return mock_func()

    result = decorated_func()
    assert result == "success"
    assert mock_func.call_count == 3


def test_retry_sync_exhausted():
    """Test retries exhausted raises last exception."""
    mock_func = Mock(side_effect=ValueError("fail"))

    @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
    def decorated_func():
        return mock_func()

    with pytest.raises(ValueError, match="fail"):
        decorated_func()
    assert mock_func.call_count == 3


def test_retry_unhandled_exception():
    """Test unhandled exception is raised immediately."""
    mock_func = Mock(side_effect=KeyError("fail"))

    @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
    def decorated_func():
        return mock_func()

    with pytest.raises(KeyError, match="fail"):
        decorated_func()
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_retry_async_success():
    """Test async function success."""
    mock_func = Mock(return_value="success")

    @retry(max_attempts=3, delay=0.01)
    async def decorated_func():
        return mock_func()

    result = await decorated_func()
    assert result == "success"
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_retry_async_failure_then_success():
    """Test async function retries."""
    mock_func = Mock(side_effect=[ValueError("fail"), "success"])

    @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
    async def decorated_func():
        return mock_func()

    result = await decorated_func()
    assert result == "success"
    assert mock_func.call_count == 2
