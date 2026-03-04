"""
Métricas de Performance do Sistema
Coleta estatísticas reais de API, WebSocket, Database e Cache
"""
import time
import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class APIMetrics:
    """Métricas de API e latência"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    errors_4xx: int = 0
    errors_5xx: int = 0
    
    # Latências em ms
    latencies: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record_request(self, latency_ms: float, status_code: int):
        """Registra uma requisição"""
        self.total_requests += 1
        self.latencies.append(latency_ms)
        
        if 200 <= status_code < 400:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if 400 <= status_code < 500:
                self.errors_4xx += 1
            elif status_code >= 500:
                self.errors_5xx += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas calculadas"""
        if not self.latencies:
            return {
                "latenciaMedia": "0 ms",
                "latenciaP95": "0 ms",
                "latenciaP99": "0 ms",
                "latenciaMaxima": "0 ms",
                "sucessos": "0 (0.0%)",
                "falhas": 0,
                "erros4xx": 0,
                "erros5xx": 0,
            }
        
        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)
        
        return {
            "latenciaMedia": f"{sum(self.latencies) / n:.1f} ms",
            "latenciaP95": f"{sorted_latencies[int(n * 0.95)] if n > 1 else sorted_latencies[0]:.1f} ms",
            "latenciaP99": f"{sorted_latencies[int(n * 0.99)] if n > 1 else sorted_latencies[0]:.1f} ms",
            "latenciaMaxima": f"{max(self.latencies):.1f} ms",
            "sucessos": f"{self.successful_requests} ({self.successful_requests / self.total_requests * 100:.1f}%)",
            "falhas": self.failed_requests,
            "erros4xx": self.errors_4xx,
            "erros5xx": self.errors_5xx,
        }


@dataclass
class WebSocketMetrics:
    """Métricas de WebSocket e conexões"""
    user_connections: int = 0
    monitoring_connections: int = 0
    reconnections: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    broker_latency_ms: float = 0.0
    
    # Contas ativas conectadas
    active_accounts: set = field(default_factory=set)
    
    def update_connections(self, user_count: int, monitoring_count: int):
        """Atualiza contagem de conexões"""
        self.user_connections = user_count
        self.monitoring_connections = monitoring_count
    
    def record_message(self, sent: bool = False, received: bool = False):
        """Registra mensagem WebSocket"""
        if sent:
            self.messages_sent += 1
        if received:
            self.messages_received += 1
    
    def record_reconnection(self):
        """Registra reconexão"""
        self.reconnections += 1
    
    def set_broker_latency(self, latency_ms: float):
        """Define latência da corretora"""
        self.broker_latency_ms = latency_ms
    
    def add_active_account(self, account_id: str):
        """Adiciona conta ativa"""
        self.active_accounts.add(account_id)
    
    def remove_active_account(self, account_id: str):
        """Remove conta ativa"""
        self.active_accounts.discard(account_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas"""
        return {
            "conexoesUsuarios": self.user_connections,
            "conexoesMonitoramento": self.monitoring_connections,
            "totalConexoesWS": self.user_connections + self.monitoring_connections,
            "contasAtivas": len(self.active_accounts),
            "mensagensWSEnviadas": self.messages_sent,
            "mensagensWSRecebidas": self.messages_received,
            "reconexoes": self.reconnections,
            "latenciaCorretora": f"{self.broker_latency_ms:.1f} ms",
        }


@dataclass
class DatabaseMetrics:
    """Métricas de Banco de Dados"""
    queries_executed: int = 0
    selects: int = 0
    inserts: int = 0
    updates: int = 0
    deletes: int = 0
    errors: int = 0
    slow_queries: int = 0
    
    # Tempos das queries (ms)
    query_times: deque = field(default_factory=lambda: deque(maxlen=500))
    
    def record_query(self, query_type: str, duration_ms: float):
        """Registra uma query"""
        self.queries_executed += 1
        self.query_times.append(duration_ms)
        
        query_type = query_type.upper()
        if "SELECT" in query_type:
            self.selects += 1
        elif "INSERT" in query_type:
            self.inserts += 1
        elif "UPDATE" in query_type:
            self.updates += 1
        elif "DELETE" in query_type:
            self.deletes += 1
        
        # Query lenta (>100ms)
        if duration_ms > 100:
            self.slow_queries += 1
    
    def record_error(self):
        """Registra erro de DB"""
        self.errors += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas"""
        total_time = sum(self.query_times) if self.query_times else 0
        avg_time = total_time / len(self.query_times) if self.query_times else 0
        
        return {
            "queriesExecutadas": self.queries_executed,
            "select": self.selects,
            "insert": self.inserts,
            "update": self.updates,
            "delete": self.deletes,
            "errosDB": self.errors,
            "queriesLentas": self.slow_queries,
            "tempoMedioQuery": f"{avg_time:.1f} ms",
            "tempoTotalQueries": f"{total_time:.1f} ms",
        }


@dataclass
class CacheMetrics:
    """Métricas de Cache"""
    hits: int = 0
    misses: int = 0
    
    def record_hit(self):
        """Registra cache hit"""
        self.hits += 1
    
    def record_miss(self):
        """Registra cache miss"""
        self.misses += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        
        return {
            "cacheHits": self.hits,
            "cacheMisses": self.misses,
            "cacheHitRate": f"{hit_rate:.1f}%",
        }


class MetricsCollector:
    """Coletor central de métricas do sistema"""
    
    def __init__(self):
        self.api = APIMetrics()
        self.websocket = WebSocketMetrics()
        self.database = DatabaseMetrics()
        self.cache = CacheMetrics()
        
        # Timestamp de início
        self.start_time = datetime.utcnow()
        
        # RPS tracking
        self.requests_per_second = deque(maxlen=60)  # Últimos 60 segundos
        
        # Batch processing
        self.batch_saved = 0
        self.batch_errors = 0
        self.batch_times: deque = deque(maxlen=100)
        self.last_batch_save: Optional[datetime] = None
        self.batch_queue_size = 0
    
    def record_api_request(self, latency_ms: float, status_code: int):
        """Registra requisição API"""
        self.api.record_request(latency_ms, status_code)
    
    def record_query(self, query_type: str, duration_ms: float):
        """Registra query SQL"""
        self.database.record_query(query_type, duration_ms)
    
    def record_cache_hit(self):
        """Registra cache hit"""
        self.cache.record_hit()
    
    def record_cache_miss(self):
        """Registra cache miss"""
        self.cache.record_miss()
    
    def update_websocket_connections(self, user_count: int, monitoring_count: int):
        """Atualiza conexões WebSocket"""
        self.websocket.update_connections(user_count, monitoring_count)
    
    def record_websocket_message(self, sent: bool = False, received: bool = False):
        """Registra mensagem WebSocket"""
        self.websocket.record_message(sent, received)
    
    def record_batch_save(self, duration_ms: float, success: bool = True):
        """Registra save do batch"""
        self.last_batch_save = datetime.utcnow()
        if success:
            self.batch_saved += 1
        else:
            self.batch_errors += 1
        self.batch_times.append(duration_ms)
    
    def update_batch_queue(self, size: int):
        """Atualiza tamanho da fila do batch"""
        self.batch_queue_size = size
    
    def get_uptime(self) -> str:
        """Retorna uptime formatado"""
        uptime = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_batch_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do batch"""
        avg_time = sum(self.batch_times) / len(self.batch_times) if self.batch_times else 0
        
        # Throughput: sinais por segundo (últimos 60 segundos)
        throughput = self.batch_saved / 60 if self.batch_saved > 0 else 0
        
        last_save_str = "Nunca"
        if self.last_batch_save:
            last_save_str = self.last_batch_save.strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "batchFila": self.batch_queue_size,
            "batchSalvos": self.batch_saved,
            "batchErros": self.batch_errors,
            "batchTempoMedio": f"{avg_time:.1f} ms",
            "batchThroughput": f"{throughput:.1f} sinais/s",
            "batchUltimoSave": last_save_str,
            "agregacaoUltima": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "agregacaoStatus": "running",
        }
    
    def reset(self):
        """Reseta todas as métricas (cuidado!)"""
        self.api = APIMetrics()
        self.websocket = WebSocketMetrics()
        self.database = DatabaseMetrics()
        self.cache = CacheMetrics()
        self.start_time = datetime.utcnow()
        self.batch_saved = 0
        self.batch_errors = 0
        self.batch_times.clear()


# Instância global do coletor
metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Retorna instância global do coletor de métricas"""
    return metrics_collector
