"""
L1 Cache In-Process - Cache local em memória para acesso ultra-rápido
Camada antes do Redis, elimina round-trip de rede para dados mais quentes
"""
from typing import Any, Optional, Dict
from cachetools import TTLCache
from loguru import logger
import asyncio
import time


class L1InProcessCache:
    """
    Cache L1 em memória local com TTL curto e proteção contra cache stampede
    
    Use cases:
    - Configurações de autotrade (consultadas múltiplas vezes por segundo)
    - Dados de usuário logado
    - Sinais recentes do próprio usuário
    
    Características:
    - ~100x mais rápido que Redis (acesso direto em RAM)
    - TTL curto (10s padrão) para garantir frescor dos dados
    - Thread-safe com asyncio.Lock para operações concorrentes
    - Cache stampede protection com locks por chave e cleanup explícito
    """
    
    def __init__(
        self,
        maxsize: int = 500,
        ttl: int = 10,  # Segundos
        name: str = "l1_cache"
    ):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._ttl = ttl  # Salvar TTL para uso no método set()
        self._name = name
        self._lock = asyncio.Lock()
        # Dict normal com cleanup explícito (WeakValueDictionary tem problemas com asyncio.Lock)
        self._fetch_locks: Dict[str, asyncio.Lock] = {}
        self._stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0
        }
    
    def _get_fetch_lock(self, key: str) -> asyncio.Lock:
        """Obter ou criar lock para uma chave específica"""
        if key not in self._fetch_locks:
            self._fetch_locks[key] = asyncio.Lock()
        return self._fetch_locks[key]
    
    def _cleanup_fetch_lock(self, key: str):
        """Limpar lock de fetch se não estiver mais em uso"""
        if key in self._fetch_locks:
            lock = self._fetch_locks[key]
            # Só remove se o lock não está locked e não há waiters
            if not lock.locked() and not lock._waiters:  # _waiters é asyncio.Queue ou None
                del self._fetch_locks[key]
                logger.debug(f"[L1 CACHE] Lock limpo para {key}")
    
    async def get(self, key: str) -> Optional[Any]:
        """Obter valor do cache L1 com TTL check"""
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if expiry is None or time.time() < expiry:
                    self._stats['hits'] += 1
                    # Log silenciado
                    # logger.info(f"[L1 CACHE HIT] {key} (hits: {self._stats['hits']}, misses: {self._stats['misses']})")
                    # Report to performance monitor
                    try:
                        from services.performance_monitor import performance_monitor
                        performance_monitor.record_cache(hit=True)
                    except Exception:
                        pass
                    return value
                else:
                    # Expirado, remover
                    del self._cache[key]
                    self._stats['misses'] += 1
                    logger.debug(f"[L1 CACHE EXPIRED] {key}")
            else:
                self._stats['misses'] += 1
                # Log silenciado
                # logger.info(f"[L1 CACHE MISS] {key} (hits: {self._stats['hits']}, misses: {self._stats['misses']})")
            # Report miss to performance monitor
            try:
                from services.performance_monitor import performance_monitor
                performance_monitor.record_cache(hit=False)
            except Exception:
                pass
            return None
    
    async def get_with_fetch(
        self,
        key: str,
        fetch_func,
        l2_cache=None,
        l2_ttl: int = 300
    ) -> Any:
        """
        Padrão de cache multi-camada com stampede protection
        
        L1 (in-process) → L2 (Redis) → DB
        
        Importante: O double-check verifica SÓ O L1 (memória local), sem I/O no lock
        """
        # Tentar L1 primeiro (sem lock - rápido)
        async with self._lock:
            value = self._cache.get(key)
        
        if value is not None:
            self._stats['hits'] += 1
            logger.debug(f"[L1 CACHE] Hit: {key}")
            # Report to performance monitor
            try:
                from services.performance_monitor import performance_monitor
                performance_monitor.record_cache(hit=True)
            except Exception:
                pass
            return value
        
        # Cache stampede protection: lock por chave
        fetch_lock = self._get_fetch_lock(key)
        async with fetch_lock:
            # DOUBLE-CHECK: Verificar SÓ O L1 (sem I/O!)
            # Não chama self.get() aqui porque self.get() também verifica Redis
            async with self._lock:
                value = self._cache.get(key)
            
            if value is not None:
                self._stats['hits'] += 1  # Hit no double-check!
                logger.debug(f"[L1 CACHE] Double-check HIT: {key} | total_hits={self._stats['hits']}")
                # Report to performance monitor
                try:
                    from services.performance_monitor import performance_monitor
                    performance_monitor.record_cache(hit=True)
                except Exception:
                    pass
                return value
            else:
                logger.debug(f"[L1 CACHE] Double-check MISS: {key} | cache_size={len(self._cache)}")
            
            # Agora sim: vamos fazer fetch, então conta como miss
            self._stats['misses'] += 1
            # Report miss to performance monitor
            try:
                from services.performance_monitor import performance_monitor
                performance_monitor.record_cache(hit=False)
            except Exception:
                pass
            
            # FORA DO LOCK de stampede: Tentar L2 (Redis)
            if l2_cache:
                value = await l2_cache.get(key)
                if value is not None:
                    # Popular L1
                    async with self._lock:
                        self._cache[key] = value
                    return value
            
            # FORA DO LOCK de stampede: Fetch do DB
            value = await fetch_func()
            
            if value is not None:
                # Popular L1
                async with self._lock:
                    self._cache[key] = value
                
                # Popular L2 (sempre fora do lock principal)
                if l2_cache:
                    await l2_cache.set(key, value, ttl=l2_ttl)
            
            return value
        
        # Limpar lock se não estiver mais em uso (após sair do async with)
        self._cleanup_fetch_lock(key)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Definir valor no cache L1"""
        use_ttl = ttl if ttl is not None else self._ttl
        async with self._lock:
            expiry = time.time() + use_ttl if use_ttl else None
            self._cache[key] = (value, expiry)
        
        self._stats['sets'] += 1
        logger.info(f"[L1 CACHE SET] {key} (ttl={use_ttl}s, total_cached={len(self._cache)})")
    
    async def delete(self, key: str):
        """Remover valor do cache L1"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
        
        self._stats['deletes'] += 1
        logger.debug(f"[L1 CACHE] Delete: {key}")
    
    async def clear(self):
        """Limpar todo o cache L1"""
        async with self._lock:
            self._cache.clear()
        
        logger.info(f"[L1 CACHE] Cache limpo: {self._name}")
    
    async def invalidate(self, key: str):
        """Invalidar chave específica do cache L1 (essencial para updates imediatos)"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
        
        logger.debug(f"[L1 CACHE] Invalidado: {key}")
    
    async def invalidate_pattern(self, pattern: str):
        """Invalidar múltiplas chaves por padrão (ex: 'config:*')"""
        async with self._lock:
            # Usar list() para criar cópia e evitar RuntimeError durante iteração
            keys_to_delete = [k for k in list(self._cache.keys()) if pattern in k or k.startswith(pattern.rstrip('*'))]
            for key in keys_to_delete:
                self._cache.pop(key, None)  # pop é mais seguro que del
        
        logger.debug(f"[L1 CACHE] Invalidado padrão '{pattern}': {len(keys_to_delete)} chaves")
    
    def get_stats(self) -> Dict[str, Any]:
        """Obter estatísticas do cache"""
        total = self._stats['hits'] + self._stats['misses']
        hit_rate = self._stats['hits'] / total if total > 0 else 0
        
        return {
            **self._stats,
            'hit_rate': hit_rate,
            'size': len(self._cache),
            'maxsize': self._cache.maxsize,
            'ttl': self._cache.ttl,
            'name': self._name
        }
    
    def __contains__(self, key: str) -> bool:
        """Verificar se chave existe no cache (síncrono para performance)"""
        return key in self._cache
    
    def __len__(self) -> int:
        """Retornar tamanho do cache"""
        return len(self._cache)


# Instâncias globais otimizadas para diferentes use cases
autotrade_config_l1_cache = L1InProcessCache(
    maxsize=200,
    ttl=300,  # 5 minutos para configurações (aumentado de 60s)
    name="autotrade_config"
)

user_data_l1_cache = L1InProcessCache(
    maxsize=100,
    ttl=60,  # 1 minuto para dados de usuário
    name="user_data"
)

recent_signals_l1_cache = L1InProcessCache(
    maxsize=500,
    ttl=5,   # 5 segundos para sinais recentes
    name="recent_signals"
)


# Helper functions para uso conveniente
async def get_with_l1_l2_cache(
    key: str,
    l1_cache: L1InProcessCache,
    l2_fetch_func,
    l2_cache=None,
    l2_ttl: int = 300
) -> Any:
    """
    Padrão de cache multi-camada: L1 (in-process) → L2 (Redis) → DB
    
    Args:
        key: Chave do cache
        l1_cache: Cache L1 in-process
        l2_fetch_func: Função async para buscar do L2 (Redis) ou DB
        l2_cache: Cache L2 (Redis) opcional
        l2_ttl: TTL para L2
    
    Returns:
        Valor do cache ou resultado da função
    """
    # Tentar L1 primeiro (memória local - ~100ns)
    value = await l1_cache.get(key)
    if value is not None:
        return value
    
    # Tentar L2 (Redis - ~1ms)
    if l2_cache:
        value = await l2_cache.get(key)
        if value is not None:
            # Popular L1 para próximas chamadas
            await l1_cache.set(key, value)
            return value
    
    # Fallback para função de fetch (DB - ~50ms)
    value = await l2_fetch_func()
    
    if value is not None:
        # Popular ambos os caches
        await l1_cache.set(key, value)
        if l2_cache:
            await l2_cache.set(key, value, ttl=l2_ttl)
    
    return value
