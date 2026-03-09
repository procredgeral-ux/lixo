"""
Gerenciador de Fila de Notificações com Redis
Persiste notificações para evitar perda em caso de reinicialização
"""
import asyncio
import json
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from loguru import logger

from core.config import settings
from core.cache.redis_client import get_redis_client


@dataclass
class NotificationMessage:
    """Representa uma notificação na fila"""
    text: str
    chat_id: str
    priority: int = 1
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = None
    notification_type: str = "general"  # signal, trade_result, stop_loss, stop_gain, etc.
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NotificationMessage':
        return cls(**data)


class NotificationQueueManager:
    """
    Gerenciador de fila de notificações com Redis
    - Persiste notificações em Redis (fila persistente)
    - Suporta prioridades (1=alta, 2=média, 3=baixa)
    - Recupera notificações pendentes após reinicialização
    """
    
    REDIS_QUEUE_KEY = "notification_queue"
    REDIS_PROCESSING_KEY = "notification_processing"
    REDIS_FAILED_KEY = "notification_failed"
    
    def __init__(self):
        self._redis = None
        self._local_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._initialized = False
        self._restore_task: Optional[asyncio.Task] = None
    
    async def _get_redis(self):
        """Obtém conexão Redis lazy"""
        if self._redis is None:
            try:
                self._redis = await get_redis_client()
            except Exception as e:
                logger.warning(f"[NotificationQueue] Redis não disponível: {e}")
                return None
        return self._redis
    
    async def initialize(self):
        """Inicializa o gerenciador e restaura fila do Redis"""
        if self._initialized:
            return
            
        redis = await self._get_redis()
        if redis:
            # Restaurar notificações pendentes do Redis
            await self._restore_from_redis()
            logger.info("[NotificationQueue] Fila restaurada do Redis")
        else:
            logger.warning("[NotificationQueue] Usando fila em memória (sem persistência)")
        
        self._initialized = True
    
    async def _restore_from_redis(self):
        """Restaura notificações pendentes do Redis para a fila local"""
        redis = await self._get_redis()
        if not redis:
            return
            
        try:
            # Obter todas as notificações da fila Redis
            notifications = await redis.lrange(self.REDIS_QUEUE_KEY, 0, -1)
            
            for notif_data in notifications:
                try:
                    data = json.loads(notif_data)
                    msg = NotificationMessage.from_dict(data)
                    await self._local_queue.put((msg.priority, msg))
                except Exception as e:
                    logger.error(f"[NotificationQueue] Erro ao restaurar notificação: {e}")
            
            # Limpar Redis após restauração
            await redis.delete(self.REDIS_QUEUE_KEY)
            
            count = len(notifications)
            if count > 0:
                logger.info(f"[NotificationQueue] {count} notificações restauradas do Redis")
                
        except Exception as e:
            logger.error(f"[NotificationQueue] Erro ao restaurar do Redis: {e}")
    
    async def enqueue(self, message: NotificationMessage) -> bool:
        """
        Adiciona notificação à fila
        Persiste em Redis se disponível
        """
        try:
            # Adicionar à fila local
            await self._local_queue.put((message.priority, message))
            
            # Persistir em Redis
            redis = await self._get_redis()
            if redis:
                await redis.lpush(
                    self.REDIS_QUEUE_KEY,
                    json.dumps(message.to_dict())
                )
            
            return True
            
        except Exception as e:
            logger.error(f"[NotificationQueue] Erro ao enfileirar: {e}")
            return False
    
    async def dequeue(self) -> Optional[NotificationMessage]:
        """
        Remove e retorna a próxima notificação da fila
        Também remove do Redis
        """
        try:
            priority, message = await self._local_queue.get()
            
            # Remover do Redis
            redis = await self._get_redis()
            if redis:
                # Encontrar e remover a notificação específica
                notif_data = json.dumps(message.to_dict())
                await redis.lrem(self.REDIS_QUEUE_KEY, 1, notif_data)
            
            return message
            
        except Exception as e:
            logger.error(f"[NotificationQueue] Erro ao desenfileirar: {e}")
            return None
    
    async def mark_processing(self, message: NotificationMessage):
        """Marca notificação como em processamento"""
        redis = await self._get_redis()
        if redis:
            await redis.hset(
                self.REDIS_PROCESSING_KEY,
                f"{message.chat_id}:{message.created_at}",
                json.dumps(message.to_dict())
            )
    
    async def mark_completed(self, message: NotificationMessage):
        """Marca notificação como concluída (remove do processing)"""
        redis = await self._get_redis()
        if redis:
            await redis.hdel(
                self.REDIS_PROCESSING_KEY,
                f"{message.chat_id}:{message.created_at}"
            )
    
    async def mark_failed(self, message: NotificationMessage, error: str = None):
        """Marca notificação como falha"""
        redis = await self._get_redis()
        if redis:
            data = message.to_dict()
            data['failed_at'] = datetime.utcnow().isoformat()
            data['error'] = error
            
            await redis.lpush(
                self.REDIS_FAILED_KEY,
                json.dumps(data)
            )
            
            # Remover do processing
            await self.mark_completed(message)
    
    async def requeue_failed(self, message: NotificationMessage):
        """Reenfileira notificação com retry incrementado"""
        message.retry_count += 1
        message.priority += 1  # Menor prioridade no retry
        
        if message.retry_count <= message.max_retries:
            await self.enqueue(message)
            return True
        else:
            await self.mark_failed(message, "Max retries exceeded")
            return False
    
    async def get_queue_size(self) -> int:
        """Retorna tamanho da fila"""
        return self._local_queue.qsize()
    
    async def get_redis_queue_size(self) -> int:
        """Retorna tamanho da fila no Redis"""
        redis = await self._get_redis()
        if redis:
            return await redis.llen(self.REDIS_QUEUE_KEY)
        return 0
    
    async def get_processing_count(self) -> int:
        """Retorna número de notificações em processamento"""
        redis = await self._get_redis()
        if redis:
            return await redis.hlen(self.REDIS_PROCESSING_KEY)
        return 0
    
    async def get_failed_count(self) -> int:
        """Retorna número de notificações falhas"""
        redis = await self._get_redis()
        if redis:
            return await redis.llen(self.REDIS_FAILED_KEY)
        return 0
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas completas da fila"""
        return {
            "local_queue_size": await self.get_queue_size(),
            "redis_queue_size": await self.get_redis_queue_size(),
            "processing_count": await self.get_processing_count(),
            "failed_count": await self.get_failed_count(),
            "redis_available": self._redis is not None
        }


# Instância global
notification_queue_manager = NotificationQueueManager()
