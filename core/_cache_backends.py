"""Cache management using Redis or in-memory fallback"""
from typing import Optional, Any
import asyncio
import json
from core.config import settings


class CacheBackend:
    """Cache backend interface"""
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        raise NotImplementedError
    
    async def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache"""
        raise NotImplementedError
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        raise NotImplementedError
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        raise NotImplementedError
    
    async def clear(self) -> bool:
        """Clear all cache"""
        raise NotImplementedError


class InMemoryCache(CacheBackend):
    """In-memory cache fallback when Redis is not available"""
    
    def __init__(self):
        self._cache: dict = {}
        self._ttl: dict = {}
        self._lock = asyncio.Lock()
        self._total_size_bytes = 0
    
    def _estimate_size(self, value: Any) -> int:
        """Estimar tamanho em bytes de um valor"""
        try:
            if isinstance(value, (str, bytes)):
                return len(value)
            elif isinstance(value, (int, float, bool)):
                return 8
            else:
                # Estimativa via JSON
                return len(json.dumps(value))
        except Exception:
            return 100  # Valor padrão
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        async with self._lock:
            if key not in self._cache:
                return None

            # Check TTL
            if key in self._ttl:
                import time
                if time.time() > self._ttl[key]:
                    value = self._cache.pop(key, None)
                    self._ttl.pop(key, None)
                    if value:
                        self._total_size_bytes -= self._estimate_size(value)
                    return None

            return self._cache[key]
    
    async def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache"""
        async with self._lock:
            # Remover valor antigo se existir
            if key in self._cache:
                old_value = self._cache[key]
                self._total_size_bytes -= self._estimate_size(old_value)
            
            self._cache[key] = value
            self._total_size_bytes += self._estimate_size(value)

            if ttl:
                import time
                self._ttl[key] = time.time() + ttl

            return True
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        async with self._lock:
            if key in self._cache:
                value = self._cache.pop(key, None)
                self._ttl.pop(key, None)
                if value:
                    self._total_size_bytes -= self._estimate_size(value)
            return True
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        async with self._lock:
            return key in self._cache
    
    async def clear(self) -> bool:
        """Clear all cache"""
        async with self._lock:
            self._cache.clear()
            self._ttl.clear()
            self._total_size_bytes = 0
            return True
    
    def get_memory_mb(self) -> float:
        """Retornar memória usada em MB"""
        return self._total_size_bytes / (1024 * 1024)


class RedisCache(CacheBackend):
    """Redis cache backend"""
    
    def __init__(self):
        self._redis = None
        self._enabled = settings.REDIS_ENABLED
        
        if self._enabled:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except ImportError:
                self._enabled = False
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self._enabled or not self._redis:
            return None
        
        try:
            value = await self._redis.get(key)
            if value is None:
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception:
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache"""
        if not self._enabled or not self._redis:
            return False
        
        try:
            # Serialize to JSON if needed
            if not isinstance(value, (str, int, float, bool)):
                value = json.dumps(value)
            
            if ttl:
                await self._redis.setex(key, ttl, value)
            else:
                await self._redis.set(key, value)
            
            return True
        except Exception:
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not self._enabled or not self._redis:
            return False
        
        try:
            await self._redis.delete(key)
            return True
        except Exception:
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self._enabled or not self._redis:
            return False
        
        try:
            return await self._redis.exists(key) > 0
        except Exception:
            return False
    
    async def clear(self) -> bool:
        """Clear all cache"""
        if not self._enabled or not self._redis:
            return False
        
        try:
            await self._redis.flushdb()
            return True
        except Exception:
            return False


# Global cache instance
_cache_backend: Optional[CacheBackend] = None


def get_cache() -> CacheBackend:
    """Get cache backend instance"""
    global _cache_backend
    
    if _cache_backend is None:
        if settings.REDIS_ENABLED:
            _cache_backend = RedisCache()
        else:
            _cache_backend = InMemoryCache()
    
    return _cache_backend


async def cache_get(key: str) -> Optional[Any]:
    """Get value from cache with performance tracking"""
    cache = get_cache()
    result = await cache.get(key)
    
    # Registrar cache hit/miss no performance monitor
    try:
        from services.performance_monitor import performance_monitor
        memory_mb = 0.0
        if isinstance(cache, InMemoryCache):
            memory_mb = cache.get_memory_mb()
        if result is not None:
            performance_monitor.record_cache(hit=True, memory_mb=memory_mb)
        else:
            performance_monitor.record_cache(hit=False, memory_mb=memory_mb)
    except Exception:
        pass
    
    return result


async def cache_set(key: str, value: Any, ttl: int = None) -> bool:
    """Set value in cache"""
    cache = get_cache()
    if ttl is None:
        ttl = settings.REDIS_CACHE_TTL
    
    result = await cache.set(key, value, ttl)
    
    # Opcional: registrar cache set (não é hit nem miss, apenas operação)
    # Mas pode ser útil para debugging
    
    return result


async def cache_delete(key: str) -> bool:
    """Delete value from cache"""
    cache = get_cache()
    return await cache.delete(key)


async def cache_exists(key: str) -> bool:
    """Check if key exists in cache"""
    cache = get_cache()
    return await cache.exists(key)


async def cache_clear() -> bool:
    """Clear all cache"""
    cache = get_cache()
    return await cache.clear()
