"""Cache lifecycle events (C prefix)."""

from dataclasses import dataclass

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "CacheHitEvent",
    "CacheMissEvent",
    "CacheInvalidationEvent",
    "CacheLoadEvent",
    "CacheUpdateEvent",
    "CacheStatsEvent",
]


@dataclass
class CacheHitEvent(BaseEvent):
    """Fired when a cache hit occurs."""

    cache_type: str = ""
    key: str = ""
    hit_rate: float | None = None

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        hit_rate_str = f" (hit rate: {self.hit_rate:.1%})" if self.hit_rate is not None else ""
        self.message = f"Cache hit: {self.cache_type}[{self.key}]{hit_rate_str}"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
            "hit_rate": self.hit_rate,
        }

    @property
    def code(self) -> str:
        return "C001"


@dataclass
class CacheMissEvent(BaseEvent):
    """Fired when a cache miss occurs."""

    cache_type: str = ""
    key: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        reason_str = f" ({self.reason})" if self.reason else ""
        self.message = f"Cache miss: {self.cache_type}[{self.key}]{reason_str}"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
            "reason": self.reason,
        }

    @property
    def code(self) -> str:
        return "C002"


@dataclass
class CacheInvalidationEvent(BaseEvent):
    """Fired when cache is invalidated."""

    cache_type: str = ""
    entries_removed: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.CACHE
        reason_str = f" - {self.reason}" if self.reason else ""
        self.message = (
            f"Cache invalidated: {self.cache_type} ({self.entries_removed} entries){reason_str}"
        )
        self.data = {
            "cache_type": self.cache_type,
            "entries_removed": self.entries_removed,
            "reason": self.reason,
        }

    @property
    def code(self) -> str:
        return "C003"


@dataclass
class CacheLoadEvent(BaseEvent):
    """Fired when cache is loaded."""

    cache_type: str = ""
    entries_loaded: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        self.message = (
            f"Cache loaded: {self.cache_type} ({self.entries_loaded} entries from {self.source})"
        )
        self.data = {
            "cache_type": self.cache_type,
            "entries_loaded": self.entries_loaded,
            "source": self.source,
        }

    @property
    def code(self) -> str:
        return "C004"


@dataclass
class CacheUpdateEvent(BaseEvent):
    """Fired when cache is updated."""

    cache_type: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        self.message = f"Cache updated: {self.cache_type}[{self.key}]"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
        }

    @property
    def code(self) -> str:
        return "C005"


@dataclass
class CacheStatsEvent(BaseEvent):
    """Fired to report cache statistics."""

    cache_type: str = ""
    hit_count: int = 0
    miss_count: int = 0
    total_entries: int = 0
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        total_accesses = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total_accesses if total_accesses > 0 else 0.0
        size_str = f" | {self.size_bytes:,} bytes" if self.size_bytes is not None else ""
        self.message = (
            f"Cache stats: {self.cache_type} - {hit_rate:.1%} hit rate "
            f"({self.hit_count} hits, {self.miss_count} misses, {self.total_entries} entries{size_str})"
        )
        self.data = {
            "cache_type": self.cache_type,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "total_entries": self.total_entries,
            "size_bytes": self.size_bytes,
            "hit_rate": hit_rate,
        }

    @property
    def code(self) -> str:
        return "C006"
