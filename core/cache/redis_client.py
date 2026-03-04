"""
Redis Client Centralizado
Gerencia conexões Redis com connection pooling e fallback para memória.
"""

import json
import pickle
from typing import Optional, Any, Union
from datetime import timedelta
from functools import lru_cache

from loguru import logger
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import RedisError, ConnectionError

from core.config import settings


class RedisManager:
    """Gerenciador centralizado de conexões Redis"""
    
    _instance: Optional['RedisManager'] = None
    _pool: Optional[ConnectionPool] = None
    _client: Optional[Redis] = None
    _enabled: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self) -> bool:
        """Inicializa conexão Redis
        
        Returns:
            bool: True se conectado com sucesso
        """
        if not settings.REDIS_ENABLED:
            logger.info("[REDIS] Desabilitado nas configurações")
            return False
        
        try:
            # Se REDIS_URL está definida (Railway), usar diretamente
            if settings.REDIS_URL and settings.REDIS_URL.startswith('redis://'):
                self._pool = ConnectionPool.from_url(
                    settings.REDIS_URL,
                    max_connections=50,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    decode_responses=False  # Manter bytes para pickle
                )
                logger.info(f"[REDIS] Usando REDIS_URL do Railway/Environment")
            else:
                # Fallback para configurações individuais
                self._pool = ConnectionPool(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD,
                    max_connections=50,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    decode_responses=False  # Manter bytes para pickle
                )
            
            self._client = Redis(connection_pool=self._pool)
            
            # Testar conexão
            await self._client.ping()
            self._enabled = True
            
            logger.info(f"[REDIS] Conectado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"[REDIS] Falha na conexão: {e}")
            self._enabled = False
            return False
    
    async def close(self):
        """Fecha conexões Redis"""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
        self._enabled = False
        logger.info("[REDIS] Conexões fechadas")
    
    @property
    def is_connected(self) -> bool:
        """Verifica se está conectado"""
        return self._enabled and self._client is not None
    
    @property
    def client(self) -> Optional[Redis]:
        """Retorna cliente Redis ou None"""
        return self._client if self._enabled else None
    
    # Métodos de utilidade com fallback automático
    
    async def set_json(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """Armazena valor como JSON"""
        if not self.is_connected:
            return False
        
        try:
            data = json.dumps(value, default=str).encode('utf-8')
            if ttl:
                await self._client.setex(key, ttl, data)
            else:
                await self._client.set(key, data)
            return True
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao set JSON: {e}")
            return False
    
    async def get_json(self, key: str) -> Optional[Any]:
        """Recupera valor como JSON"""
        if not self.is_connected:
            return None
        
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data.decode('utf-8'))
            return None
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao get JSON: {e}")
            return None
    
    async def set_pickle(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """Armazena valor como pickle (para objetos complexos)"""
        if not self.is_connected:
            return False
        
        try:
            data = pickle.dumps(value)
            if ttl:
                await self._client.setex(key, ttl, data)
            else:
                await self._client.set(key, data)
            return True
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao set pickle: {e}")
            return False
    
    async def get_pickle(self, key: str) -> Optional[Any]:
        """Recupera valor como pickle"""
        if not self.is_connected:
            return None
        
        try:
            data = await self._client.get(key)
            if data:
                return pickle.loads(data)
            return None
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao get pickle: {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """Deleta chave"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.delete(key)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao delete: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Verifica se chave existe"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.exists(key)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao exists: {e}")
            return False
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Define TTL em segundos"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.expire(key, seconds)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao expire: {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Retorna TTL restante em segundos (-1 = sem TTL, -2 = não existe)"""
        if not self.is_connected:
            return -2
        
        try:
            return await self._client.ttl(key)
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao ttl: {e}")
            return -2
    
    # Hash operations (para sessões e dados estruturados)
    
    async def hset(self, name: str, key: str, value: Any) -> bool:
        """Set hash field"""
        if not self.is_connected:
            return False
        
        try:
            data = json.dumps(value, default=str).encode('utf-8')
            await self._client.hset(name, key, data)
            return True
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao hset: {e}")
            return False
    
    async def hget(self, name: str, key: str) -> Optional[Any]:
        """Get hash field"""
        if not self.is_connected:
            return None
        
        try:
            data = await self._client.hget(name, key)
            if data:
                return json.loads(data.decode('utf-8'))
            return None
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao hget: {e}")
            return None
    
    async def hgetall(self, name: str) -> dict:
        """Get all hash fields"""
        if not self.is_connected:
            return {}
        
        try:
            data = await self._client.hgetall(name)
            result = {}
            for k, v in data.items():
                key = k.decode('utf-8')
                try:
                    result[key] = json.loads(v.decode('utf-8'))
                except:
                    result[key] = v.decode('utf-8')
            return result
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao hgetall: {e}")
            return {}
    
    async def hdel(self, name: str, key: str) -> bool:
        """Delete hash field"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.hdel(name, key)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao hdel: {e}")
            return False
    
    async def hkeys(self, name: str) -> list:
        """Get all hash keys"""
        if not self.is_connected:
            return []
        
        try:
            keys = await self._client.hkeys(name)
            return [k.decode('utf-8') for k in keys]
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao hkeys: {e}")
            return []
    
    # Set operations (para blacklists)
    
    async def sadd(self, name: str, member: str) -> bool:
        """Add member to set"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.sadd(name, member)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao sadd: {e}")
            return False
    
    async def sismember(self, name: str, member: str) -> bool:
        """Check if member is in set"""
        if not self.is_connected:
            return False
        
        try:
            return await self._client.sismember(name, member)
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao sismember: {e}")
            return False
    
    async def srem(self, name: str, member: str) -> bool:
        """Remove member from set"""
        if not self.is_connected:
            return False
        
        try:
            result = await self._client.srem(name, member)
            return result > 0
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao srem: {e}")
            return False
    
    async def smembers(self, name: str) -> set:
        """Get all set members"""
        if not self.is_connected:
            return set()
        
        try:
            members = await self._client.smembers(name)
            return {m.decode('utf-8') for m in members}
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao smembers: {e}")
            return set()
    
    # Stream operations (para auditoria)
    
    async def xadd(self, stream: str, fields: dict, maxlen: int = 10000) -> Optional[str]:
        """Add entry to stream (para audit logs)"""
        if not self.is_connected:
            return None
        
        try:
            # Converter valores para bytes
            data = {k: json.dumps(v, default=str).encode('utf-8') 
                    if not isinstance(v, (str, bytes)) else v 
                    for k, v in fields.items()}
            
            msg_id = await self._client.xadd(stream, data, maxlen=maxlen)
            return msg_id.decode('utf-8') if msg_id else None
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao xadd: {e}")
            return None
    
    async def xrevrange(
        self, 
        stream: str, 
        count: int = 100, 
        start: str = '+', 
        stop: str = '-'
    ) -> list:
        """Get entries from stream (mais recentes primeiro)"""
        if not self.is_connected:
            return []
        
        try:
            entries = await self._client.xrevrange(stream, start, stop, count=count)
            result = []
            for msg_id, fields in entries:
                entry = {'id': msg_id.decode('utf-8')}
                for k, v in fields.items():
                    key = k.decode('utf-8')
                    try:
                        entry[key] = json.loads(v.decode('utf-8'))
                    except:
                        entry[key] = v.decode('utf-8')
                result.append(entry)
            return result
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao xrevrange: {e}")
            return []
    
    async def xlen(self, stream: str) -> int:
        """Get stream length"""
        if not self.is_connected:
            return 0
        
        try:
            return await self._client.xlen(stream)
        except RedisError as e:
            logger.warning(f"[REDIS] Erro ao xlen: {e}")
            return 0


# Instância global
redis_manager = RedisManager()


async def initialize_redis() -> bool:
    """Inicializa Redis globalmente"""
    return await redis_manager.initialize()


async def close_redis():
    """Fecha conexões Redis globalmente"""
    await redis_manager.close()


# Key generators para namespaces
class KeyGenerator:
    """Gerador de chaves com namespaces"""
    
    PREFIX = "autotrade"
    
    @classmethod
    def session(cls, token: str) -> str:
        return f"{cls.PREFIX}:session:{token}"
    
    @classmethod
    def user_sessions(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:user_sessions:{user_id}"
    
    @classmethod
    def token_blacklist(cls) -> str:
        return f"{cls.PREFIX}:token_blacklist"
    
    @classmethod
    def csrf_token(cls, token: str) -> str:
        return f"{cls.PREFIX}:csrf:{token}"
    
    @classmethod
    def api_key(cls, key_id: str) -> str:
        return f"{cls.PREFIX}:api_key:{key_id}"
    
    @classmethod
    def audit_stream(cls) -> str:
        return f"{cls.PREFIX}:audit"
    
    @classmethod
    def brute_force(cls, identifier: str) -> str:
        return f"{cls.PREFIX}:brute_force:{identifier}"
    
    @classmethod
    def vip_cache(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:vip:{user_id}"


__all__ = [
    'RedisManager',
    'redis_manager',
    'initialize_redis',
    'close_redis',
    'KeyGenerator'
]
