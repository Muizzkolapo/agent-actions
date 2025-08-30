"""
Production-grade caching system for WHERE clause operations.
Implements multi-level caching with TTL, LRU eviction, and performance monitoring.
"""
import time
import threading
import hashlib
import pickle
from typing import Any, Dict, Optional, Union, Callable, TypeVar, Generic
from dataclasses import dataclass
from collections import OrderedDict
from datetime import datetime, timedelta
import logging
import weakref

from ..monitoring.metrics import get_metrics_collector, record_where_clause_cache_hit, record_where_clause_cache_miss
from ..monitoring.logging import LoggerFactory, StructuredLogger
from agent_actions.cli.exceptions import DependencyError

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class CacheEntry:
    """Represents a cache entry with metadata."""
    value: Any
    created_at: float
    accessed_at: float
    access_count: int
    ttl: Optional[float] = None
    
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl
    
    def touch(self):
        """Update access time and count."""
        self.accessed_at = time.time()
        self.access_count += 1


class LRUCache(Generic[T]):
    """
    Thread-safe LRU cache with TTL support and monitoring.
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None, logger_factory: LoggerFactory = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'size': 0
        }
        
        self.metrics = get_metrics_collector()
        if logger_factory is None:
            # Create a basic logger factory if none provided
            logger_factory = LoggerFactory()
        self.structured_logger = logger_factory.create_logger()
    
    def get(self, key: str) -> Optional[T]:
        """Get value from cache."""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                
                # Check if expired
                if entry.is_expired():
                    del self._cache[key]
                    self._stats['misses'] += 1
                    self._stats['size'] = len(self._cache)
                    return None
                
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                entry.touch()
                
                self._stats['hits'] += 1
                return entry.value
            else:
                self._stats['misses'] += 1
                return None
    
    def put(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Put value in cache."""
        with self._lock:
            # Use default TTL if not specified
            if ttl is None:
                ttl = self.default_ttl
            
            # Create cache entry
            entry = CacheEntry(
                value=value,
                created_at=time.time(),
                accessed_at=time.time(),
                access_count=1,
                ttl=ttl
            )
            
            # If key already exists, update it
            if key in self._cache:
                self._cache[key] = entry
                self._cache.move_to_end(key)
            else:
                # Add new entry
                self._cache[key] = entry
                
                # Check if we need to evict
                if len(self._cache) > self.max_size:
                    self._evict_lru()
            
            self._stats['size'] = len(self._cache)
    
    def _evict_lru(self):
        """Evict least recently used items."""
        while len(self._cache) > self.max_size:
            # Remove from beginning (least recently used)
            evicted_key, _ = self._cache.popitem(last=False)
            self._stats['evictions'] += 1
            
            self.structured_logger.debug(
                f"Cache evicted key: {evicted_key}",
                context={'component': 'cache', 'operation': 'eviction'}
            )
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats['size'] = len(self._cache)
                return True
            return False
    
    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._stats['size'] = 0
    
    def cleanup_expired(self):
        """Remove expired entries."""
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self._cache[key]
                self._stats['evictions'] += 1
            
            self._stats['size'] = len(self._cache)
            
            if expired_keys:
                self.structured_logger.debug(
                    f"Cleaned up {len(expired_keys)} expired cache entries",
                    context={'component': 'cache', 'operation': 'cleanup'}
                )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = self._stats['hits'] / total_requests if total_requests > 0 else 0.0
            
            return {
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': hit_rate,
                'evictions': self._stats['evictions'],
                'current_size': self._stats['size'],
                'max_size': self.max_size,
                'fill_ratio': self._stats['size'] / self.max_size
            }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information."""
        with self._lock:
            entries_info = []
            current_time = time.time()
            
            for key, entry in self._cache.items():
                entries_info.append({
                    'key': key,
                    'age_seconds': current_time - entry.created_at,
                    'access_count': entry.access_count,
                    'last_accessed_seconds_ago': current_time - entry.accessed_at,
                    'ttl': entry.ttl,
                    'is_expired': entry.is_expired()
                })
            
            stats = self.get_stats()
            stats['entries'] = entries_info
            return stats


class MultiLevelCache:
    """
    Multi-level cache with L1 (in-memory) and L2 (persistent) storage.
    """
    
    def __init__(
        self,
        l1_max_size: int = 1000,
        l1_ttl: Optional[float] = 300,  # 5 minutes
        l2_max_size: int = 10000,
        l2_ttl: Optional[float] = 3600,  # 1 hour
        enable_l2: bool = True,
        logger_factory: LoggerFactory = None
    ):
        if logger_factory is None:
            logger_factory = LoggerFactory()
            
        self.l1_cache = LRUCache[Any](l1_max_size, l1_ttl, logger_factory)
        self.l2_cache = LRUCache[Any](l2_max_size, l2_ttl, logger_factory) if enable_l2 else None
        self.enable_l2 = enable_l2
        
        self.metrics = get_metrics_collector()
        self.structured_logger = logger_factory.create_logger()
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self._cleanup_thread.start()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from multi-level cache."""
        # Try L1 first
        value = self.l1_cache.get(key)
        if value is not None:
            record_where_clause_cache_hit("l1")
            return value
        
        # Try L2 if enabled
        if self.enable_l2 and self.l2_cache:
            value = self.l2_cache.get(key)
            if value is not None:
                # Promote to L1
                self.l1_cache.put(key, value)
                record_where_clause_cache_hit("l2")
                return value
        
        record_where_clause_cache_miss("multi_level")
        return None
    
    def put(self, key: str, value: Any, l1_ttl: Optional[float] = None, l2_ttl: Optional[float] = None):
        """Put value in multi-level cache."""
        # Store in L1
        self.l1_cache.put(key, value, l1_ttl)
        
        # Store in L2 if enabled
        if self.enable_l2 and self.l2_cache:
            self.l2_cache.put(key, value, l2_ttl)
    
    def delete(self, key: str):
        """Delete from all cache levels."""
        self.l1_cache.delete(key)
        if self.enable_l2 and self.l2_cache:
            self.l2_cache.delete(key)
    
    def clear(self):
        """Clear all cache levels."""
        self.l1_cache.clear()
        if self.enable_l2 and self.l2_cache:
            self.l2_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        stats = {
            'l1': self.l1_cache.get_stats()
        }
        
        if self.enable_l2 and self.l2_cache:
            stats['l2'] = self.l2_cache.get_stats()
        
        return stats
    
    def _periodic_cleanup(self):
        """Periodic cleanup of expired entries."""
        while True:
            try:
                time.sleep(60)  # Run every minute
                
                self.l1_cache.cleanup_expired()
                if self.enable_l2 and self.l2_cache:
                    self.l2_cache.cleanup_expired()
            
            except Exception as e:
                self.structured_logger.error(
                    f"Error in cache cleanup: {e}",
                    context={'component': 'cache', 'operation': 'cleanup_error'}
                )


class CacheManager:
    """
    Centralized cache manager for WHERE clause operations.
    """
    
    def __init__(self, logger_factory: LoggerFactory):
        # Validate required dependency
        if logger_factory is None:
            raise DependencyError("CacheManager", "logger_factory")
        
        self._caches: Dict[str, Union[LRUCache, MultiLevelCache]] = {}
        self._lock = threading.RLock()
        self._logger_factory = logger_factory
        self.metrics = get_metrics_collector()
        self.structured_logger = logger_factory.create_logger()
        
        # Initialize default caches
        self._initialize_default_caches()
    
    def _initialize_default_caches(self):
        """Initialize default caches for WHERE clause operations."""
        # Parse cache for parsed WHERE clauses
        self.register_cache(
            "where_clause_parse",
            MultiLevelCache(
                l1_max_size=500,
                l1_ttl=300,  # 5 minutes
                l2_max_size=2000,
                l2_ttl=1800,  # 30 minutes
                logger_factory=self._logger_factory
            )
        )
        
        # Evaluation cache for data evaluation results
        self.register_cache(
            "where_clause_eval",
            LRUCache(
                max_size=1000,
                default_ttl=60,  # 1 minute (shorter due to data dependency)
                logger_factory=self._logger_factory
            )
        )
        
        # Field access cache for nested field lookups
        self.register_cache(
            "field_access",
            LRUCache(
                max_size=2000,
                default_ttl=600,  # 10 minutes
                logger_factory=self._logger_factory
            )
        )
    
    def register_cache(self, name: str, cache: Union[LRUCache, MultiLevelCache]):
        """Register a named cache."""
        with self._lock:
            self._caches[name] = cache
        
        self.structured_logger.info(
            f"Cache registered: {name}",
            context={'component': 'cache_manager', 'operation': 'register'}
        )
    
    def get_cache(self, name: str) -> Optional[Union[LRUCache, MultiLevelCache]]:
        """Get a named cache."""
        with self._lock:
            return self._caches.get(name)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all caches."""
        with self._lock:
            stats = {}
            for name, cache in self._caches.items():
                try:
                    stats[name] = cache.get_stats()
                except Exception as e:
                    stats[name] = {'error': str(e)}
            return stats
    
    def clear_all_caches(self):
        """Clear all caches."""
        with self._lock:
            for cache in self._caches.values():
                cache.clear()
        
        self.structured_logger.info(
            "All caches cleared",
            context={'component': 'cache_manager', 'operation': 'clear_all'}
        )


# Decorator for caching function results
def cached(
    cache_name: str = "default",
    ttl: Optional[float] = None,
    key_func: Optional[Callable] = None
):
    """
    Decorator to cache function results.
    
    Args:
        cache_name: Name of the cache to use
        ttl: Time to live for cached values
        key_func: Function to generate cache key from function arguments
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            manager = get_cache_manager()
            cache = manager.get_cache(cache_name)
            
            if cache is None:
                # No cache available, execute function directly
                return func(*args, **kwargs)
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default key generation
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = hashlib.md5("|".join(key_parts).encode()).hexdigest()
            
            # Try to get from cache
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.put(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


# Global cache manager
_cache_manager: Optional[CacheManager] = None
_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """Get or create the global cache manager."""
    global _cache_manager
    
    if _cache_manager is None:
        with _manager_lock:
            if _cache_manager is None:
                # Create with default LoggerFactory for backward compatibility
                # This should be replaced with proper DI in the future
                _cache_manager = CacheManager(LoggerFactory())
    
    return _cache_manager


def init_cache_manager(logger_factory: LoggerFactory = None) -> CacheManager:
    """Initialize the global cache manager.
    
    Args:
        logger_factory: Optional LoggerFactory for the cache manager.
                       If not provided, a default one will be created.
    """
    global _cache_manager
    
    with _manager_lock:
        if logger_factory is None:
            logger_factory = LoggerFactory()
        _cache_manager = CacheManager(logger_factory)
    
    return _cache_manager


# Convenience functions for WHERE clause caching
def cache_where_clause_parse(clause: str, result: Any, ttl: Optional[float] = None):
    """Cache WHERE clause parse result."""
    manager = get_cache_manager()
    cache = manager.get_cache("where_clause_parse")
    if cache:
        key = hashlib.md5(f"parse:{clause}".encode()).hexdigest()
        cache.put(key, result, ttl)


def get_cached_where_clause_parse(clause: str) -> Optional[Any]:
    """Get cached WHERE clause parse result."""
    manager = get_cache_manager()
    cache = manager.get_cache("where_clause_parse")
    if cache:
        key = hashlib.md5(f"parse:{clause}".encode()).hexdigest()
        return cache.get(key)
    return None


def cache_where_clause_eval(clause: str, data_hash: str, result: bool, ttl: Optional[float] = None):
    """Cache WHERE clause evaluation result."""
    manager = get_cache_manager()
    cache = manager.get_cache("where_clause_eval")
    if cache:
        key = hashlib.md5(f"eval:{clause}:{data_hash}".encode()).hexdigest()
        cache.put(key, result, ttl)


def get_cached_where_clause_eval(clause: str, data_hash: str) -> Optional[bool]:
    """Get cached WHERE clause evaluation result."""
    manager = get_cache_manager()
    cache = manager.get_cache("where_clause_eval")
    if cache:
        key = hashlib.md5(f"eval:{clause}:{data_hash}".encode()).hexdigest()
        return cache.get(key)
    return None


def cache_field_access(field_path: str, data_hash: str, result: Any, ttl: Optional[float] = None):
    """Cache field access result."""
    manager = get_cache_manager()
    cache = manager.get_cache("field_access")
    if cache:
        key = hashlib.md5(f"field:{field_path}:{data_hash}".encode()).hexdigest()
        cache.put(key, result, ttl)


def get_cached_field_access(field_path: str, data_hash: str) -> Optional[Any]:
    """Get cached field access result."""
    manager = get_cache_manager()
    cache = manager.get_cache("field_access")
    if cache:
        key = hashlib.md5(f"field:{field_path}:{data_hash}".encode()).hexdigest()
        return cache.get(key)
    return None


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics for all caches."""
    manager = get_cache_manager()
    return manager.get_all_stats()


def clear_all_caches():
    """Clear all caches."""
    manager = get_cache_manager()
    manager.clear_all_caches()