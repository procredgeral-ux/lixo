"""
Sistema de métricas unificado - usa mesma lógica do performance_monitor.py
para garantir consistência entre dashboard.log e API /admin/performance
"""
import time
import psutil
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Variáveis globais para tracking (mesmo padrão do performance_monitor)
_ws_messages_sent = 0
_ws_messages_recv = 0

def record_ws_message_global(sent: bool = True):
    """Registrar mensagem WebSocket - pode ser chamada de qualquer lugar"""
    global _ws_messages_sent, _ws_messages_recv
    if sent:
        _ws_messages_sent += 1
    else:
        _ws_messages_recv += 1

def get_ws_message_counts():
    """Retorna contagens de mensagens WebSocket"""
    return _ws_messages_sent, _ws_messages_recv


class UnifiedMetricsCollector:
    """
    Coletor unificado de métricas - garante consistência entre dashboard.log e API
    """
    
    def __init__(self):
        self._start_time = time.time()
        self._process: Optional[psutil.Process] = None
        
        # Histórico para médias móveis
        self._cpu_samples = []
        self._memory_samples = []
        self._latency_samples = []
        
        # Contadores anteriores para deltas
        self._prev_disk_io = None
        self._prev_network_io = None
        self._last_request_count = 0
        
        # API Metrics
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.http_4xx_errors = 0
        self.http_5xx_errors = 0
        self.max_latency_ms = 0.0
        
        # Database Metrics  
        self.db_queries = 0
        self.db_selects = 0
        self.db_inserts = 0
        self.db_updates = 0
        self.db_deletes = 0
        self.db_errors = 0
        self.db_slow_queries = 0
        self.db_total_time_ms = 0.0
        
        # Cache Metrics
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Batch Metrics
        self.batch_signals_saved = 0
        self.batch_save_errors = 0
        self.batch_signals_queued = 0
        self.batch_last_save_time = None
        
    def _get_process(self) -> psutil.Process:
        """Get or create process handle"""
        if self._process is None:
            self._process = psutil.Process()
            # Initialize CPU baseline
            self._process.cpu_percent(interval=None)
        return self._process
    
    def record_api_request(self, latency_ms: float, status_code: int):
        """Registrar requisição API"""
        self.total_requests += 1
        self._latency_samples.append(latency_ms)
        
        # Limitar histórico
        if len(self._latency_samples) > 300:
            self._latency_samples.pop(0)
        
        if 200 <= status_code < 400:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if 400 <= status_code < 500:
                self.http_4xx_errors += 1
            elif status_code >= 500:
                self.http_5xx_errors += 1
        
        if latency_ms > self.max_latency_ms:
            self.max_latency_ms = latency_ms
    
    def record_db_query(self, query_type: str, duration_ms: float):
        """Registrar query SQL"""
        self.db_queries += 1
        self.db_total_time_ms += duration_ms
        
        query_upper = query_type.upper()
        if 'SELECT' in query_upper:
            self.db_selects += 1
        elif 'INSERT' in query_upper:
            self.db_inserts += 1
        elif 'UPDATE' in query_upper:
            self.db_updates += 1
        elif 'DELETE' in query_upper:
            self.db_deletes += 1
        
        if duration_ms > 1000:  # Query lenta > 1s
            self.db_slow_queries += 1
    
    def record_db_error(self):
        """Registrar erro de DB"""
        self.db_errors += 1
    
    def record_cache_hit(self):
        """Registrar cache hit"""
        self.cache_hits += 1
    
    def record_cache_miss(self):
        """Registrar cache miss"""
        self.cache_misses += 1
    
    def record_batch_save(self, count: int = 1, success: bool = True):
        """Registrar save do batch"""
        if success:
            self.batch_signals_saved += count
            self.batch_last_save_time = datetime.now().strftime("%H:%M:%S")
        else:
            self.batch_save_errors += 1
    
    def update_batch_queue(self, size: int):
        """Atualizar tamanho da fila do batch"""
        self.batch_signals_queued = size
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de sistema (mesma lógica do performance_monitor.py)"""
        process = self._get_process()
        
        # CPU - normalizado por cpu_count (igual ao Gerenciador de Tarefas)
        cpu_percent_raw = process.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count() or 1
        cpu_percent = cpu_percent_raw / cpu_count
        
        # Memória - Working Set no Windows, RSS em outros
        memory_info = process.memory_info()
        if sys.platform == 'win32' and hasattr(memory_info, 'wset'):
            memory_mb = memory_info.wset / 1024 / 1024
        else:
            memory_mb = memory_info.rss / 1024 / 1024
        
        # Atualizar histórico
        self._cpu_samples.append(cpu_percent)
        self._memory_samples.append(memory_mb)
        
        # Manter apenas últimos 60 samples
        if len(self._cpu_samples) > 60:
            self._cpu_samples.pop(0)
        if len(self._memory_samples) > 60:
            self._memory_samples.pop(0)
        
        # Calcular médias
        avg_cpu = sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0
        avg_memory = sum(self._memory_samples) / len(self._memory_samples) if self._memory_samples else 0
        
        # Uptime
        uptime_seconds = time.time() - self._start_time
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        secs = int(uptime_seconds % 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        
        # Disco
        try:
            disk_usage = psutil.disk_usage('/')
            disk_percent = disk_usage.percent
        except:
            disk_percent = 0.0
        
        # Disco IO (delta)
        disk_read_mb = 0.0
        disk_write_mb = 0.0
        try:
            disk_io = psutil.disk_io_counters()
            if self._prev_disk_io is not None and disk_io:
                read_bytes = disk_io.read_bytes - self._prev_disk_io.read_bytes
                write_bytes = disk_io.write_bytes - self._prev_disk_io.write_bytes
                disk_read_mb = read_bytes / 1024 / 1024
                disk_write_mb = write_bytes / 1024 / 1024
            self._prev_disk_io = disk_io
        except:
            pass
        
        # Network IO (delta)
        net_recv_mb = 0.0
        net_sent_mb = 0.0
        try:
            net_io = psutil.net_io_counters()
            if self._prev_network_io is not None and net_io:
                recv_bytes = net_io.bytes_recv - self._prev_network_io.bytes_recv
                sent_bytes = net_io.bytes_sent - self._prev_network_io.bytes_sent
                net_recv_mb = recv_bytes / 1024 / 1024
                net_sent_mb = sent_bytes / 1024 / 1024
            self._prev_network_io = net_io
        except:
            pass
        
        # Load Average
        try:
            load_avg = psutil.getloadavg()
            load_avg_1m, load_avg_5m, load_avg_15m = load_avg
        except:
            load_avg_1m = load_avg_5m = load_avg_15m = 0.0
        
        # Swap
        try:
            swap = psutil.swap_memory()
            swap_used_mb = swap.used / 1024 / 1024
            swap_total_mb = swap.total / 1024 / 1024
        except:
            swap_used_mb = swap_total_mb = 0.0
        
        return {
            'uptime': uptime_str,
            'memory_mb': memory_mb,
            'avg_memory_mb': avg_memory,
            'cpu_percent': cpu_percent,
            'avg_cpu_percent': avg_cpu,
            'threads': process.num_threads(),
            'disk_usage_percent': disk_percent,
            'disk_read_mb': disk_read_mb,
            'disk_write_mb': disk_write_mb,
            'network_recv_mb': net_recv_mb,
            'network_sent_mb': net_sent_mb,
            'load_avg_1m': load_avg_1m,
            'load_avg_5m': load_avg_5m,
            'load_avg_15m': load_avg_15m,
            'swap_used_mb': swap_used_mb,
            'swap_total_mb': swap_total_mb,
        }
    
    def get_api_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de API"""
        # Calcular latências
        avg_latency = 0.0
        p95_latency = 0.0
        p99_latency = 0.0
        
        if self._latency_samples:
            sorted_latencies = sorted(self._latency_samples)
            n = len(sorted_latencies)
            avg_latency = sum(sorted_latencies) / n
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)
            p95_latency = sorted_latencies[min(p95_idx, n-1)]
            p99_latency = sorted_latencies[min(p99_idx, n-1)]
        
        # Taxa de sucesso
        total = self.total_requests
        success_rate = (self.successful_requests / total * 100) if total > 0 else 0
        
        # RPS (requests no último minuto / 60)
        # Simplificado: total / tempo desde início
        elapsed = time.time() - self._start_time
        rps = self.total_requests / elapsed if elapsed > 0 else 0
        
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'success_rate': success_rate,
            'http_4xx_errors': self.http_4xx_errors,
            'http_5xx_errors': self.http_5xx_errors,
            'rps_current': rps,
            'avg_latency_ms': avg_latency,
            'latency_p95_ms': p95_latency,
            'latency_p99_ms': p99_latency,
            'max_latency_ms': self.max_latency_ms,
        }
    
    def get_websocket_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de WebSocket"""
        ws_sent, ws_recv = get_ws_message_counts()
        
        # Tentar obter métricas do connection_manager se disponível
        connection_metrics = {
            'user_connections': 0,
            'monitoring_connections': 0,
            'ws_connections': 0,
            'active_accounts': 0,
        }
        
        try:
            # Importar e obter métricas do connection_manager
            from services import data_collector as dc_module
            if dc_module.connection_manager:
                metrics = dc_module.connection_manager.get_metrics()
                connection_metrics.update(metrics)
        except Exception:
            # Se não conseguir importar, manter zeros
            pass
        
        return {
            'ws_messages_sent': ws_sent,
            'ws_messages_recv': ws_recv,
            'ws_reconnections': 0,  # TODO: Implementar tracking
            'user_connections': connection_metrics['user_connections'],
            'monitoring_connections': connection_metrics['monitoring_connections'],
            'ws_connections': connection_metrics['ws_connections'],
            'active_accounts': connection_metrics['active_accounts'],
            'broker_latency_ms': 0.0,  # TODO: Implementar
        }
    
    def get_database_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de Database - sincroniza com performance_monitor"""
        # Tentar obter métricas do performance_monitor primeiro
        try:
            from services.performance_monitor import performance_monitor
            pm_stats = performance_monitor.stats
            
            return {
                'db_queries': pm_stats.get('db_queries', 0),
                'db_selects': pm_stats.get('db_selects', 0),
                'db_inserts': pm_stats.get('db_inserts', 0),
                'db_updates': pm_stats.get('db_updates', 0),
                'db_deletes': pm_stats.get('db_deletes', 0),
                'db_errors': pm_stats.get('db_errors', 0),
                'db_slow_queries': pm_stats.get('db_slow_queries', 0),
                'db_avg_time_ms': pm_stats.get('db_avg_time_ms', 0.0),
                'db_total_time_ms': pm_stats.get('db_total_time_ms', 0.0),
            }
        except Exception:
            # Fallback para métricas locais se performance_monitor não disponível
            avg_time = self.db_total_time_ms / self.db_queries if self.db_queries > 0 else 0
            
            return {
                'db_queries': self.db_queries,
                'db_selects': self.db_selects,
                'db_inserts': self.db_inserts,
                'db_updates': self.db_updates,
                'db_deletes': self.db_deletes,
                'db_errors': self.db_errors,
                'db_slow_queries': self.db_slow_queries,
                'db_avg_time_ms': avg_time,
                'db_total_time_ms': self.db_total_time_ms,
            }
    
    def get_cache_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de Cache - sincroniza com performance_monitor"""
        try:
            from services.performance_monitor import performance_monitor
            pm_stats = performance_monitor.stats
            
            hits = pm_stats.get('cache_hits', 0)
            misses = pm_stats.get('cache_misses', 0)
            total = hits + misses
            hit_rate = (hits / total * 100) if total > 0 else 0
            
            return {
                'cache_hits': hits,
                'cache_misses': misses,
                'cache_hit_rate': hit_rate,
            }
        except Exception:
            # Fallback para métricas locais
            total = self.cache_hits + self.cache_misses
            hit_rate = (self.cache_hits / total * 100) if total > 0 else 0
            
            return {
                'cache_hits': self.cache_hits,
                'cache_misses': self.cache_misses,
                'cache_hit_rate': hit_rate,
            }
    
    def get_batch_metrics(self) -> Dict[str, Any]:
        """Coletar métricas de Batch - sincroniza com performance_monitor"""
        try:
            from services.performance_monitor import performance_monitor
            pm_stats = performance_monitor.stats
            
            return {
                'batch_signals_queued': pm_stats.get('batch_signals_queued', 0),
                'batch_signals_saved': pm_stats.get('batch_signals_saved', 0),
                'batch_save_errors': pm_stats.get('batch_save_errors', 0),
                'batch_last_save_time': pm_stats.get('batch_last_save_time', 'Nunca'),
            }
        except Exception:
            # Fallback para métricas locais
            return {
                'batch_signals_queued': self.batch_signals_queued,
                'batch_signals_saved': self.batch_signals_saved,
                'batch_save_errors': self.batch_save_errors,
                'batch_last_save_time': self.batch_last_save_time or 'Nunca',
            }


# Instância global (singleton)
_unified_metrics = None

def get_unified_metrics() -> UnifiedMetricsCollector:
    """Get or create unified metrics collector"""
    global _unified_metrics
    if _unified_metrics is None:
        _unified_metrics = UnifiedMetricsCollector()
    return _unified_metrics
