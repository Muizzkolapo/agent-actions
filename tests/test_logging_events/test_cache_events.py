"""Tests for cache event types.

This module tests all cache event types and verifies they're
properly emitted by the various cache systems.
"""

import pytest
from agent_actions.logging.events.types import (
    CacheHitEvent,
    CacheMissEvent,
    CacheInvalidationEvent,
    CacheLoadEvent,
    CacheUpdateEvent,
    CacheStatsEvent,
    EventCategories,
)
from agent_actions.logging.core.events import EventLevel


class TestCacheEventCreation:
    """Tests for cache event creation and properties."""

    def test_cache_hit_event(self):
        """Test CacheHitEvent creation and properties."""
        event = CacheHitEvent(cache_type="test_cache", key="test_key", hit_rate=0.85)

        assert event.code == "C001"
        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache hit" in event.message
        assert "test_cache" in event.message
        assert "test_key" in event.message
        assert event.data["cache_type"] == "test_cache"
        assert event.data["key"] == "test_key"
        assert event.data["hit_rate"] == 0.85

    def test_cache_hit_event_without_rate(self):
        """Test CacheHitEvent without hit_rate."""
        event = CacheHitEvent(cache_type="test_cache", key="test_key")

        assert event.code == "C001"
        assert event.data["hit_rate"] is None
        # Message should not include hit rate when None
        assert "hit rate" not in event.message.lower() or event.message.endswith("]")

    def test_cache_miss_event(self):
        """Test CacheMissEvent creation and properties."""
        event = CacheMissEvent(cache_type="test_cache", key="test_key", reason="not found")

        assert event.code == "C002"
        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache miss" in event.message
        assert "test_cache" in event.message
        assert "test_key" in event.message
        assert "not found" in event.message
        assert event.data["cache_type"] == "test_cache"
        assert event.data["key"] == "test_key"
        assert event.data["reason"] == "not found"

    def test_cache_invalidation_event(self):
        """Test CacheInvalidationEvent creation and properties."""
        event = CacheInvalidationEvent(
            cache_type="test_cache", entries_removed=42, reason="manual clear"
        )

        assert event.code == "C003"
        assert event.level == EventLevel.INFO  # Note: INFO level, not DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache invalidated" in event.message
        assert "test_cache" in event.message
        assert "42 entries" in event.message
        assert "manual clear" in event.message
        assert event.data["cache_type"] == "test_cache"
        assert event.data["entries_removed"] == 42
        assert event.data["reason"] == "manual clear"

    def test_cache_load_event(self):
        """Test CacheLoadEvent creation and properties."""
        event = CacheLoadEvent(cache_type="test_cache", entries_loaded=100, source="disk")

        assert event.code == "C004"
        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache loaded" in event.message
        assert "test_cache" in event.message
        assert "100 entries" in event.message
        assert "disk" in event.message
        assert event.data["cache_type"] == "test_cache"
        assert event.data["entries_loaded"] == 100
        assert event.data["source"] == "disk"

    def test_cache_update_event(self):
        """Test CacheUpdateEvent creation and properties."""
        event = CacheUpdateEvent(cache_type="test_cache", key="test_key")

        assert event.code == "C005"
        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache updated" in event.message
        assert "test_cache" in event.message
        assert "test_key" in event.message
        assert event.data["cache_type"] == "test_cache"
        assert event.data["key"] == "test_key"

    def test_cache_stats_event(self):
        """Test CacheStatsEvent creation and properties."""
        event = CacheStatsEvent(
            cache_type="test_cache", hit_count=85, miss_count=15, total_entries=50, size_bytes=1024
        )

        assert event.code == "C006"
        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.CACHE
        assert "Cache stats" in event.message
        assert "test_cache" in event.message
        assert "85.0%" in event.message  # Hit rate
        assert event.data["cache_type"] == "test_cache"
        assert event.data["hit_count"] == 85
        assert event.data["miss_count"] == 15
        assert event.data["total_entries"] == 50
        assert event.data["size_bytes"] == 1024
        assert event.data["hit_rate"] == 0.85  # 85/100

    def test_cache_stats_event_zero_accesses(self):
        """Test CacheStatsEvent with zero hits/misses."""
        event = CacheStatsEvent(cache_type="test_cache", hit_count=0, miss_count=0, total_entries=0)

        assert event.code == "C006"
        assert event.data["hit_rate"] == 0.0  # Should not divide by zero
        assert "0.0%" in event.message

    def test_cache_stats_event_without_size(self):
        """Test CacheStatsEvent without size_bytes."""
        event = CacheStatsEvent(
            cache_type="test_cache", hit_count=10, miss_count=5, total_entries=20
        )

        assert event.code == "C006"
        assert event.data["size_bytes"] is None


class TestCacheEventSerialization:
    """Tests for cache event serialization."""

    def test_cache_hit_event_to_dict(self):
        """Test CacheHitEvent serialization."""
        event = CacheHitEvent(cache_type="test_cache", key="test_key", hit_rate=0.90)

        event_dict = event.to_dict()

        assert event_dict["code"] == "C001"
        assert event_dict["level"] == "debug"
        assert event_dict["category"] == "cache"
        assert event_dict["data"]["cache_type"] == "test_cache"
        assert event_dict["data"]["key"] == "test_key"
        assert event_dict["data"]["hit_rate"] == 0.90

    def test_cache_stats_event_to_dict(self):
        """Test CacheStatsEvent serialization."""
        event = CacheStatsEvent(
            cache_type="test_cache", hit_count=80, miss_count=20, total_entries=100, size_bytes=2048
        )

        event_dict = event.to_dict()

        assert event_dict["code"] == "C006"
        assert event_dict["data"]["hit_rate"] == 0.80
        assert event_dict["data"]["size_bytes"] == 2048


class TestCacheEventCategories:
    """Tests for event categorization."""

    def test_all_cache_events_use_cache_category(self):
        """Verify all cache events use the CACHE category."""
        events = [
            CacheHitEvent(cache_type="test", key="key"),
            CacheMissEvent(cache_type="test", key="key"),
            CacheInvalidationEvent(cache_type="test", entries_removed=0),
            CacheLoadEvent(cache_type="test", entries_loaded=0, source="test"),
            CacheUpdateEvent(cache_type="test", key="key"),
            CacheStatsEvent(cache_type="test", hit_count=0, miss_count=0, total_entries=0),
        ]

        for event in events:
            assert event.category == EventCategories.CACHE


class TestCacheEventLevels:
    """Tests for event level assignments."""

    def test_most_cache_events_are_debug(self):
        """Verify most cache events are DEBUG level."""
        debug_events = [
            CacheHitEvent(cache_type="test", key="key"),
            CacheMissEvent(cache_type="test", key="key"),
            CacheLoadEvent(cache_type="test", entries_loaded=0, source="test"),
            CacheUpdateEvent(cache_type="test", key="key"),
            CacheStatsEvent(cache_type="test", hit_count=0, miss_count=0, total_entries=0),
        ]

        for event in debug_events:
            assert event.level == EventLevel.DEBUG

    def test_cache_invalidation_is_info(self):
        """Verify CacheInvalidationEvent is INFO level."""
        event = CacheInvalidationEvent(cache_type="test", entries_removed=10)

        assert event.level == EventLevel.INFO
