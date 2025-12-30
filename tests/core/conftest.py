"""
Test configuration for core module tests.

This module configures anyio backend selection for async tests.
"""

import pytest


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request):
    """Parametrize tests to run with both asyncio and trio backends."""
    return request.param
