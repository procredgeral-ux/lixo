"""
Integrações do UnifiedMetrics com sistemas existentes
Conecta WebSocket, Database e outros serviços ao coletor de métricas
"""
from loguru import logger

# Importar o unified_metrics
from services.unified_metrics import get_unified_metrics, record_ws_message_global

# Instância global
_metrics = get_unified_metrics()


def record_websocket_message(sent: bool = True):
    """
    Registrar mensagem WebSocket
    Uso: chamar quando enviar ou receber mensagem via WebSocket
    """
    try:
        record_ws_message_global(sent=sent)
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar WS message: {e}")


def record_database_query(query_type: str, duration_ms: float):
    """
    Registrar query SQL
    Uso: chamar após executar query no banco de dados
    
    Args:
        query_type: Tipo da query (SELECT, INSERT, UPDATE, DELETE)
        duration_ms: Tempo de execução em milissegundos
    """
    try:
        _metrics.record_db_query(query_type, duration_ms)
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar DB query: {e}")


def record_database_error():
    """
    Registrar erro de banco de dados
    Uso: chamar quando ocorrer erro em query SQL
    """
    try:
        _metrics.record_db_error()
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar DB error: {e}")


def record_cache_hit():
    """
    Registrar cache hit
    Uso: chamar quando dado for encontrado no cache
    """
    try:
        _metrics.record_cache_hit()
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar cache hit: {e}")


def record_cache_miss():
    """
    Registrar cache miss
    Uso: chamar quando dado NÃO for encontrado no cache
    """
    try:
        _metrics.record_cache_miss()
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar cache miss: {e}")


def record_batch_save(count: int = 1, success: bool = True):
    """
    Registrar save do batch
    Uso: chamar quando sinais forem salvos em lote
    
    Args:
        count: Quantidade de sinais salvos
        success: Se a operação foi bem sucedida
    """
    try:
        _metrics.record_batch_save(count, success)
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao registrar batch save: {e}")


def update_batch_queue_size(size: int):
    """
    Atualizar tamanho da fila do batch
    Uso: chamar periodicamente com tamanho atual da fila
    
    Args:
        size: Número de sinais na fila
    """
    try:
        _metrics.update_batch_queue(size)
    except Exception as e:
        logger.debug(f"[MetricsIntegration] Erro ao atualizar batch queue: {e}")


# Funções de conveniência para integração rápida

def ws_message_sent():
    """WebSocket message sent"""
    record_websocket_message(sent=True)


def ws_message_received():
    """WebSocket message received"""
    record_websocket_message(sent=False)


# Decorator para medir tempo de queries
import time
from functools import wraps

def track_query_time(query_type: str):
    """
    Decorator para automaticamente medir tempo de queries
    
    Uso:
        @track_query_time("SELECT")
        async def get_user(user_id):
            return await db.fetch_one(...)
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                record_database_query(query_type, duration_ms)
                return result
            except Exception:
                record_database_error()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                record_database_query(query_type, duration_ms)
                return result
            except Exception:
                record_database_error()
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


import asyncio

__all__ = [
    'record_websocket_message',
    'record_database_query',
    'record_database_error',
    'record_cache_hit',
    'record_cache_miss',
    'record_batch_save',
    'update_batch_queue_size',
    'ws_message_sent',
    'ws_message_received',
    'track_query_time',
]
