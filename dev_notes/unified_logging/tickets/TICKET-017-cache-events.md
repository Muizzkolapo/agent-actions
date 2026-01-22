# TICKET-017: Add Cache Events

**Status:** 🔲 TODO
**Priority:** Medium
**Estimate:** 3-4 hours
**Labels:** logging, cache, performance

## Description

Add event instrumentation for all cache operations to provide visibility into cache hit rates, invalidation, and performance.

## Deliverables

- [ ] Define cache event types (C001-C006)
- [ ] Instrument batch registry cache
- [ ] Instrument static data file cache
- [ ] Instrument module loading cache
- [ ] Instrument schema type cache
- [ ] Instrument parser LRU cache
- [ ] Instrument batch client cache

## Cache Systems Identified

### 1. Batch Registry Cache (CRITICAL)
**File:** `agent_actions/llm/batch/infrastructure/registry.py`

**Cache Type:** In-memory dict with file persistence

**Methods to instrument:**
- `get_batch_job()` (line 83) - Fire CacheHitEvent/CacheMissEvent
- `get_batch_job_by_id()` (line 97) - Fire CacheHitEvent/CacheMissEvent
- `save_batch_job()` (line 66) - Fire CacheUpdateEvent
- `invalidate_cache()` (line 250) - Fire CacheInvalidationEvent
- `_ensure_cache_loaded()` (line 264) - Fire CacheLoadEvent

### 2. Static Data File Cache (HIGH)
**File:** `agent_actions/prompt/context/static_loader.py`

**Cache Type:** Dictionary cache for loaded files

**Methods to instrument:**
- `load_static_data()` (line 57) - Fire hit/miss per field (lines 74-77)
- `clear_cache()` (line 326) - Fire CacheInvalidationEvent
- `get_cache_stats()` (line 332) - Fire CacheStatsEvent

### 3. Module Loading Cache (HIGH)
**File:** `agent_actions/utils/module_loader.py`

**Cache Types:** Path cache (Set) + Module cache (Dict)

**Functions to instrument:**
- `ensure_path_importable()` (line 83) - Fire PathCacheHitEvent (line 109)
- `load_module_from_path()` (line 223) - Fire ModuleCacheHitEvent (line 268)
- `clear_path_cache()` (line 206) - Fire CacheClearEvent
- `clear_module_cache()` (line 342) - Fire CacheClearEvent

### 4. Schema Type Cache (MEDIUM)
**File:** `agent_actions/utils/udf_management/type_conversion/converters.py`

**Cache Type:** Type to schema memoization

**Functions to instrument:**
- `derive_schema_from_type()` (line 109) - Fire hit/miss (line 126)
- `clear_schema_cache()` (line 393) - Fire CacheClearEvent

### 5. Parser LRU Cache (LOW)
**File:** `agent_actions/input/preprocessing/parsing/parser.py`

**Cache Type:** functools.lru_cache

**Methods to instrument:**
- `parse_cached()` (line 353) - Track cache statistics
- `clear_cache()` (line 451) - Fire CacheClearEvent
- `get_cache_info()` (line 455) - Periodic CacheStatsEvent

### 6. Batch Client Cache (MEDIUM)
**File:** `agent_actions/llm/batch/infrastructure/batch_client_resolver.py`

**Cache Type:** Client instance cache

**Methods to instrument:**
- `get_for_config()` (line 45) - Fire hit/miss (lines 99-122)
- `get_for_batch_id()` (line 131) - Fire hit/miss (lines 154-159)

## Event Types to Add

Add to `agent_actions/logging/events/types.py`:

```python
class CacheHitEvent(DebugLevel, BaseEvent):
    """C001 - Cache hit"""
    def __init__(self, cache_type: str, key: str, hit_rate: Optional[float] = None):
        super().__init__(
            message=f"Cache hit: {cache_type}[{key}]",
            category="cache",
            data={"cache_type": cache_type, "key": key, "hit_rate": hit_rate},
        )

class CacheMissEvent(DebugLevel, BaseEvent):
    """C002 - Cache miss"""
    def __init__(self, cache_type: str, key: str, reason: Optional[str] = None):
        super().__init__(
            message=f"Cache miss: {cache_type}[{key}]",
            category="cache",
            data={"cache_type": cache_type, "key": key, "reason": reason},
        )

class CacheInvalidationEvent(InfoLevel, BaseEvent):
    """C003 - Cache invalidated"""
    def __init__(self, cache_type: str, entries_removed: int, reason: Optional[str] = None):
        super().__init__(
            message=f"Cache invalidated: {cache_type} ({entries_removed} entries)",
            category="cache",
            data={"cache_type": cache_type, "entries_removed": entries_removed, "reason": reason},
        )

class CacheLoadEvent(DebugLevel, BaseEvent):
    """C004 - Cache loaded"""
    def __init__(self, cache_type: str, entries_loaded: int, source: str):
        super().__init__(
            message=f"Cache loaded: {cache_type} ({entries_loaded} entries from {source})",
            category="cache",
            data={"cache_type": cache_type, "entries_loaded": entries_loaded, "source": source},
        )

class CacheUpdateEvent(DebugLevel, BaseEvent):
    """C005 - Cache updated"""
    def __init__(self, cache_type: str, key: str):
        super().__init__(
            message=f"Cache updated: {cache_type}[{key}]",
            category="cache",
            data={"cache_type": cache_type, "key": key},
        )

class CacheStatsEvent(DebugLevel, BaseEvent):
    """C006 - Cache statistics"""
    def __init__(self, cache_type: str, hit_count: int, miss_count: int,
                 total_entries: int, size_bytes: Optional[int] = None):
        hit_rate = hit_count / (hit_count + miss_count) if (hit_count + miss_count) > 0 else 0
        super().__init__(
            message=f"Cache stats: {cache_type} ({hit_rate:.1%} hit rate)",
            category="cache",
            data={
                "cache_type": cache_type,
                "hit_count": hit_count,
                "miss_count": miss_count,
                "total_entries": total_entries,
                "size_bytes": size_bytes,
                "hit_rate": hit_rate,
            },
        )
```

## Implementation Example

```python
# In registry.py get_batch_job()
def get_batch_job(self, file_name: str) -> Optional[BatchJobEntry]:
    self._ensure_cache_loaded()

    if file_name in self._cache:
        fire_event(CacheHitEvent("batch_registry", file_name))
        return self._cache[file_name]

    fire_event(CacheMissEvent("batch_registry", file_name))
    return None
```

## Acceptance Criteria

- [ ] All 6 cache systems fire events
- [ ] Cache hit rates visible in debug logs
- [ ] Cache invalidation tracked
- [ ] Tests verify event firing
