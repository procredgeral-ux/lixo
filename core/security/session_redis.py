"""
Session Manager com suporte a Redis
Gerencia sessões JWT com persistência em Redis e fallback para memória.
"""

import time
import hashlib
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

from loguru import logger

from core.cache.redis_client import redis_manager, KeyGenerator


@dataclass
class SessionData:
    """Dados da sessão"""
    user_id: str
    token: str
    refresh_token: str
    ip_address: str
    user_agent: str
    created_at: float
    last_activity: float
    expires_at: float
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SessionData':
        return cls(**data)
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def time_remaining(self) -> int:
        """Retorna segundos restantes da sessão"""
        remaining = int(self.expires_at - time.time())
        return max(0, remaining)


class HybridSessionManager:
    """
    Gerenciador de sessões híbrido (Redis + Memória)
    
    Prioridade:
    1. Redis (persistente, compartilhado entre instâncias)
    2. Memória local (fallback quando Redis indisponível)
    """
    
    def __init__(self):
        self._memory_sessions: Dict[str, SessionData] = {}
        self._memory_user_sessions: Dict[str, set] = {}
        self._session_timeout = 3600  # 1 hora
        self._refresh_rotation = True
        
        # Métricas
        self._redis_hits = 0
        self._memory_hits = 0
        self._misses = 0
    
    def _hash_token(self, token: str) -> str:
        """Cria hash do token para usar como chave"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    async def create_session(
        self,
        user_id: str,
        token: str,
        refresh_token: str,
        ip_address: str,
        user_agent: str
    ) -> SessionData:
        """Cria nova sessão em Redis e/ou memória"""
        
        now = time.time()
        expires_at = now + self._session_timeout
        
        session = SessionData(
            user_id=user_id,
            token=token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=now,
            last_activity=now,
            expires_at=expires_at
        )
        
        token_hash = self._hash_token(token)
        
        # Tentar Redis primeiro
        if redis_manager.is_connected:
            try:
                # Armazenar sessão
                session_key = KeyGenerator.session(token_hash)
                await redis_manager.set_json(
                    session_key, 
                    session.to_dict(),
                    ttl=self._session_timeout
                )
                
                # Adicionar ao índice de sessões do usuário
                user_key = KeyGenerator.user_sessions(user_id)
                await redis_manager.hset(user_key, token_hash, {
                    'created_at': now,
                    'ip': ip_address,
                    'expires_at': expires_at
                })
                # Definir TTL no índice também
                await redis_manager.expire(user_key, self._session_timeout)
                
                logger.debug(f"[SESSION] Criada em Redis: {token_hash[:8]}...")
                return session
                
            except Exception as e:
                logger.warning(f"[SESSION] Falha no Redis, usando memória: {e}")
        
        # Fallback para memória
        self._memory_sessions[token_hash] = session
        
        if user_id not in self._memory_user_sessions:
            self._memory_user_sessions[user_id] = set()
        self._memory_user_sessions[user_id].add(token_hash)
        
        logger.debug(f"[SESSION] Criada em memória: {token_hash[:8]}...")
        return session
    
    async def get_session(self, token: str) -> Optional[SessionData]:
        """Recupera sessão do Redis ou memória"""
        
        token_hash = self._hash_token(token)
        
        # Tentar Redis primeiro
        if redis_manager.is_connected:
            try:
                session_key = KeyGenerator.session(token_hash)
                data = await redis_manager.get_json(session_key)
                
                if data:
                    session = SessionData.from_dict(data)
                    
                    # Verificar expiração
                    if session.is_expired():
                        await self._delete_from_redis(token_hash, session.user_id)
                        self._misses += 1
                        return None
                    
                    # Atualizar last_activity no Redis
                    session.last_activity = time.time()
                    await redis_manager.set_json(
                        session_key,
                        session.to_dict(),
                        ttl=self._session_timeout
                    )
                    
                    self._redis_hits += 1
                    return session
                    
            except Exception as e:
                logger.warning(f"[SESSION] Erro Redis, tentando memória: {e}")
        
        # Fallback para memória
        session = self._memory_sessions.get(token_hash)
        
        if session:
            if session.is_expired():
                self._delete_from_memory(token_hash, session.user_id)
                self._misses += 1
                return None
            
            session.last_activity = time.time()
            self._memory_hits += 1
            return session
        
        self._misses += 1
        return None
    
    async def revoke_session(self, token: str) -> bool:
        """Revoga sessão (deleta de ambos os storages)"""
        
        token_hash = self._hash_token(token)
        
        # Tentar obter user_id antes de deletar
        session = await self.get_session(token)
        user_id = session.user_id if session else None
        
        deleted = False
        
        # Deletar do Redis
        if redis_manager.is_connected:
            try:
                if await self._delete_from_redis(token_hash, user_id):
                    deleted = True
            except Exception as e:
                logger.warning(f"[SESSION] Erro ao revogar no Redis: {e}")
        
        # Deletar da memória
        if self._delete_from_memory(token_hash, user_id):
            deleted = True
        
        if deleted:
            logger.info(f"[SESSION] Revogada: {token_hash[:8]}...")
        
        return deleted
    
    async def revoke_all_sessions(self, user_id: str) -> int:
        """Revoga todas as sessões de um usuário"""
        
        count = 0
        
        # Deletar do Redis
        if redis_manager.is_connected:
            try:
                user_key = KeyGenerator.user_sessions(user_id)
                sessions = await redis_manager.hgetall(user_key)
                
                for token_hash in sessions.keys():
                    await self._delete_from_redis(token_hash, user_id)
                    count += 1
                
                # Deletar índice
                await redis_manager.delete(user_key)
                
            except Exception as e:
                logger.warning(f"[SESSION] Erro ao revogar todas no Redis: {e}")
        
        # Deletar da memória
        if user_id in self._memory_user_sessions:
            for token_hash in self._memory_user_sessions[user_id]:
                if token_hash in self._memory_sessions:
                    del self._memory_sessions[token_hash]
                    count += 1
            del self._memory_user_sessions[user_id]
        
        logger.info(f"[SESSION] Revogadas {count} sessões do usuário {user_id}")
        return count
    
    async def blacklist_token(self, token: str, reason: str = "logout") -> bool:
        """Adiciona token à blacklist (para revoke imediato)"""
        
        token_hash = self._hash_token(token)
        
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                await redis_manager.sadd(blacklist_key, token_hash)
                # TTL de 7 dias para tokens na blacklist
                await redis_manager.expire(blacklist_key, 7 * 24 * 3600)
                
                logger.info(f"[SESSION] Token blacklisted: {token_hash[:8]}...")
                return True
            except Exception as e:
                logger.warning(f"[SESSION] Erro ao blacklist no Redis: {e}")
        
        # Fallback: deletar da memória
        session = self._memory_sessions.get(token_hash)
        if session:
            self._delete_from_memory(token_hash, session.user_id)
            logger.info(f"[SESSION] Token removido da memória: {token_hash[:8]}...")
            return True
        
        return False
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """Verifica se token está na blacklist"""
        
        token_hash = self._hash_token(token)
        
        if redis_manager.is_connected:
            try:
                blacklist_key = KeyGenerator.token_blacklist()
                return await redis_manager.sismember(blacklist_key, token_hash)
            except Exception as e:
                logger.warning(f"[SESSION] Erro ao verificar blacklist no Redis: {e}")
        
        # Na memória, se não existe na sessão, considera-se blacklisted
        return token_hash not in self._memory_sessions
    
    async def rotate_refresh_token(
        self,
        old_refresh_token: str,
        new_refresh_token: str
    ) -> bool:
        """Rotaciona refresh token"""
        
        # Encontrar sessão pelo refresh token antigo
        session = None
        token_hash = None
        
        # Procurar na memória
        for th, sess in self._memory_sessions.items():
            if sess.refresh_token == old_refresh_token:
                session = sess
                token_hash = th
                break
        
        # Se não achou na memória, procurar no Redis
        if not session and redis_manager.is_connected:
            # Isso é ineficiente, mas necessário sem índice de refresh tokens
            # Em produção, considere um índice separado
            pass
        
        if session:
            session.refresh_token = new_refresh_token
            session.last_activity = time.time()
            
            # Atualizar no Redis
            if redis_manager.is_connected:
                try:
                    session_key = KeyGenerator.session(token_hash)
                    await redis_manager.set_json(
                        session_key,
                        session.to_dict(),
                        ttl=self._session_timeout
                    )
                except Exception as e:
                    logger.warning(f"[SESSION] Erro ao rotacionar no Redis: {e}")
            
            # Atualizar na memória
            self._memory_sessions[token_hash] = session
            
            logger.info(f"[SESSION] Refresh token rotacionado: {token_hash[:8]}...")
            return True
        
        return False
    
    async def get_active_sessions(self, user_id: str) -> List[dict]:
        """Retorna todas as sessões ativas de um usuário"""
        
        sessions = []
        now = time.time()
        
        # Buscar no Redis
        if redis_manager.is_connected:
            try:
                user_key = KeyGenerator.user_sessions(user_id)
                session_meta = await redis_manager.hgetall(user_key)
                
                for token_hash, meta in session_meta.items():
                    if isinstance(meta, dict):
                        expires_at = meta.get('expires_at', 0)
                        if expires_at > now:
                            sessions.append({
                                'token_hash': token_hash[:16] + '...',
                                'created_at': datetime.fromtimestamp(
                                    meta.get('created_at', 0)
                                ).isoformat(),
                                'ip_address': meta.get('ip', 'unknown'),
                                'expires_in': int(expires_at - now)
                            })
                        else:
                            # Limpar sessão expirada do índice
                            await redis_manager.hdel(user_key, token_hash)
                            
            except Exception as e:
                logger.warning(f"[SESSION] Erro ao listar no Redis: {e}")
        
        # Buscar na memória
        if user_id in self._memory_user_sessions:
            for token_hash in self._memory_user_sessions[user_id]:
                session = self._memory_sessions.get(token_hash)
                if session and not session.is_expired():
                    sessions.append({
                        'token_hash': token_hash[:16] + '...',
                        'created_at': datetime.fromtimestamp(
                            session.created_at
                        ).isoformat(),
                        'ip_address': session.ip_address,
                        'expires_in': session.time_remaining(),
                        'source': 'memory'
                    })
        
        return sessions
    
    async def cleanup_expired_sessions(self) -> int:
        """Limpa sessões expiradas de ambos os storages"""
        
        cleaned = 0
        now = time.time()
        
        # Limpar memória
        expired_tokens = []
        for token_hash, session in self._memory_sessions.items():
            if session.is_expired():
                expired_tokens.append((token_hash, session.user_id))
        
        for token_hash, user_id in expired_tokens:
            self._delete_from_memory(token_hash, user_id)
            cleaned += 1
        
        # Limpar Redis (TTL automático faz isso, mas podemos forçar)
        # Sessões expiradas são removidas automaticamente pelo TTL
        
        if cleaned > 0:
            logger.info(f"[SESSION] {cleaned} sessões expiradas removidas da memória")
        
        return cleaned
    
    def get_statistics(self) -> dict:
        """Retorna estatísticas do gerenciador"""
        return {
            'redis_hits': self._redis_hits,
            'memory_hits': self._memory_hits,
            'misses': self._misses,
            'memory_sessions': len(self._memory_sessions),
            'redis_connected': redis_manager.is_connected
        }
    
    # Métodos auxiliares privados
    
    async def _delete_from_redis(self, token_hash: str, user_id: Optional[str]) -> bool:
        """Deleta sessão do Redis"""
        if not redis_manager.is_connected:
            return False
        
        try:
            session_key = KeyGenerator.session(token_hash)
            deleted = await redis_manager.delete(session_key)
            
            # Remover do índice do usuário
            if user_id:
                user_key = KeyGenerator.user_sessions(user_id)
                await redis_manager.hdel(user_key, token_hash)
            
            return deleted
        except Exception as e:
            logger.warning(f"[SESSION] Erro ao deletar do Redis: {e}")
            return False
    
    def _delete_from_memory(self, token_hash: str, user_id: Optional[str]) -> bool:
        """Deleta sessão da memória"""
        if token_hash not in self._memory_sessions:
            return False
        
        deleted_session = self._memory_sessions.pop(token_hash, None)
        
        if user_id and user_id in self._memory_user_sessions:
            self._memory_user_sessions[user_id].discard(token_hash)
            if not self._memory_user_sessions[user_id]:
                del self._memory_user_sessions[user_id]
        elif deleted_session:
            # Tentar remover pelo user_id da sessão
            uid = deleted_session.user_id
            if uid in self._memory_user_sessions:
                self._memory_user_sessions[uid].discard(token_hash)
        
        return True


# Instância global
session_manager = HybridSessionManager()


# Funções de conveniência para compatibilidade
async def create_session(
    user_id: str,
    token: str,
    refresh_token: str,
    ip_address: str,
    user_agent: str
) -> dict:
    """Cria nova sessão"""
    session = await session_manager.create_session(
        user_id, token, refresh_token, ip_address, user_agent
    )
    return session.to_dict()


async def get_session(token: str) -> Optional[dict]:
    """Recupera sessão"""
    session = await session_manager.get_session(token)
    return session.to_dict() if session else None


async def revoke_session(token: str) -> bool:
    """Revoga sessão"""
    return await session_manager.revoke_session(token)


async def revoke_all_sessions(user_id: str) -> int:
    """Revoga todas as sessões do usuário"""
    return await session_manager.revoke_all_sessions(user_id)


async def blacklist_token(token: str, reason: str = "logout") -> bool:
    """Adiciona token à blacklist"""
    return await session_manager.blacklist_token(token, reason)


async def is_token_blacklisted(token: str) -> bool:
    """Verifica se token está na blacklist"""
    return await session_manager.is_token_blacklisted(token)


async def get_active_sessions(user_id: str) -> List[dict]:
    """Retorna sessões ativas do usuário"""
    return await session_manager.get_active_sessions(user_id)


__all__ = [
    'HybridSessionManager',
    'session_manager',
    'SessionData',
    'create_session',
    'get_session',
    'revoke_session',
    'revoke_all_sessions',
    'blacklist_token',
    'is_token_blacklisted',
    'get_active_sessions'
]
