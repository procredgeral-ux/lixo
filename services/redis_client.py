"""Redis Client - Cliente assíncrono para Redis"""
import redis.asyncio as redis
from typing import Any, Optional
from loguru import logger
import json
import zlib
import base64


class RedisClient:
    """Cliente assíncrono para Redis com compressão opcional"""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.connected = False
        # Threshold para compressão: dados maiores que 1KB são comprimidos
        self.compression_threshold = 1024
        self.compression_level = 1  # Level 1 = rápido, ~60% redução

    async def connect(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        redis_url: Optional[str] = None
    ):
        """Conectar ao Redis - suporta URL completa ou componentes separados"""
        try:
            # Se redis_url for fornecido, usar diretamente (Railway style)
            if redis_url:
                self.redis = await redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                logger.info(f"✅ Redis conectado via URL: {redis_url.replace(password or '', '***') if password else redis_url}")
            else:
                # Fallback para componentes individuais
                self.redis = await redis.from_url(
                    f"redis://{host}:{port}/{db}",
                    password=password,
                    encoding="utf-8",
                    decode_responses=True
                )
                logger.info(f"✅ Redis conectado: {host}:{port}")
            
            await self.redis.ping()
            self.connected = True
            
        except Exception as e:
            logger.error(f"❌ Erro ao conectar ao Redis: {e}")
            raise

    async def disconnect(self):
        """Desconectar do Redis"""
        if self.redis:
            await self.redis.close()
            self.connected = False
            logger.info("🔌 Redis desconectado")

    async def get(self, key: str) -> Optional[str]:
        """Obter valor do Redis"""
        if not self.connected:
            return None
        try:
            return await self.redis.get(key)
        except Exception as e:
            logger.error(f"Erro ao obter chave {key}: {e}")
            return None

    async def set(self, key: str, value: str, ttl: int = 300):
        """Definir valor no Redis com TTL"""
        if not self.connected:
            return
        try:
            await self.redis.setex(key, ttl, value)
        except Exception as e:
            logger.error(f"Erro ao definir chave {key}: {e}")

    async def delete(self, key: str):
        """Deletar chave do Redis"""
        if not self.connected:
            return
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.error(f"Erro ao deletar chave {key}: {e}")

    async def exists(self, key: str) -> bool:
        """Verificar se chave existe"""
        if not self.connected:
            return False
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Erro ao verificar chave {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Any]:
        """Obter valor JSON do Redis"""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    async def set_json(self, key: str, value: Any, ttl: int = 300):
        """Definir valor JSON no Redis"""
        try:
            json_value = json.dumps(value)
            await self.set(key, json_value, ttl)
        except Exception as e:
            logger.error(f"Erro ao definir JSON {key}: {e}")

    async def get_compressed(self, key: str) -> Optional[Any]:
        """
        Obter valor comprimido do Redis
        Descomprime automaticamente se necessário
        """
        if not self.connected:
            return None
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            
            # Verificar se está comprimido (prefixo 'z:' indica zlib)
            if isinstance(value, str) and value.startswith('z:'):
                # Descomprimir
                compressed = base64.b64decode(value[2:])  # Remove 'z:' prefix
                decompressed = zlib.decompress(compressed)
                return json.loads(decompressed.decode('utf-8'))
            
            # Não comprimido, tentar JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
                
        except Exception as e:
            logger.error(f"Erro ao obter valor comprimido {key}: {e}")
            return None

    async def set_compressed(self, key: str, value: Any, ttl: int = 300):
        """
        Definir valor comprimido no Redis
        Usa compressão zlib level 1 para dados grandes (>1KB)
        """
        if not self.connected:
            return
        try:
            json_data = json.dumps(value).encode('utf-8')
            
            # Só comprimir se dados forem grandes o suficiente
            if len(json_data) > self.compression_threshold:
                # Comprimir com level 1 (rápido, boa redução)
                compressed = zlib.compress(json_data, level=self.compression_level)
                encoded = 'z:' + base64.b64encode(compressed).decode('utf-8')
                
                await self.redis.setex(key, ttl, encoded)
                
                compression_ratio = len(encoded) / len(json_data)
                logger.debug(
                    f"[REDIS] Comprimido {key}: {len(json_data)} -> {len(encoded)} bytes "
                    f"({compression_ratio:.1%})"
                )
            else:
                # Dados pequenos, não comprimir
                await self.redis.setex(key, ttl, json_data.decode('utf-8'))
                
        except Exception as e:
            logger.error(f"Erro ao definir valor comprimido {key}: {e}")

    async def clear_pattern(self, pattern: str):
        """Deletar todas as chaves que correspondem ao padrão"""
        if not self.connected:
            return
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
                logger.debug(f"🗑️ Deletadas {len(keys)} chaves: {pattern}")
        except Exception as e:
            logger.error(f"Erro ao limpar padrão {pattern}: {e}")

    async def flush_all(self):
        """Limpar todas as chaves do Redis"""
        if not self.connected:
            return
        try:
            await self.redis.flushdb()
            logger.info("🗑️ Redis limpo completamente")
        except Exception as e:
            logger.error(f"Erro ao limpar Redis: {e}")


# Instância global do cliente Redis
redis_client = RedisClient()
