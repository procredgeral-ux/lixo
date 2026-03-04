"""
Token Blacklist com Redis
Gerencia tokens revogados com persistência em Redis.
"""

import time
import hashlib
from typing import Optional, Dict, Set
from datetime import datetime

from loguru import logger

from core.cache.redis_client import redis_manager, KeyGenerator


class HybridTokenBlacklist:
    """
    Blacklist híbrida de tokens (Redis + Memória)
    
    Garante que tokens revogados permaneçam inválidos mesmo após restart.
    """
    
    def __init__(self):
        # Memória local como cache L1
        self._memory_blacklist: Dict[str, float] = {}
        self._cleanup_interval = 3600  # Limpar a cada 1 hora
        self._last_cleanup = time.time()
        
        # Métricas
        self._redis_hits = 0
        self._memory_hits = 0
        self._writes = 0
    
    def _hash_token(self, token: str) -> str:
        """Cria hash do token para armazenamento seguro"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    async def add(
        self, 
        token: str, 
        reason: str = "logout",
        expires_at: Optional[float] = None
    ) -> bool:
        """
        Adiciona token à blacklist
        
        Args:
            token: Token JWT a ser revogado
            reason: Motivo da revogação (logout, security, etc)
            expires_at: Timestamp de expiração do token (para TTL automático)
        
        Returns:
            bool: True se adicionado com sucesso
        """
        token_hash = self._hash_token(token)
        now = time.time()
        
        # Dados do token revogado
        data = {
            'token_hash': token_hash,
            'revoked_at': now,
            'reason': reason,
            'expires_at': expires_at or (now + 7 * 24 * 3600)  # 7 dias padrão
        }
        
        success = False
        
        # Tentar Redis primeiro
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                
                # Usar sorted set com timestamp de expiração como score
                await redis_manager._client.zadd(
                    blacklist_key,
                    {token_hash: data['expires_at']}
                )
                
                # Armazenar metadados em hash
                meta_key = f"{blacklist_key}:meta"
                await redis_manager.hset(meta_key, token_hash, data)
                
                # Definir TTL automático baseado na expiração do token
                ttl = int(data['expires_at'] - now)
                if ttl > 0:
                    await redis_manager.expire(meta_key, ttl)
                
                logger.info(
                    f"[BLACKLIST] Token adicionado no Redis: {token_hash[:16]}... "
                    f"(reason: {reason})"
                )
                success = True
                self._writes += 1
                
            except Exception as e:
                logger.warning(f"[BLACKLIST] Falha no Redis: {e}")
        
        # Sempre adicionar à memória (fallback ou cache L1)
        self._memory_blacklist[token_hash] = data['expires_at']
        
        if not success:
            logger.warning(
                f"[BLACKLIST] Token adicionado apenas em memória: {token_hash[:16]}..."
            )
        
        return True
    
    async def is_blacklisted(self, token: str) -> bool:
        """Verifica se token está na blacklist"""
        
        token_hash = self._hash_token(token)
        now = time.time()
        
        # Verificar memória primeiro (mais rápido)
        if token_hash in self._memory_blacklist:
            expires_at = self._memory_blacklist[token_hash]
            
            if expires_at > now:
                self._memory_hits += 1
                return True
            else:
                # Expirado, remover da memória
                del self._memory_blacklist[token_hash]
        
        # Verificar no Redis
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                
                # Verificar se existe no sorted set
                score = await redis_manager._client.zscore(blacklist_key, token_hash)
                
                if score:
                    # Verificar se não expirou
                    if score > now:
                        # Adicionar à memória para próximas verificações rápidas
                        self._memory_blacklist[token_hash] = score
                        self._redis_hits += 1
                        return True
                    else:
                        # Expirado no Redis, remover
                        await self._remove_from_redis(token_hash)
                        
            except Exception as e:
                logger.warning(f"[BLACKLIST] Erro ao verificar no Redis: {e}")
        
        return False
    
    async def remove(self, token: str) -> bool:
        """Remove token da blacklist (raramente usado, mas útil para admin)"""
        
        token_hash = self._hash_token(token)
        
        removed = False
        
        # Remover do Redis
        if redis_manager.is_connected:
            try:
                if await self._remove_from_redis(token_hash):
                    removed = True
            except Exception as e:
                logger.warning(f"[BLACKLIST] Erro ao remover do Redis: {e}")
        
        # Remover da memória
        if token_hash in self._memory_blacklist:
            del self._memory_blacklist[token_hash]
            removed = True
        
        if removed:
            logger.info(f"[BLACKLIST] Token removido: {token_hash[:16]}...")
        
        return removed
    
    async def cleanup_expired(self) -> int:
        """Limpa tokens expirados da blacklist"""
        
        now = time.time()
        cleaned = 0
        
        # Limpar memória
        expired = [
            th for th, exp in self._memory_blacklist.items() 
            if exp <= now
        ]
        for th in expired:
            del self._memory_blacklist[th]
            cleaned += 1
        
        # Limpar Redis
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                
                # Remover tokens com score <= now (expirados)
                removed = await redis_manager._client.zremrangebyscore(
                    blacklist_key, '-inf', now
                )
                
                if removed:
                    cleaned += removed
                    logger.info(f"[BLACKLIST] {removed} tokens expirados removidos do Redis")
                    
            except Exception as e:
                logger.warning(f"[BLACKLIST] Erro ao limpar Redis: {e}")
        
        self._last_cleanup = now
        return cleaned
    
    async def get_all_active(
        self, 
        limit: int = 1000,
        include_expired: bool = False
    ) -> list:
        """Retorna todos os tokens na blacklist (para admin/debug)"""
        
        tokens = []
        now = time.time()
        
        # Buscar no Redis
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                meta_key = f"{blacklist_key}:meta"
                
                # Buscar do sorted set ordenado por expiração (mais recentes primeiro)
                entries = await redis_manager._client.zrevrange(
                    blacklist_key, 0, limit - 1, withscores=True
                )
                
                for token_hash, expires_at in entries:
                    th = token_hash.decode('utf-8') if isinstance(token_hash, bytes) else token_hash
                    
                    if not include_expired and expires_at <= now:
                        continue
                    
                    # Buscar metadados
                    meta = await redis_manager.hget(meta_key, th)
                    
                    tokens.append({
                        'token_hash': th[:16] + '...',
                        'revoked_at': meta.get('revoked_at') if meta else None,
                        'reason': meta.get('reason') if meta else 'unknown',
                        'expires_at': datetime.fromtimestamp(expires_at).isoformat(),
                        'is_expired': expires_at <= now,
                        'source': 'redis'
                    })
                    
            except Exception as e:
                logger.warning(f"[BLACKLIST] Erro ao listar no Redis: {e}")
        
        # Buscar na memória
        for th, expires_at in self._memory_blacklist.items():
            if not include_expired and expires_at <= now:
                continue
            
            # Verificar se já não está na lista do Redis
            if not any(t.get('token_hash', '').startswith(th[:16]) for t in tokens):
                tokens.append({
                    'token_hash': th[:16] + '...',
                    'revoked_at': None,
                    'reason': 'memory_only',
                    'expires_at': datetime.fromtimestamp(expires_at).isoformat(),
                    'is_expired': expires_at <= now,
                    'source': 'memory'
                })
        
        return tokens[:limit]
    
    async def sync_from_redis(self) -> int:
        """Sincroniza tokens da memória com Redis (útil após restart)"""
        
        if not redis_manager.is_connected or not self._memory_blacklist:
            return 0
        
        synced = 0
        now = time.time()
        
        try:
            blacklist_key = KeyGenerator.token_blacklist()
            meta_key = f"{blacklist_key}:meta"
            
            for token_hash, expires_at in self._memory_blacklist.items():
                if expires_at > now:
                    await redis_manager._client.zadd(
                        blacklist_key,
                        {token_hash: expires_at}
                    )
                    
                    await redis_manager.hset(meta_key, token_hash, {
                        'token_hash': token_hash,
                        'revoked_at': now,
                        'reason': 'sync_from_memory',
                        'expires_at': expires_at
                    })
                    synced += 1
            
            if synced > 0:
                logger.info(f"[BLACKLIST] {synced} tokens sincronizados para o Redis")
                
        except Exception as e:
            logger.warning(f"[BLACKLIST] Erro na sincronização: {e}")
        
        return synced
    
    async def _remove_from_redis(self, token_hash: str) -> bool:
        """Remove token do Redis"""
        if not redis_manager.is_connected:
            return False
        
        try:
            blacklist_key = KeyGenerator.token_blacklist()
            meta_key = f"{blacklist_key}:meta"
            
            # Remover do sorted set
            result = await redis_manager._client.zrem(blacklist_key, token_hash)
            
            # Remover metadados
            await redis_manager.hdel(meta_key, token_hash)
            
            return result > 0
        except Exception as e:
            logger.warning(f"[BLACKLIST] Erro ao remover do Redis: {e}")
            return False
    
    def get_statistics(self) -> dict:
        """Retorna estatísticas da blacklist"""
        return {
            'redis_hits': self._redis_hits,
            'memory_hits': self._memory_hits,
            'writes': self._writes,
            'memory_entries': len(self._memory_blacklist),
            'redis_connected': redis_manager.is_connected,
            'last_cleanup': self._last_cleanup
        }


# Instância global
token_blacklist = HybridTokenBlacklist()


# Funções de conveniência
async def blacklist_token(
    token: str, 
    reason: str = "logout",
    expires_at: Optional[float] = None
) -> bool:
    """Adiciona token à blacklist"""
    return await token_blacklist.add(token, reason, expires_at)


async def is_token_blacklisted(token: str) -> bool:
    """Verifica se token está na blacklist"""
    return await token_blacklist.is_blacklisted(token)


async def remove_from_blacklist(token: str) -> bool:
    """Remove token da blacklist"""
    return await token_blacklist.remove(token)


async def cleanup_expired_tokens() -> int:
    """Limpa tokens expirados"""
    return await token_blacklist.cleanup_expired()


async def get_blacklisted_tokens(
    limit: int = 1000,
    include_expired: bool = False
) -> list:
    """Retorna tokens na blacklist"""
    return await token_blacklist.get_all_active(limit, include_expired)


__all__ = [
    'HybridTokenBlacklist',
    'token_blacklist',
    'blacklist_token',
    'is_token_blacklisted',
    'remove_from_blacklist',
    'cleanup_expired_tokens',
    'get_blacklisted_tokens'
]
