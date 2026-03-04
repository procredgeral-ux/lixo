"""Cache module - Redis client and caching utilities"""

# Re-export everything from the original cache backends
from core._cache_backends import (
    CacheBackend,
    InMemoryCache,
    RedisCache,
    get_cache,
    cache_get,
    cache_set,
    cache_delete,
    cache_exists,
    cache_clear,
)

# Export the new Redis security client
from core.cache.redis_client import (
    RedisManager,
    redis_manager,
    initialize_redis,
    close_redis,
    KeyGenerator
)

__all__ = [
    # Original cache exports
    'CacheBackend',
    'InMemoryCache',
    'RedisCache',
    'get_cache',
    'cache_get',
    'cache_set',
    'cache_delete',
    'cache_exists',
    'cache_clear',
    # New Redis client exports
    'RedisManager',
    'redis_manager',
    'initialize_redis',
    'close_redis',
    'KeyGenerator'
]
