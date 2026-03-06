"""Cache system for indicator calculations using Redis"""
from typing import Any, Dict, Optional, Tuple
from functools import wraps
import time
import hashlib
import json
import threading
from loguru import logger
from services.redis_client import redis_client


class IndicatorCache:
    """Cache for indicator calculations using Redis"""

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        """
        Initialize indicator cache

        Args:
            max_size: Maximum number of cached items (Redis handles this)
            ttl: Time to live in seconds (default: 5 minutes)
        """
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0
        self._prefix = "indicator_cache:"
        self._lock = threading.RLock()
        self.cache = {}
        self.access_times = {}

    def _generate_key(self, indicator_name: str, params: Dict[str, Any], data_hash: str) -> str:
        """Generate cache key for indicator calculation"""
        # Create a unique key based on indicator name, params, and data hash
        key_data = f"{indicator_name}:{json.dumps(params, sort_keys=True)}:{data_hash}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{self._prefix}{key_hash}"
        """
        Generate cache key
        
        Args:
            indicator_name: Name of the indicator
            params: Indicator parameters
            data_hash: Hash of the input data
        
        Returns:
            str: Cache key
        """
        # Sort params for consistent key generation
        try:
            sorted_params = json.dumps(params, sort_keys=True)
        except (TypeError, ValueError):
            # Se json.dumps falhar (ex: valores NaN, inf), usar string alternativa
            sorted_params = str(sorted(params.items()))
        
        key_string = f"{indicator_name}:{sorted_params}:{data_hash}"
        return md5(key_string.encode()).hexdigest()
    
        
    def get(self, indicator_name: str, params: Dict[str, Any], data_hash: str) -> Optional[Any]:
        """
        Get cached value
        
        Args:
            indicator_name: Name of the indicator
            params: Indicator parameters
            data_hash: Hash of the input data
        
        Returns:
            Cached value or None
        """
        key = self._generate_key(indicator_name, params, data_hash)
        
        with self._lock:
            if key not in self.cache:
                self.misses += 1
                return None
            
            value, timestamp = self.cache[key]
            
            # Check if cache entry is expired
            if time.time() - timestamp > self.ttl:
                self._remove(key)
                self.misses += 1
                return None
            
            # Update access time for LRU eviction
            self.access_times[key] = time.time()
            self.hits += 1
            
            # Log silenciado para reduzir poluição
            # logger.debug(f"Cache hit for {indicator_name}: {self.hits}/{self.hits + self.misses}")
            return value
    
    def set(self, indicator_name: str, params: Dict[str, Any], data_hash: str, value: Any):
        """
        Set cached value
        
        Args:
            indicator_name: Name of the indicator
            params: Indicator parameters
            data_hash: Hash of the input data
            value: Value to cache
        """
        key = self._generate_key(indicator_name, params, data_hash)
        
        with self._lock:
            # Verificar se a chave já existe (evitar duplicação)
            if key in self.cache:
                # Atualizar valor existente
                self.cache[key] = (value, time.time())
                self.access_times[key] = time.time()
                # Log silenciado
                # logger.debug(f"Cache updated for {indicator_name}: {len(self.cache)}/{self.max_size}")
                return
            
            # Evict oldest entries se cache estiver cheio
            while len(self.cache) >= self.max_size:
                self._evict_oldest()
            
            self.cache[key] = (value, time.time())
            self.access_times[key] = time.time()
            
            # Log silenciado para reduzir poluição
            # logger.debug(f"Cache set for {indicator_name}: {len(self.cache)}/{self.max_size}")
    
    def _evict_oldest(self):
        """Evict the oldest entry from cache (LRU)"""
        if not self.access_times:
            return
        
        oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        self._remove(oldest_key)
        # Log silenciado
        # logger.debug(f"Cache evicted oldest entry: {oldest_key}")
    
    def _remove(self, key: str):
        """
        Remove entry from cache
        
        Args:
            key: Cache key
        """
        self.cache.pop(key, None)
        self.access_times.pop(key, None)
    
    def clear(self):
        """Clear all cache entries"""
        self.cache.clear()
        self.access_times.clear()
        self.hits = 0
        self.misses = 0
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dict with cache statistics
        """
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'ttl': self.ttl
        }
    
    def _cleanup_expired(self):
        """Remove expired entries from cache"""
        current_time = time.time()
        expired_keys = []
        
        with self._lock:
            for key, (value, timestamp) in self.cache.items():
                if current_time - timestamp > self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                self._remove(key)
            
            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired entries")


# Global cache instance
indicator_cache = IndicatorCache()


def hash_dataframe(df) -> str:
    """
    Generate hash for DataFrame for caching
    
    Args:
        df: DataFrame to hash
    
    Returns:
        str: Hash string
    """
    # Usar todo o DataFrame para garantir unicidade
    # Incluir nomes das colunas E índice para garantir unicidade completa
    # Converter para bytes de forma determinística
    import hashlib
    
    # Criar hash que inclui dados, nomes das colunas E índice
    h = hashlib.md5()
    
    # Adicionar nomes das colunas em ordem
    h.update(','.join(df.columns.tolist()).encode())
    
    # Adicionar índice para garantir unicidade
    h.update(df.index.to_numpy().tobytes())
    
    # Adicionar dados
    h.update(df.to_numpy().tobytes())
    
    return h.hexdigest()


def cached_indicator(indicator_name: str):
    """
    Decorator to cache indicator calculations
    
    Args:
        indicator_name: Name of the indicator
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, data, **kwargs):
            # Gerar hash que inclui dados do DataFrame E parâmetros do indicador
            data_hash = hash_dataframe(data)
            
            # Incluir parâmetros da instância do indicador no cache key
            # Isso garante que diferentes configurações do mesmo indicador
            # não compartilhem o cache
            instance_params = {}
            if hasattr(self, 'period'):
                instance_params['period'] = self.period
            if hasattr(self, 'smooth'):
                instance_params['smooth'] = self.smooth
            if hasattr(self, 'dynamic_levels'):
                instance_params['dynamic_levels'] = self.dynamic_levels
            if hasattr(self, 'use_true_levels'):
                instance_params['use_true_levels'] = self.use_true_levels
            if hasattr(self, 'swing_period'):
                instance_params['swing_period'] = self.swing_period
            if hasattr(self, 'zone_strength'):
                instance_params['zone_strength'] = self.zone_strength
            if hasattr(self, 'zone_tolerance'):
                instance_params['zone_tolerance'] = self.zone_tolerance
            if hasattr(self, 'min_zone_width'):
                instance_params['min_zone_width'] = self.min_zone_width
            if hasattr(self, 'atr_multiplier'):
                instance_params['atr_multiplier'] = self.atr_multiplier
            if hasattr(self, 'fast'):
                instance_params['fast'] = self.fast
            if hasattr(self, 'slow'):
                instance_params['slow'] = self.slow
            if hasattr(self, 'signal'):
                instance_params['signal'] = self.signal
            if hasattr(self, 'k_period'):
                instance_params['k_period'] = self.k_period
            if hasattr(self, 'd_period'):
                instance_params['d_period'] = self.d_period
            if hasattr(self, 'std_dev'):
                instance_params['std_dev'] = self.std_dev
            
            # Combinar parâmetros da instância com kwargs
            all_params = {**instance_params, **kwargs}
            
            # Check cache
            cached_value = indicator_cache.get(
                indicator_name,
                all_params,
                data_hash
            )
            
            if cached_value is not None:
                # Log silenciado
                # logger.debug(f"Cache hit for {indicator_name}")
                return cached_value
            
            # Calculate value
            result = func(self, data, **kwargs)
            
            # Cache result
            indicator_cache.set(
                indicator_name,
                all_params,
                data_hash,
                result
            )
            
            # Log silenciado
            # logger.debug(f"Cache miss for {indicator_name}, calculated and cached")
            return result
        
        return wrapper
    return decorator
