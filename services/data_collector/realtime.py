"""
Serviço de coleta de dados em tempo real para PocketOption
"""

import asyncio
import json
import time
import uuid
from collections import deque, defaultdict
from typing import Optional, List, Dict, Any, Deque, Tuple, Set
from datetime import datetime
from pathlib import Path
from loguru import logger
import pandas as pd

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from core.database import get_db_context
from core.config import settings
from models import MonitoringAccount, MonitoringAccountType, Asset, AutoTradeConfig, Strategy, Signal, SignalType, Indicator, strategy_indicators, Account, User
from services.pocketoption.client import AsyncPocketOptionClient
from services.pocketoption.constants import ASSETS

# Criar mapa reverso de asset_id para símbolo para otimização
ASSET_ID_TO_SYMBOL = {asset_id: symbol for symbol, asset_id in ASSETS.items()}
from services.data_collector.local_storage import LocalStorageService, local_storage
from services.data_collector.connection_manager import UserConnectionManager
from services.ws_connection_logger import get_connection_logger, remove_connection_logger
from services.trade_executor import TradeExecutor
from services.notifications.telegram import telegram_service
from services.pocketoption.maintenance_checker import maintenance_checker
from services.pocketoption.maintenance_handler import maintenance_handler
from schemas import CandleResponse, CandleDataResponse
from services.trade_timing_manager import TradeTimingManager
from services.candle_close_tracker import CandleCloseTracker
from services.user_logger import user_logger
from services.l1_cache import autotrade_config_l1_cache, user_data_l1_cache, get_with_l1_l2_cache


class DataCollectorService:
    """Serviço para coleta de dados de mercado em tempo real"""

    def __init__(self):
        self.payout_client: Optional[AsyncPocketOptionClient] = None
        self.ativos_clients: List[AsyncPocketOptionClient] = []
        self.is_running = False

        self.monitored_assets: List[int] = []
        self._assets_update_task: Optional[asyncio.Task] = None
        self._candles_collection_task: Optional[asyncio.Task] = None
        self._ativos_monitoring_task: Optional[asyncio.Task] = None
        # Buffer para acumular ticks antes de logar
        self._tick_buffers: Dict[int, Dict[str, float]] = {}  # {account_idx: {symbol: price}}
        self._last_log_time: Dict[int, float] = {}  # {account_idx: timestamp}
        # Histórico de ticks por símbolo (timestamp em segundos, preço)
        self._tick_history: Dict[str, Deque[Tuple[float, float]]] = {}
        self._tick_history_window_seconds = 3600  # manter até 1h de ticks por símbolo
        self._maintenance_mode = False
        # Buffer para acumular históricos recebidos antes de logar
        self._received_histories: Dict[int, List[Dict[str, Any]]] = {}  # {account_idx: [histories]}
        # Serviço de armazenamento local
        self.local_storage = LocalStorageService()
        
        # Gerenciador de conexões de usuários (demo e real)
        self.connection_manager = UserConnectionManager()
        
        # Exportar instância global para métricas
        import services.data_collector as dc_module
        dc_module.connection_manager = self.connection_manager

        # Executor de trades
        self.trade_executor = TradeExecutor(self.connection_manager)
        self.trade_executor.data_collector = self  # Referência para invalidar cache

        # TradeTimingManager para gerenciar execução no fechamento da vela
        self.trade_timing_manager = TradeTimingManager()
        
        # CandleCloseTracker para rastrear fechamento de velas
        self.candle_close_tracker = CandleCloseTracker()
        
        # BatchSignalSaver para salvamento em lote de sinais (eficiência DB)
        from services.batch_signal_saver import BatchSignalSaver
        self.batch_signal_saver = BatchSignalSaver(
            flush_interval=5.0,  # Salvar a cada 5 segundos
            max_batch_size=50,   # Ou quando atingir 50 sinais
        )
        
        # Injetar TradeTimingManager no TradeExecutor
        self.trade_executor.trade_timing_manager = self.trade_timing_manager

        # Passar trade_executor para connection_manager
        self.connection_manager.trade_executor = self.trade_executor
        
        # Buffer para agrupar fechamentos de velas por timeframe
        self._candle_closes: Dict[int, Dict[str, List[str]]] = {}  # {timeframe_seconds: [symbols]}
        
        # Buffer de candles por timeframe para análise em tempo real
        self._candle_buffers: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}  # {asset: {timeframe: [candles]}}
        
        # Callback para enviar atualizações de candles via WebSocket
        self._candle_update_callback: Optional[callable] = None
        self._last_candle_close: Dict[str, Dict[int, int]] = {}  # {asset: {timeframe: last_close_timestamp}}

        # Registrar callback vazio para evitar warning
        self._candle_update_callback = lambda *args, **kwargs: None
        
        # Timeframes em segundos (UTC-3)
        self.timeframes = {
            '3s': 3,
            '5s': 5,
            '30s': 30,
            '1min': 60,
            '5min': 300,
            '15min': 900,
            '1h': 3600,
            '4h': 14400,
            'daily': 86400
        }
        
        # Estratégias inicializadas
        self.strategies: Dict[str, Any] = {}
        
        # Cache do timeframe configurado (para evitar chamadas excessivas ao banco)
        self._configured_timeframe: Optional[int] = None
        self._configured_timeframes: Optional[Set[int]] = None
        self._config_last_updated: float = 0
        self._config_cache_duration: float = 60  # Cache por 60 segundos
        
        # Cache de todas as configurações de autotrade ativas (para múltiplos usuários)
        self._autotrade_configs: Dict[str, List[Dict[str, Any]]] = {}  # {account_id: [{timeframe, strategy_id, ...}]}
        self._configs_cache_last_updated: float = 0
        self._configs_cache_duration: float = 1  # Cache por 1 segundo (sincronização rápida)
        
        # Rastreamento de ativos monitorados por conta
        self._monitored_assets_by_account: Dict[int, List[str]] = {}  # {account_idx: [symbols]}
        
        # Cooldown por ativo após loss (30 segundos por estratégia/conta)
        # Formato: {account_id: {symbol: {strategy_id: timestamp}}}
        self._asset_cooldowns: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._cooldown_duration = 30  # 30 segundos
        
        # Rastreamento do resultado do último trade por ativo/conta
        self._last_trade_results: Dict[str, Dict[str, str]] = {}  # {account_id: {symbol: 'win'|'loss'}}
        
        # Rastreamento do último tick recebido por ativo (para detectar ativos inativos)
        self._last_tick_time: Dict[str, float] = {}  # {symbol: timestamp}
        self._asset_inactivity_threshold_seconds = 30  # 30 segundos sem ticks = inativo
        
        # Flag para controlar se o storage já foi inicializado (evitar limpar arquivos em reinicializações)
        self._storage_initialized = False
        
        # Health check para conexões de ativos
        self._client_health_status: Dict[int, Dict[str, Any]] = {}  # {account_idx: {'last_tick': timestamp, 'is_connected': bool, 'reconnect_count': int}}
        self._client_watchdog_task: Optional[asyncio.Task] = None
        self._health_check_interval = 5  # Verificar a cada 5 segundos
        self._max_tick_gap_seconds = 10  # Se não receber tick em 10s = problema
        self._max_reconnect_retries = 5  # Máximo de tentativas de reconexão
        self._reconnect_backoff_base = 2  # Base para backoff exponencial (2^retry)
        self._reconnect_lock = asyncio.Lock()  # Lock para evitar reconexões simultâneas
        
    def _get_account_name(self, account_idx: int) -> str:
        """Obter o nome do usuário/conta associado ao account_idx"""
        if account_idx < len(self.ativos_clients):
            client = self.ativos_clients[account_idx]
            if hasattr(client, 'user_name'):
                return client.user_name
        return f"Conta #{account_idx+1}"
    
    def _get_account_name_by_id(self, account_id: str) -> str:
        """Obter o nome do usuário/conta a partir do account_id (UUID)"""
        # Verificar se connection_manager tem a conexão
        if hasattr(self, 'connection_manager') and self.connection_manager:
            # Procurar nas conexões ativas pelo account_id
            for connection_key, connection in self.connection_manager.connections.items():
                if hasattr(connection, 'account_id') and connection.account_id == account_id and hasattr(connection, 'user_name'):
                    return connection.user_name
            # Se não encontrou nas conexões, verificar nos clients
            for client in self.ativos_clients:
                if hasattr(client, 'user_name'):
                    return client.user_name
        # Retornar ID truncado como fallback
        return account_id[:8] if account_id else "Unknown"

    async def _save_best_signal_to_db(self, account_id: str, symbol: str, signal: Any, 
                                     strategy_id: Optional[str], timeframe_seconds: int,
                                     metrics: Dict[str, Any]) -> bool:
        """Salvar o melhor sinal no banco de dados usando batch saver"""
        try:
            # Usar batch saver em vez de salvar diretamente
            signal_id = await self.batch_signal_saver.add_signal(
                account_id=account_id,
                symbol=symbol,
                signal=signal,
                strategy_id=strategy_id,
                timeframe=timeframe_seconds,
                metrics=metrics
            )
            
            signal_type_str = signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
            # Log silenciado
            # logger.info(f"[BEST SIGNAL] Sinal adicionado ao batch: {symbol} ({signal_type_str}) | conf={signal.confidence:.2f}")
            
            # Registrar sinal no performance monitor
            try:
                from services.performance_monitor import performance_monitor
                executed = metrics.get('is_executed', False)
                low_confidence = signal.confidence < 0.7
                performance_monitor.record_signal(executed=executed, low_confidence=low_confidence)
            except Exception as e:
                logger.debug(f"[PerformanceMonitor] Erro ao registrar sinal: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"[BEST SIGNAL] Erro ao adicionar sinal ao batch: {e}")
            return False

    def set_candle_update_callback(self, callback: callable):
        """Registrar callback para enviar atualizações de candles via WebSocket"""
        self._candle_update_callback = callback
    
    def _is_asset_in_cooldown(self, account_id: str, symbol: str, strategy_id: str) -> bool:
        """Verificar se um ativo está em cooldown após loss"""
        import time
        current_time = time.time()

        # Verificar se o último trade foi WIN - se foi, não aplicar cooldown
        if account_id in self._last_trade_results:
            if symbol in self._last_trade_results[account_id]:
                if strategy_id in self._last_trade_results[account_id][symbol]:
                    last_result = self._last_trade_results[account_id][symbol][strategy_id]
                    if last_result == 'win':
                        return False  # WIN permite continuar no mesmo ativo

        # Verificar cooldown padrão
        if account_id not in self._asset_cooldowns:
            return False

        if symbol not in self._asset_cooldowns[account_id]:
            return False

        if strategy_id not in self._asset_cooldowns[account_id][symbol]:
            return False

        cooldown_end = self._asset_cooldowns[account_id][symbol][strategy_id]
        remaining_time = cooldown_end - current_time
        is_in_cooldown = current_time < cooldown_end

        logger.debug(
            f"[COOLDOWN CHECK] {symbol} - remaining={remaining_time:.1f}s, is_in_cooldown={is_in_cooldown}",
            extra={
                "user_name": "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": ""
            }
        )

        # Limpar cooldown expirado
        if not is_in_cooldown:
            logger.info(
                f"✅ [{symbol}] Cooldown expirou, removendo da lista (conta: {account_id[:8]}, estratégia: {strategy_id[:8]})",
                extra={
                    "user_name": self._get_account_name_by_id(account_id),
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": ""
                }
            )
            del self._asset_cooldowns[account_id][symbol][strategy_id]
            # Limpar estruturas vazias
            if not self._asset_cooldowns[account_id][symbol]:
                del self._asset_cooldowns[account_id][symbol]
            if not self._asset_cooldowns[account_id]:
                del self._asset_cooldowns[account_id]

        return is_in_cooldown
    
    def _add_asset_to_cooldown(self, account_id: str, symbol: str, strategy_id: str, result: str = 'loss'):
        """Adicionar ativo ao cooldown após loss"""
        import time
        current_time = time.time()
        
        # Rastrear resultado do último trade
        if account_id not in self._last_trade_results:
            self._last_trade_results[account_id] = {}
        
        if symbol not in self._last_trade_results[account_id]:
            self._last_trade_results[account_id][symbol] = {}
        
        self._last_trade_results[account_id][symbol][strategy_id] = result
        
        # Aplicar cooldown apenas se foi LOSS
        if result == 'loss':
            cooldown_end = current_time + self._cooldown_duration
            
            if account_id not in self._asset_cooldowns:
                self._asset_cooldowns[account_id] = {}
            
            if symbol not in self._asset_cooldowns[account_id]:
                self._asset_cooldowns[account_id][symbol] = {}
            
            self._asset_cooldowns[account_id][symbol][strategy_id] = cooldown_end
            logger.info(
                f"⏳ [{symbol}] Adicionado ao cooldown por {self._cooldown_duration}s após LOSS (conta: {account_id[:8]}, estratégia: {strategy_id[:8]})",
                extra={
                    "user_name": self._get_account_name_by_id(account_id),
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": ""
                }
            )
        else:
            logger.info(
                f"✅ [{symbol}] WIN registrado, sem cooldown (conta: {account_id[:8]}, estratégia: {strategy_id[:8]})",
                extra={
                    "user_name": self._get_account_name_by_id(account_id),
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": ""
                }
            )

    async def initialize(self):
        """Inicializar serviço de coleta de dados"""
        logger.info("Inicializando serviço de coleta de dados...")

        # Pular reset do banco de dados para evitar problemas de bloqueio
        # await self._reset_candles()

        # Estratégias agora são carregadas do banco de dados pelo StrategyManager
        # Não inicializamos estratégias predefinidas aqui

        # Carregar dados históricos do disco para o buffer
        await self._load_historical_data_to_buffer()

        # Carregar contas de monitoramento do banco de dados
        payout_ssid, ativos_ssids = await self._load_monitoring_accounts_from_db()

        if not payout_ssid:
            logger.warning("SSID de PAYOUT não encontrado")
        else:
            logger.info(f"[OK] SSID de PAYOUT encontrado: {payout_ssid[:50]}...")
        if not ativos_ssids:
            logger.warning("SSID de ATIVOS não encontrado")

        # Inicializar cliente PAYOUT
        if payout_ssid:
            self.payout_client = AsyncPocketOptionClient(
                ssid=payout_ssid,
                is_demo=True,
                platform=2,  # Usar plataforma 2 (mobile) como no navegador
                persistent_connection=True,
                auto_reconnect=True,
                user_name="PAYOUT Monitor"
            )
            logger.info("[PAYOUT] [OK] Cliente PAYOUT inicializado")
        else:
            logger.warning("[PAYOUT] [ERROR] Cliente PAYOUT não inicializado (SSID não encontrado)")

        # Inicializar clientes ATIVOS (múltiplas contas)
        if ativos_ssids:
            for idx, ativos_ssid in enumerate(ativos_ssids):
                client = AsyncPocketOptionClient(
                    ssid=ativos_ssid,
                    is_demo=True,
                    platform=2,  # Usar plataforma 2 (mobile) como no navegador
                    persistent_connection=True,
                    auto_reconnect=True,
                    user_name=f"ATIVOS Client {idx + 1}"
                )
                self.ativos_clients.append(client)

        logger.success(f"[MONITORAMENTO] [OK] {len(self.ativos_clients)} clientes ATIVOS inicializados")

    async def _load_historical_data_to_buffer(self):
        """Inicializar buffers de candles - dados serão coletados em tempo real"""
        logger.info("Inicializando buffers de candles para coleta em tempo real...")
        
        # Não ler arquivos de histórico - dados serão coletados em tempo real das conexões WebSocket
        # Inicializar apenas a estrutura dos buffers
        try:
            # Obter lista de ativos monitorados
            monitored_assets = set()
            if hasattr(self, 'ativos_clients') and self.ativos_clients:
                for client in self.ativos_clients:
                    if hasattr(client, 'subscribed_assets'):
                        monitored_assets.update(client.subscribed_assets)
            
            # Inicializar buffers para cada asset e timeframe
            for asset in monitored_assets:
                if asset not in self._candle_buffers:
                    self._candle_buffers[asset] = {}
                if asset not in self._last_candle_close:
                    self._last_candle_close[asset] = {}
                
                for timeframe_seconds in [3, 5, 30, 60, 300, 900, 3600, 14400, 86400]:
                    if timeframe_seconds not in self._candle_buffers[asset]:
                        self._candle_buffers[asset][timeframe_seconds] = []
                    if timeframe_seconds not in self._last_candle_close[asset]:
                        self._last_candle_close[asset][timeframe_seconds] = None
            
            logger.info(f"[OK] Buffers inicializados para {len(monitored_assets)} ativos")
            
        except Exception as e:
            logger.error(f"[ERROR] Erro ao inicializar buffers: {e}")

    async def start(self):
        """Iniciar coleta de dados"""
        self.is_running = True

        # Injetar data_collector no maintenance_handler
        maintenance_handler.set_data_collector(self)

        # Registrar callbacks do maintenance_handler
        await maintenance_handler.register_callbacks()

        # Iniciar serviço de armazenamento local (apenas limpa na primeira inicialização)
        clear_storage = not self._storage_initialized
        await self.local_storage.start(clear_on_start=clear_storage)
        self._storage_initialized = True  # Marcar como inicializado
        
        # Iniciar batch signal saver para salvamento eficiente de sinais
        await self.batch_signal_saver.start()
        logger.info("[BATCH SAVER] Sistema de salvamento em lote iniciado")
        
        # Iniciar monitoramento de trades
        await self.trade_executor.start_monitoring()
        
        # Iniciar monitoramento de conexões de usuários (demo e real)
        await self.connection_manager.start_monitoring()
        
        # Iniciar verificador de manutenção do PocketOption
        if settings.POCKETOPTION_MAINTENANCE_CHECK_ENABLED:
            await maintenance_checker.start()
            logger.info("[OK] Verificador de manutenção iniciado")
        else:
            logger.info("[ERROR] Verificador de manutenção desativado")

        # Passo 1: Conectar cliente PAYOUT para coletar dados de assets
        logger.info("[MONITORAMENTO: PAYOUT] Iniciando conexão do cliente PAYOUT...")
        if self.payout_client:
            logger.info("[MONITORAMENTO: PAYOUT] [OK] Cliente PAYOUT encontrado, tentando conectar...")
            try:
                await self.payout_client.connect()
                logger.success("[MONITORAMENTO: PAYOUT] [OK] Cliente PAYOUT conectado")
                
                # Registrar callback para evento assets_update (dados de payout)
                # O evento é emitido pelo cliente websocket dentro do keep_alive_manager
                if hasattr(self.payout_client, '_keep_alive_manager') and self.payout_client._keep_alive_manager:
                    # Registrar diretamente nos _event_handlers do keep_alive_manager
                    self.payout_client._keep_alive_manager.add_event_handler("assets_update", self._on_payout_data)
                    logger.info("[MONITORAMENTO: PAYOUT] [OK] Callback _on_payout_data registrado")
                else:
                    logger.warning("[MONITORAMENTO: PAYOUT] [ERROR] Keep-alive manager não encontrado no cliente PAYOUT")
                
                # NÃO registrar no cliente para eventos json_data para evitar processamento duplicado
                # self.payout_client.add_event_callback("json_data", self._on_payout_data)
                
                # Aguardar um pouco para coletar dados de payout
                await asyncio.sleep(5)
                
                # Verificar se temos assets no banco de dados
                assets_count = await self._get_assets_count()
                logger.info(f"[OK] Coleta iniciada: {assets_count} assets")
                
                # Iniciar tarefa periódica de atualização de assets
                self._assets_update_task = asyncio.create_task(self._periodic_assets_update())
                logger.info("[OK] Tarefa periódica de atualização de assets iniciada")
                
            except Exception as e:
                logger.error(f"[MONITORAMENTO: PAYOUT] [ERROR] Falha ao conectar cliente PAYOUT: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.warning("[MONITORAMENTO: PAYOUT] [ERROR] Cliente PAYOUT não encontrado (não foi inicializado)")

        # Passo 2: Conectar clientes ATIVOS para monitoramento de preços em tempo real
        if self.ativos_clients:
            try:
                await self._start_ativos_monitoring()
                
                # Iniciar watchdog de conexões de ativos
                self._client_watchdog_task = asyncio.create_task(self._client_connection_watchdog())
                logger.info("[WATCHDOG] Watchdog de conexões de ativos iniciado")
            except Exception as e:
                logger.error(f"Falha ao iniciar monitoramento de ativos: {e}")

    async def stop(self):
        """Parar coleta de dados"""
        logger.info("Parando coleta de dados...")
        
        self.is_running = False

        # Parar verificador de manutenção
        await maintenance_checker.stop()
        
        # Parar monitoramento de trades
        await self.trade_executor.stop_monitoring()
        
        # Parar monitoramento de conexões de usuários
        await self.connection_manager.stop_monitoring()
        
        # Parar serviço de armazenamento local
        await self.local_storage.stop()
        
        # Parar batch signal saver (faz flush final dos sinais pendentes)
        await self.batch_signal_saver.stop()
        logger.info("[BATCH SAVER] Sistema de salvamento em lote parado")
        
        # Cancelar tarefa periódica de atualização de assets
        if self._assets_update_task and not self._assets_update_task.done():
            self._assets_update_task.cancel()
            try:
                await asyncio.wait_for(self._assets_update_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout ao aguardar finalização da task de atualização de assets")
            except asyncio.CancelledError:
                logger.info("Tarefa periódica de atualização de assets cancelada")
        
        # Cancelar watchdog de conexões
        if self._client_watchdog_task and not self._client_watchdog_task.done():
            self._client_watchdog_task.cancel()
            try:
                await asyncio.wait_for(self._client_watchdog_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout ao aguardar finalização do watchdog")
            except asyncio.CancelledError:
                logger.info("[WATCHDOG] Watchdog de conexões cancelado")
        
        # Desconectar cliente PAYOUT
        if self.payout_client:
            try:
                await self.payout_client.disconnect()
                logger.info("[PAYOUT] Cliente PAYOUT desconectado")
            except Exception as e:
                logger.error(f"[PAYOUT] Falha ao desconectar cliente PAYOUT: {e}")

        # Desconectar clientes ATIVOS
        if self._ativos_monitoring_task and not self._ativos_monitoring_task.done():
            self._ativos_monitoring_task.cancel()
            try:
                await asyncio.wait_for(self._ativos_monitoring_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout ao aguardar finalização da task de monitoramento de ativos")
            except asyncio.CancelledError:
                logger.info("Tarefa de monitoramento de ativos cancelada")

        for idx, client in enumerate(self.ativos_clients):
            try:
                # Fechar logger da conexão ATIVOS
                if hasattr(client, '_ws_logger') and client._ws_logger:
                    try:
                        await client._ws_logger.close()
                    except:
                        pass
                if hasattr(client, '_connection_logger_id') and client._connection_logger_id:
                    try:
                        remove_connection_logger(client._connection_logger_id)
                    except:
                        pass
                
                await client.disconnect()
                logger.info(f"[MONITORAMENTO #{idx+1}] Cliente ATIVOS #{idx+1} desconectado")
            except Exception as e:
                logger.error(f"[MONITORAMENTO #{idx+1}] Falha ao desconectar cliente ATIVOS #{idx+1}: {e}")
        
        logger.success("Coleta de dados parada")

    async def _periodic_assets_update(self):
        """Atualizar assets periodicamente - verifica conexão a cada 30s e só reconecta se necessário"""
        update_count = 0
        while self.is_running:
            try:
                await asyncio.sleep(30)  # Verificar a cada 30 segundos (não 5s)
                
                if not self.is_running:
                    break
                
                # Verificar se está em manutenção
                from services.pocketoption.maintenance_checker import maintenance_checker
                if maintenance_checker.is_under_maintenance:
                    logger.debug("[PAUSED] Sistema em manutenção, pulando verificação de payout")
                    continue
                
                # Verificar se o payout_client está conectado e saudável
                if self.payout_client:
                    try:
                        # Verificar se conexão ainda está ativa (is_connected property)
                        is_healthy = hasattr(self.payout_client, 'is_connected') and self.payout_client.is_connected
                        
                        if not is_healthy:
                            logger.warning("[WARNING] Payout connection lost, reconnecting...")
                            
                            # Tentar reconectar
                            try:
                                await self.payout_client.disconnect()
                            except:
                                pass  # Ignora erro ao desconectar se já estava morto
                            
                            await asyncio.sleep(2)
                            
                            connected = await self.payout_client.connect()
                            if connected:
                                logger.info("[OK] Payout reconectado")
                                
                                # Registrar callback novamente após reconexão
                                if hasattr(self.payout_client, '_keep_alive_manager') and self.payout_client._keep_alive_manager:
                                    self.payout_client._keep_alive_manager.add_event_handler("assets_update", self._on_payout_data)
                                    logger.info("[OK] Callback _on_payout_data registrado novamente")
                                
                                # Aguardar coleta de dados
                                await asyncio.sleep(5)
                                
                                # Verificar se temos assets atualizados
                                assets_count = await self._get_assets_count()
                                logger.info(f"[OK] Payout atualizado: {assets_count} assets")
                            else:
                                logger.error("[ERROR] Falha ao reconectar payout")
                        else:
                            # Conexão está saudável, apenas loga periodicamente (a cada 10 ciclos = 5 minutos)
                            update_count += 1
                            if update_count % 10 == 0:
                                assets_count = await self._get_assets_count()
                                logger.info(f"[OK] Payout connection healthy: {assets_count} assets")
                            
                    except Exception as e:
                        logger.error(f"[ERROR] Erro ao verificar/reconectar payout: {e}")
                else:
                    logger.warning("[WARNING] payout_client não configurado")
                    
            except asyncio.CancelledError:
                logger.info("Tarefa periódica de atualização de assets cancelada")
                break
            except Exception as e:
                logger.error(f"[ERROR] Erro na atualização periódica de assets: {e}")
                await asyncio.sleep(60)  # Esperar 1 minuto em caso de erro

    async def _get_autotrade_config(self, account_id: str) -> Optional[AutoTradeConfig]:
        """Obter configuração de autotrade da conta"""
        async with get_db_context() as db:
            result = await db.execute(
                select(AutoTradeConfig).where(AutoTradeConfig.account_id == account_id)
            )
            return result.scalar_one_or_none()

    async def _get_all_autotrade_configs(self) -> Dict[str, List[Dict[str, Any]]]:
        """Carregar todas as configurações de autotrade ativas (com cache L1 + memória)"""
        current_time = time.time()
        cache_key = "all_autotrade_configs"
        
        # Tentar L1 cache primeiro (cachetools - ~100ns)
        cached_value = await autotrade_config_l1_cache.get(cache_key)
        if cached_value is not None:
            # Verificar se o cache em memória também é válido
            if self._autotrade_configs is not None and (current_time - self._configs_cache_last_updated) < self._configs_cache_duration:
                # Ceder controle ao event loop para evitar bloqueio
                await asyncio.sleep(0)
                return self._autotrade_configs
            # Se não, usar o valor do L1 cache e atualizar memória
            self._autotrade_configs = cached_value
            self._configs_cache_last_updated = current_time
            # Ceder controle ao event loop para evitar bloqueio
            await asyncio.sleep(0)
            return cached_value

        # Verificar se o cache foi invalidado (se _configs_cache_last_updated == 0)
        if self._configs_cache_last_updated == 0:
            logger.info("[REBALANCE] Cache invalidado, recarregando configurações do banco")
            # Forçar recarga do banco
            self._autotrade_configs = None

        # Verificar se o cache ainda é válido
        if self._autotrade_configs is not None and (current_time - self._configs_cache_last_updated) < self._configs_cache_duration:
            # Ceder controle ao event loop para evitar bloqueio
            await asyncio.sleep(0)
            return self._autotrade_configs

        # Se o cache foi invalidado ou expirou, recarregar do banco
        try:
            async with get_db_context() as db:
                # Carregar TODAS as configurações de autotrade ativas diretamente
                result = await db.execute(
                    select(AutoTradeConfig, Strategy.parameters)
                    .join(Strategy, Strategy.id == AutoTradeConfig.strategy_id, isouter=True)
                    .where(AutoTradeConfig.is_active == True)
                )
                autotrade_rows = result.all()

                if not autotrade_rows:
                    self._autotrade_configs = {}
                    self._configs_cache_last_updated = current_time
                    await autotrade_config_l1_cache.set(cache_key, {})
                    return {}

                # Carregar indicadores de todas as estratégias em batch
                strategy_ids = {
                    autotrade_config.strategy_id
                    for autotrade_config, _ in autotrade_rows
                    if autotrade_config.strategy_id
                }

                indicators_by_strategy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
                if strategy_ids:
                    strategy_indicators_result = await db.execute(
                        select(
                            strategy_indicators.c.strategy_id,
                            Indicator,
                            strategy_indicators.c.parameters,
                        )
                        .join(Indicator, Indicator.id == strategy_indicators.c.indicator_id)
                        .where(strategy_indicators.c.strategy_id.in_(strategy_ids))
                    )
                    for strategy_id, indicator, params in strategy_indicators_result.all():
                        indicator_data = {
                            'type': indicator.type,
                            'name': indicator.name,
                            'parameters': params if params is not None else (indicator.parameters or {})
                        }
                        indicators_by_strategy[strategy_id].append(indicator_data)

                # Carregar configurações de todas as contas
                configs: Dict[str, List[Dict[str, Any]]] = {}

                for autotrade_config, strategy_params in autotrade_rows:
                    strategy_params = strategy_params or {}
                    indicators = indicators_by_strategy.get(autotrade_config.strategy_id, [])

                    configs.setdefault(autotrade_config.account_id, []).append({
                        'timeframe': autotrade_config.timeframe,
                        'strategy_id': autotrade_config.strategy_id,
                        'is_active': autotrade_config.is_active,
                        'amount': autotrade_config.amount,
                        'stop1': autotrade_config.stop1,
                        'stop2': autotrade_config.stop2,
                        'no_hibernate_on_consecutive_stop': autotrade_config.no_hibernate_on_consecutive_stop,
                        'soros': autotrade_config.soros,
                        'martingale': autotrade_config.martingale,
                        'min_confidence': autotrade_config.min_confidence,
                        'trade_timing': getattr(autotrade_config, 'trade_timing', 'on_signal'),
                        'execute_all_signals': getattr(autotrade_config, 'execute_all_signals', False),
                        'strategy_parameters': strategy_params,
                        'indicators': indicators,
                    })
                    logger.info(
                        f"[LIST] Conta {autotrade_config.account_id}: timeframe={autotrade_config.timeframe}s, "
                        f"strategy={autotrade_config.strategy_id}, indicators={len(indicators)}"
                    )

                # Atualizar cache
                self._autotrade_configs = configs
                self._configs_cache_last_updated = current_time
                
                # Salvar no L1 cache
                await autotrade_config_l1_cache.set(cache_key, configs)

                logger.info(f"[LIST] {len(configs)} configuração(ões) de autotrade carregada(s)")
                return configs
        except Exception as e:
            logger.error(f"Erro ao carregar configurações de autotrade: {e}")
            return {}

    async def invalidate_autotrade_configs_cache(self):
        """Invalidar o cache das configurações de autotrade"""
        self._autotrade_configs = None
        self._configs_cache_last_updated = 0
        self._configured_timeframes = None
        self._configured_timeframe = None
        self._config_last_updated = 0
        # Invalidar L1 cache também - aguardar a operação completar
        try:
            await autotrade_config_l1_cache.delete("all_autotrade_configs")
        except Exception as e:
            logger.debug(f"[CACHE] Erro ao invalidar L1 cache (não crítico): {e}")
        logger.info("[OK] Cache de configurações de autotrade invalidado")

    async def _get_configured_timeframe(self) -> Optional[int]:
        """Obter um timeframe configurado (compatibilidade)."""
        configured_timeframes = await self._get_configured_timeframes_cache()
        if not configured_timeframes:
            self._configured_timeframe = None
            return None

        self._configured_timeframe = min(configured_timeframes)
        return self._configured_timeframe

    async def _load_monitoring_accounts_from_db(self) -> Tuple[Optional[str], List[str]]:
        """Carregar contas de monitoramento do banco de dados"""
        payout_ssid = None
        ativos_ssids = []
        
        try:
            from sqlalchemy import text
            
            async with get_db_context() as db:
                # Usar SQL direto para evitar parsing de datetime corrompido
                # Carregar conta de payout com SSID
                result = await db.execute(
                    text("""
                        SELECT ssid, account_type 
                        FROM monitoring_accounts 
                        WHERE UPPER(CAST(account_type AS TEXT)) = 'PAYOUT' AND is_active = TRUE 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """)
                )
                payout_row = result.fetchone()
                if payout_row:
                    ssid = payout_row[0]
                    if ssid:
                        payout_ssid = ssid
                        logger.info("SSID de PAYOUT carregado do banco de dados")
                    else:
                        logger.warning("SSID não configurado para conta de PAYOUT")
                else:
                    logger.warning("Nenhuma conta PAYOUT ativa encontrada no banco de dados")
                
                # Carregar TODAS as contas de ativos (para distribuição de assets)
                result = await db.execute(
                    text("""
                        SELECT ssid 
                        FROM monitoring_accounts 
                        WHERE UPPER(CAST(account_type AS TEXT)) = 'ATIVOS' AND is_active = TRUE 
                        ORDER BY created_at DESC
                    """)
                )
                ativos_rows = result.fetchall()
                if ativos_rows:
                    for row in ativos_rows:
                        ssid = row[0]
                        if ssid:
                            ativos_ssids.append(ssid)
                    
                    logger.info(f"{len(ativos_ssids)} contas ATIVOS carregadas do banco de dados")
                else:
                    logger.warning("Nenhuma conta ATIVOS ativa encontrada no banco de dados")
                
        except Exception as e:
            logger.error(f"Falha ao carregar contas de monitoramento do banco de dados: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
        return payout_ssid, ativos_ssids

    async def _get_assets_count(self) -> int:
        """Obter contagem de assets no banco de dados"""
        async with get_db_context() as db:
            try:
                result = await db.execute(select(Asset).where(Asset.is_active == True))
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Falha ao obter contagem de assets: {e}")
                return 0

    async def _get_top_assets_by_payout(self, limit: int = None, min_payout: float = None) -> List[Asset]:
        """Obter assets com melhor payout do banco de dados"""
        async with get_db_context() as db:
            try:
                query = (
                    select(Asset)
                    .where(Asset.is_active == True, Asset.payout.isnot(None))
                )
                
                # Adicionar filtro de payout mínimo se fornecido
                if min_payout is not None:
                    query = query.where(Asset.payout >= min_payout)
                
                query = query.order_by(Asset.payout.desc())
                
                if limit:
                    query = query.limit(limit)
                
                result = await db.execute(query)
                assets = result.scalars().all()
                
                # Garantir que EURUSD_otc sempre esteja na lista
                eurusd_in_list = any(asset.symbol == 'EURUSD_otc' for asset in assets)
                if not eurusd_in_list:
                    # Buscar EURUSD_otc
                    eurusd_query = select(Asset).where(Asset.symbol == 'EURUSD_otc')
                    eurusd_result = await db.execute(eurusd_query)
                    eurusd_asset = eurusd_result.scalar_one_or_none()
                    
                    if eurusd_asset:
                        # Adicionar EURUSD_otc no início da lista
                        assets = [eurusd_asset] + list(assets)
                        logger.info("EURUSD_otc adicionado à lista de monitoramento")
                
                return assets
            except Exception as e:
                logger.error(f"Falha ao obter assets por payout: {e}")
                return []

    async def _start_ativos_monitoring(self):
        """Iniciar monitoramento de ativos em múltiplas contas"""
        logger.info("Iniciando monitoramento de ativos...")

        # Iniciar gerenciador unificado de reconexão
        from services.data_collector.reconnection_manager import get_reconnection_manager
        reconnection_manager = get_reconnection_manager()

        # Conectar todos os clientes ATIVOS
        for idx, client in enumerate(self.ativos_clients):
            try:
                # Criar logger específico para este cliente ATIVOS (ID estável)
                import hashlib
                stable_id_base = f"ativos_{idx}_{client.ssid[:20]}" if hasattr(client, 'ssid') else f"ativos_{idx}"
                stable_id = hashlib.md5(stable_id_base.encode()).hexdigest()[:12]
                connection_logger_id = f"ativos_{stable_id}"
                
                # Verificar se já existe logger para este cliente
                if not hasattr(client, '_ws_logger') or client._ws_logger is None:
                    ws_logger = get_connection_logger(
                        connection_logger_id,
                        connection_type="ativos",
                        user_name=getattr(client, 'user_name', f'ATIVOS {idx+1}')
                    )
                    # Anexar logger ao cliente para acesso posterior
                    client._ws_logger = ws_logger
                    client._connection_logger_id = connection_logger_id
                else:
                    ws_logger = client._ws_logger
                
                await ws_logger.log_event("INIT", f"Iniciando ATIVOS Client #{idx+1}", {
                    "account_idx": idx,
                    "user_name": getattr(client, 'user_name', f'ATIVOS {idx+1}'),
                    "stable_id": stable_id
                })
                
                connected = await client.connect()
                if connected:
                    logger.info(f"[MONITORAMENTO #{idx+1}] Cliente ATIVOS #{idx+1} conectado")
                    await ws_logger.log_event("CONNECT", "Cliente conectado com sucesso")
                else:
                    logger.warning(
                        f"[MONITORAMENTO #{idx+1}] Cliente ATIVOS #{idx+1} não conectou - aguardando reconexão"
                    )
                    await ws_logger.log_event("WARNING", "Cliente não conectou inicialmente")

                # Registrar no gerenciador unificado de reconexão
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                connection_id = f"ativos_{idx}_{timestamp}"
                reconnection_manager.register_connection(
                    connection_id=connection_id,
                    client=client,
                    connect_fn=lambda c=client: c.connect(),
                    disconnect_fn=lambda c=client: c.disconnect(),
                    check_connected_fn=lambda c: c.is_connected,
                    config={
                        'max_retries': 10,
                        'initial_delay': 5,
                        'max_delay': 60,
                        'backoff_multiplier': 2,
                        'should_reconnect': True
                    },
                    connection_type="monitoring_ativos",
                    description=f"Monitoramento ATIVOS #{idx+1}"
                )
                logger.info(f"[MONITORAMENTO #{idx+1}] [OK] Cliente ATIVOS #{idx+1} registrado no gerenciador unificado")

                # Registrar callback para stream_update (atualizações de preços)
                async def stream_update_wrapper(data, idx=idx, client=client):
                    # Logar no ws_logger do cliente
                    if hasattr(client, '_ws_logger') and client._ws_logger:
                        try:
                            await client._ws_logger.log_callback_event("stream_update", data)
                        except:
                            pass
                    await self._on_ativos_stream_update(data, idx)
                client.add_event_callback("stream_update", stream_update_wrapper)

                # Registrar callback para json_data (ticks)
                async def json_data_wrapper(data, idx=idx, client=client):
                    # Logar no ws_logger do cliente
                    if hasattr(client, '_ws_logger') and client._ws_logger:
                        try:
                            await client._ws_logger.log_callback_event("json_data", data)
                        except:
                            pass
                    await self._on_json_data(data, idx)
                client.add_event_callback("json_data", json_data_wrapper)

                # Registrar callback para candles_received (histórico completo) ANTES de inscrever nos assets
                async def candles_received_wrapper(data):
                    await self._on_ativos_candles_received(data, idx)
                client.add_event_callback("candles_received", candles_received_wrapper)

                # Reinscrever assets após autenticação/reconexão
                async def authenticated_wrapper(data, account_idx=idx, auth_client=client):
                    # Logar autenticação
                    if hasattr(auth_client, '_ws_logger') and auth_client._ws_logger:
                        try:
                            await auth_client._ws_logger.log_authenticated({
                                "account_idx": account_idx,
                                "data_keys": list(data.keys()) if isinstance(data, dict) else None
                            })
                        except:
                            pass
                    # Só inscrever se já houver assets configurados
                    if account_idx in self._monitored_assets_by_account and self._monitored_assets_by_account[account_idx]:
                        await self._subscribe_account_assets(account_idx, auth_client)
                client.add_event_callback("authenticated", authenticated_wrapper)

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[MONITORAMENTO #{idx+1}] Falha ao conectar cliente ATIVOS #{idx+1}: {e}")

        # Buscar todos os assets com payout >= 92% (mesmo critério do rebalanceamento)
        all_assets = await self._get_top_assets_by_payout(min_payout=92.0)

        if not all_assets:
            logger.warning("Nenhum asset encontrado no banco de dados")
            return

        logger.info(f"[INIT] Encontrados {len(all_assets)} assets com payout >= 92%")
        logger.info(f"[INIT] Top ativos: {[asset.symbol for asset in all_assets[:15]]}")

        # Distribuir assets entre as contas (10 por conta)
        assets_per_account = 10
        num_accounts = len(self.ativos_clients)
        
        logger.info(f"[INIT] Número de contas ATIVOS: {num_accounts}")

        for account_idx in range(num_accounts):
            # Selecionar assets disponíveis (pular ativos indisponíveis)
            available_assets = []
            unavailable_assets = []
            
            for asset in all_assets:
                # Pular ativos conhecidos como indisponíveis
                if asset.symbol in ["#AMZN_otc", "#FDX_otc"]:
                    unavailable_assets.append(asset.symbol)
                    continue
                
                available_assets.append(asset)
                
                if len(available_assets) >= assets_per_account:
                    break
            
            logger.info(f"[INIT] Conta {account_idx}: {len(available_assets)} ativos disponíveis após filtro")
            
            if len(available_assets) < assets_per_account:
                account_name = self._get_account_name(account_idx)
                logger.warning(
                    f"[INIT] {account_name}: apenas {len(available_assets)} assets disponíveis "
                    f"(indisponíveis: {unavailable_assets})"
                )
            
            start_idx = account_idx * assets_per_account
            end_idx = start_idx + min(assets_per_account, len(available_assets))
            
            logger.info(f"[INIT] Conta {account_idx}: start_idx={start_idx}, end_idx={end_idx}")

            if start_idx >= len(available_assets):
                account_name = self._get_account_name(account_idx)
                logger.info(f"[INIT] {account_name}: sem assets suficientes para monitorar")
                continue

            account_assets = available_assets[start_idx:end_idx]
            client = self.ativos_clients[account_idx]

            account_name = self._get_account_name(account_idx)
            logger.info(f"[INIT] {account_name}: selecionados {len(account_assets)} assets: {[a.symbol for a in account_assets]}")

            # Rastrear ativos monitorados por conta
            self._monitored_assets_by_account[account_idx] = [asset.symbol for asset in account_assets]

            # Inscrever assets no websocket (apenas quando conectado)
            subscribed_count = await self._subscribe_account_assets(account_idx, client)

            if subscribed_count < len(account_assets):
                account_name = self._get_account_name(account_idx)
                logger.warning(
                    f"{account_name}: apenas {subscribed_count}/{len(account_assets)} assets inscritos"
                )
            
            if unavailable_assets:
                logger.warning(f"Ativos indisponíveis ignorados: {unavailable_assets}")

        logger.success(f"Monitoramento de ativos iniciado com {num_accounts} contas")

        # Iniciar tarefa de monitoramento contínuo
        self._ativos_monitoring_task = asyncio.create_task(self._ativos_monitoring_loop())

        # Iniciar tarefa para logar fechamentos de velas agrupados
        self._log_candle_closes_task = asyncio.create_task(self._log_candle_closes_loop())

    async def _subscribe_account_assets(
        self,
        account_idx: int,
        client: AsyncPocketOptionClient,
    ) -> int:
        """Inscrever todos os ativos monitorados por uma conta no websocket."""
        assets = self._monitored_assets_by_account.get(account_idx, [])
        if not assets:
            account_name = self._get_account_name(account_idx)
            logger.warning(
                f"{account_name}: nenhum asset configurado para inscrição"
            )
            return 0

        if not client or not client.is_connected:
            account_name = self._get_account_name(account_idx)
            logger.warning(
                f"{account_name}: cliente desconectado, pulando inscrição de {len(assets)} assets"
            )
            return 0

        subscribed_count = 0
        for symbol in assets:
            try:
                if await self._subscribe_asset(client, symbol):
                    subscribed_count += 1
                await asyncio.sleep(0.2)  # Pequeno delay entre inscrições
            except Exception as e:
                logger.error(f"[ERROR] Falha ao inscrever {symbol}: {e}")

        if subscribed_count:
            account_name = self._get_account_name(account_idx)
            logger.success(
                f"[OK] {subscribed_count} assets inscritos na {account_name}"
            )

        return subscribed_count

    async def _subscribe_asset(self, client: AsyncPocketOptionClient, asset_symbol: str):
        """Inscrever um ativo para receber atualizações de preços via websocket"""
        # Usar changeSymbol para inscrever no ativo
        data = {
            "asset": asset_symbol,
            "period": 1  # Timeframe de 1 segundo para atualizações rápidas
        }
        message_data = ["changeSymbol", data]
        message = f'42{json.dumps(message_data)}'

        # Enviar mensagem via websocket
        sent = False
        if hasattr(client, '_keep_alive_manager') and client._keep_alive_manager:
            sent = await client._keep_alive_manager.send_message(message)
        elif hasattr(client, '_websocket'):
            await client._websocket.send_message(message)
            sent = True

        if sent:
            logger.debug(f"[OK] Inscrevendo em {asset_symbol}")
            # Solicitar dados históricos após inscrição bem-sucedida
            await self._request_historical_data(client, asset_symbol)
        else:
            logger.warning(f"[WARNING] Falha ao inscrever {asset_symbol} (conexão indisponível)")

        return sent

    async def _request_historical_data(self, client: AsyncPocketOptionClient, asset_symbol: str):
        """Solicitar dados históricos para um ativo"""
        try:
            # Solicitar histórico de candles (últimos 100 candles de 1 segundo)
            data = {
                "asset": asset_symbol,
                "period": 1,
                "count": 100
            }
            message_data = ["get_candles", data]
            message = f'42{json.dumps(message_data)}'

            if hasattr(client, '_keep_alive_manager') and client._keep_alive_manager:
                await client._keep_alive_manager.send_message(message)
                logger.debug(f"[OK] Dados históricos solicitados para {asset_symbol}")
            elif hasattr(client, '_websocket'):
                await client._websocket.send_message(message)
                logger.debug(f"[OK] Dados históricos solicitados para {asset_symbol}")
        except Exception as e:
            logger.error(f"[ERROR] Falha ao solicitar dados históricos para {asset_symbol}: {e}")
    
    async def _unsubscribe_asset(self, client: AsyncPocketOptionClient, asset_symbol: str):
        """Desinscrever um ativo do websocket"""
        logger.info(f"[Unsubscribe] Tentando desinscrever de {asset_symbol}...")
        
        # Usar changeSymbol com asset vazio para desinscrever
        data = {
            "asset": "",
            "period": 1
        }
        message_data = ["changeSymbol", data]
        message = f'42{json.dumps(message_data)}'
        
        # Enviar mensagem via websocket
        sent = False
        if hasattr(client, '_keep_alive_manager') and client._keep_alive_manager:
            try:
                await client._keep_alive_manager.send_message(message)
                sent = True
                logger.info(f"[Unsubscribe] [OK] Mensagem de unsubscribe enviada para {asset_symbol}")
            except Exception as e:
                logger.error(f"[Unsubscribe] [ERROR] Erro ao enviar via keep_alive_manager: {e}")
        elif hasattr(client, '_websocket'):
            try:
                await client._websocket.send_message(message)
                sent = True
                logger.info(f"[Unsubscribe] [OK] Mensagem de unsubscribe enviada para {asset_symbol}")
            except Exception as e:
                logger.error(f"[Unsubscribe] [ERROR] Erro ao enviar via websocket: {e}")
        
        if not sent:
            logger.error(f"[Unsubscribe] [ERROR] Não foi possível enviar mensagem de unsubscribe para {asset_symbol}")
        
        logger.debug(f"[ERROR] Desinscrevendo de {asset_symbol}")
    
    async def _rebalance_assets(self):
        """Rebalancear ativos monitorados baseado em payout (deve ser 92%)
        
        Lógica:
        1. Identificar ativos ruins (payout < 92%) e SEMPRE removê-los
        2. Adicionar novos ativos bons apenas se necessário e disponíveis
        """
        try:
            logger.info("[Rebalance] Iniciando rebalanceamento de ativos...")

            # Buscar top 30 ativos com payout >= 92%
            top_30_assets = await self._get_top_assets_by_payout(limit=30, min_payout=92.0)

            if not top_30_assets:
                logger.warning("[Rebalance] Nenhum asset encontrado no banco de dados com payout >= 92%")
                return

            logger.info(f"[Rebalance] Top 30 ativos encontrados: {[asset.symbol for asset in top_30_assets[:5]]}...")

            # Criar conjunto de todos os símbolos no top 30
            top_30_symbols = set(asset.symbol for asset in top_30_assets)

            # Criar conjunto de todos os ativos monitorados por todas as contas
            all_monitored_symbols = set()
            for account_idx, symbols in self._monitored_assets_by_account.items():
                all_monitored_symbols.update(symbols)

            logger.info(f"[Rebalance] Ativos monitorados atualmente: {all_monitored_symbols}")

            # Para cada conta, processar rebalanceamento
            for account_idx, client in enumerate(self.ativos_clients):
                if account_idx not in self._monitored_assets_by_account:
                    continue

                monitored_symbols = list(self._monitored_assets_by_account[account_idx])  # Copia para modificação
                account_name = self._get_account_name(account_idx)
                logger.info(f"[Rebalance] {account_name}: monitorando {len(monitored_symbols)} ativos: {monitored_symbols}")

                # === FASE 1: REMOVER ATIVOS RUINS (SEMPRE) ===
                bad_assets = [symbol for symbol in monitored_symbols if symbol not in top_30_symbols]
                
                if bad_assets:
                    logger.info(f"[Rebalance] {account_name}: {len(bad_assets)} ativos ruins encontrados: {bad_assets}")
                    
                    for bad_symbol in bad_assets:
                        try:
                            # Remover do rastreamento PRIMEIRO
                            logger.debug(f"[Rebalance] Removendo {bad_symbol} do rastreamento da {account_name}")
                            self._monitored_assets_by_account[account_idx].remove(bad_symbol)
                            all_monitored_symbols.discard(bad_symbol)  # Remove se existir
                            
                            # Limpar buffers de candles para este ativo
                            if bad_symbol in self._candle_buffers:
                                del self._candle_buffers[bad_symbol]
                                logger.debug(f"[Rebalance] Buffers de candles limpos para {bad_symbol}")
                            
                            if bad_symbol in self._last_candle_close:
                                del self._last_candle_close[bad_symbol]
                            
                            # Desinscrever do websocket
                            logger.info(f"[Rebalance] Desinscrevendo de {bad_symbol}...")
                            await self._unsubscribe_asset(client, bad_symbol)
                            logger.info(f"[Rebalance] [OK] Desinscrito de {bad_symbol}")
                            
                            # Apagar arquivo local do ativo ruim
                            logger.info(f"[Rebalance] Apagando arquivo de {bad_symbol}...")
                            deleted = await local_storage.delete_asset_file(bad_symbol)
                            if deleted:
                                logger.info(f"[Rebalance] [OK] Arquivo de {bad_symbol} apagado")
                            else:
                                logger.warning(f"[Rebalance] [WARN] Arquivo de {bad_symbol} não encontrado ou erro ao apagar")
                            
                            logger.info(f"[Rebalance] {account_name}: ativo ruim {bad_symbol} completamente removido")
                            
                        except Exception as e:
                            logger.error(f"[ERROR] Falha ao remover ativo ruim {bad_symbol}: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
                else:
                    logger.info(f"[Rebalance] {account_name}: nenhum ativo ruim encontrado (todos >= 92%)")

                # === FASE 1.5: REMOVER ATIVOS INATIVOS (sem ticks por mais de X segundos) ===
                current_time = time.time()
                inactive_assets = []
                for symbol in monitored_symbols:
                    last_tick = self._last_tick_time.get(symbol)
                    if last_tick is None:
                        # Ativo foi inscrito mas nunca recebeu tick
                        inactive_assets.append(symbol)
                        logger.warning(f"[Rebalance] {symbol}: NUNCA recebeu ticks desde a inscrição")
                    elif (current_time - last_tick) > self._asset_inactivity_threshold_seconds:
                        # Ativo não recebe ticks há mais do que o threshold
                        inactive_assets.append(symbol)
                        logger.warning(f"[Rebalance] {symbol}: INATIVO - último tick há {current_time - last_tick:.0f}s")
                
                if inactive_assets:
                    logger.info(f"[Rebalance] {account_name}: {len(inactive_assets)} ativos inativos encontrados: {inactive_assets}")
                    
                    for inactive_symbol in inactive_assets:
                        try:
                            # Remover do rastreamento (verificar se existe primeiro)
                            logger.debug(f"[Rebalance] Removendo ativo inativo {inactive_symbol} do rastreamento")
                            if inactive_symbol in self._monitored_assets_by_account[account_idx]:
                                self._monitored_assets_by_account[account_idx].remove(inactive_symbol)
                            all_monitored_symbols.discard(inactive_symbol)
                            
                            # Limpar buffers
                            if inactive_symbol in self._candle_buffers:
                                del self._candle_buffers[inactive_symbol]
                            if inactive_symbol in self._last_candle_close:
                                del self._last_candle_close[inactive_symbol]
                            if inactive_symbol in self._last_tick_time:
                                del self._last_tick_time[inactive_symbol]
                            
                            # Desinscrever
                            logger.info(f"[Rebalance] Desinscrevendo de ativo inativo {inactive_symbol}...")
                            await self._unsubscribe_asset(client, inactive_symbol)
                            
                            # Apagar arquivo
                            deleted = await local_storage.delete_asset_file(inactive_symbol)
                            if deleted:
                                logger.info(f"[Rebalance] [OK] Arquivo de {inactive_symbol} apagado")
                            
                            logger.info(f"[Rebalance] {account_name}: ativo inativo {inactive_symbol} removido")
                            
                        except Exception as e:
                            logger.error(f"[ERROR] Falha ao remover ativo inativo {inactive_symbol}: {e}")
                
                # Recalcular lista após remoção de inativos
                monitored_symbols = list(self._monitored_assets_by_account[account_idx])
                
                # === FASE 3: ADICIONAR NOVOS ATIVOS BONS (se necessário) ===
                current_count = len(self._monitored_assets_by_account[account_idx])
                
                if current_count < 10:
                    needed = 10 - current_count
                    logger.warning(f"[Rebalance] {account_name}: apenas {current_count} ativos monitorados, precisa de {needed} mais")
                    
                    # Identificar ativos disponíveis (bons e não monitorados)
                    available_symbols = list(top_30_symbols - all_monitored_symbols)
                    
                    if available_symbols:
                        logger.info(f"[Rebalance] {account_name}: {len(available_symbols)} ativos bons disponíveis: {available_symbols[:5]}...")
                        
                        # Adicionar até completar 10
                        for i in range(min(needed, len(available_symbols))):
                            better_symbol = available_symbols[i]
                            
                            try:
                                # Adicionar ao rastreamento
                                self._monitored_assets_by_account[account_idx].append(better_symbol)
                                all_monitored_symbols.add(better_symbol)
                                
                                # Inscrever no ativo
                                logger.info(f"[Rebalance] Inscrevendo em {better_symbol}...")
                                await self._subscribe_asset(client, better_symbol)
                                logger.info(f"[Rebalance] [OK] Inscrito em {better_symbol}")
                                
                                logger.info(f"[Rebalance] {account_name}: adicionado {better_symbol}")
                                
                                await asyncio.sleep(0.2)  # Pequeno delay entre inscrições
                            except Exception as e:
                                logger.error(f"[ERROR] Falha ao adicionar {better_symbol}: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                    else:
                        logger.warning(f"[Rebalance] {account_name}: nenhum ativo bom disponível para adicionar")

                # Log final da conta
                final_count = len(self._monitored_assets_by_account[account_idx])
                final_assets = self._monitored_assets_by_account[account_idx]
                logger.info(f"[Rebalance] {account_name}: rebalanceamento concluído - {final_count} ativos: {final_assets}")

        except Exception as e:
            logger.error(f"Erro ao rebalancear ativos: {e}")
            import traceback
            traceback.print_exc()
    
    async def _on_ativos_stream_update(self, data: Any, account_idx: int):
        """Processar atualizações de stream de preços dos ativos"""
        try:
            # Verificar diferentes formatos de dados
            
            # Formato 1: Lista de ticks [["symbol", timestamp, price], ...]
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        symbol = item[0]
                        timestamp = item[1]
                        price = item[2]
                        
                        # Adicionar ao buffer
                        await self._add_tick_to_buffer(account_idx, symbol, price, timestamp)
                        
                        # Atualizar buffer de candles e verificar fechamento de vela
                        await self._update_candle_buffer(symbol, timestamp, price)
            
            # Formato 2: Dict com candles como no código original
            elif isinstance(data, dict):
                asset = data.get("asset")
                period = data.get("period")
                candles_data = data.get("data") or data.get("candles")
                
                if asset and period and candles_data:
                    # Extrair o preço atual (último candle)
                    if isinstance(candles_data, list) and len(candles_data) > 0:
                        last_candle = candles_data[-1]
                        if isinstance(last_candle, list) and len(last_candle) >= 2:
                            timestamp = last_candle[0]
                            price = last_candle[2]  # Close price
                            
                            # Adicionar ao buffer
                            await self._add_tick_to_buffer(account_idx, asset, price, timestamp)
                            
                            # Atualizar buffer de candles e verificar fechamento de vela
                            await self._update_candle_buffer(asset, timestamp, price)
        except Exception as e:
            logger.error(f"Erro ao processar stream update da conta #{account_idx}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _update_candle_buffer(self, symbol: str, timestamp: float, price: float):
        """Atualizar buffer de candles e verificar fechamento de vela"""
        try:
            # Converter timestamp para segundos se estiver em milissegundos
            if timestamp > 10000000000:
                timestamp_seconds = timestamp / 1000
                logger.debug(f"🔍 [{symbol}] Timestamp convertido de ms para s: {timestamp} -> {timestamp_seconds}")
            else:
                timestamp_seconds = timestamp
            
            # REMOVIDO: Log de tick individual (muito verboso)
            # Apenas logar em DEBUG se houver velas fechadas (ver abaixo)
            
            # Inicializar buffers para o asset se necessário
            if symbol not in self._candle_buffers:
                self._candle_buffers[symbol] = {}
                self._last_candle_close[symbol] = {}
                logger.debug(f"🔧 [{symbol}] Buffers criados")
            
            # Obter timeframes configurados (cache) - não recarregar em cada tick
            configured_timeframes = await self._get_configured_timeframes_cache()
            
            closed_candles = []  # Track closed candles for single log line
            
            # Verificar cada timeframe
            for timeframe_name, timeframe_seconds in self.timeframes.items():
                # Filtrar: apenas executar estratégias para timeframes configurados
                if configured_timeframes and timeframe_seconds not in configured_timeframes:
                    continue
                
                # Calcular o timestamp de fechamento da vela atual
                candle_start = int(timestamp_seconds // timeframe_seconds) * timeframe_seconds
                candle_close_time = candle_start + timeframe_seconds

                # Inicializar buffer para este timeframe se necessário
                if timeframe_seconds not in self._candle_buffers[symbol]:
                    self._candle_buffers[symbol][timeframe_seconds] = []
                    self._last_candle_close[symbol][timeframe_seconds] = None

                last_close_time = self._last_candle_close[symbol].get(timeframe_seconds)

                if last_close_time is None:
                    # Inicialização: registrar o início da vela atual sem disparar fechamento
                    self._last_candle_close[symbol][timeframe_seconds] = candle_close_time
                elif candle_close_time > last_close_time:
                    # Vela fechou (cruzou o limite do timeframe)
                    close_time_int = int(candle_close_time)

                    if timeframe_seconds not in self._candle_closes:
                        self._candle_closes[timeframe_seconds] = {}

                    if close_time_int not in self._candle_closes[timeframe_seconds]:
                        self._candle_closes[timeframe_seconds][close_time_int] = []

                    if symbol not in self._candle_closes[timeframe_seconds][close_time_int]:
                        self._candle_closes[timeframe_seconds][close_time_int].append(symbol)

                    closed_candles.append(timeframe_name)
                    self._last_candle_close[symbol][timeframe_seconds] = candle_close_time
                elif candle_close_time < last_close_time:
                    logger.warning(f"⏪ [{symbol}] {timeframe_name}: Timestamp regressivo ({candle_close_time} < {last_close_time})")
                
                # Atualizar buffer de candles (criar/atualizar candle atual)
                await self._update_current_candle(symbol, timeframe_seconds, timestamp_seconds, price)
            
            # REMOVIDO: Log de velas fechadas (muito verboso)
            # if closed_candles:
            #     logger.info(f"🕯️ [{symbol}] Velas fechadas: {', '.join(closed_candles)}")
                
        except Exception as e:
            logger.error(f"Erro ao atualizar buffer de candles para {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _update_current_candle(self, symbol: str, timeframe_seconds: int, timestamp: float, price: float):
        """Atualizar candle atual no buffer"""
        try:
            buffers = self._candle_buffers.get(symbol, {})
            buffer = buffers.get(timeframe_seconds, [])
            
            # Calcular timestamp de fechamento da vela
            candle_start = int(timestamp // timeframe_seconds) * timeframe_seconds
            candle_close_time = candle_start + timeframe_seconds
            
            # Verificar se já existe candle para este fechamento (O(1) com dict)
            existing_candle = None
            candle_dict = {candle['close_time']: candle for candle in buffer}
            existing_candle = candle_dict.get(candle_close_time)
            
            if existing_candle:
                # Atualizar candle existente
                existing_candle['close'] = price
                existing_candle['high'] = max(existing_candle['high'], price)
                existing_candle['low'] = min(existing_candle['low'], price)
            else:
                # Criar novo candle
                new_candle = {
                    'close_time': candle_close_time,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 0
                }
                buffer.append(new_candle)
                
                # Manter apenas últimos 200 candles
                if len(buffer) > 200:
                    buffer.pop(0)
            
            self._candle_buffers[symbol][timeframe_seconds] = buffer
            
        except Exception as e:
            logger.error(f"Erro ao atualizar candle atual: {e}")

    async def _get_configured_timeframes_cache(self) -> Set[int]:
        """Obter timeframes configurados do cache (otimização para não recarregar em cada tick)."""
        current_time = time.time()

        if self._configured_timeframes is not None and (current_time - self._config_last_updated) < self._config_cache_duration:
            return set(self._configured_timeframes)

        try:
            all_configs = await self._get_all_autotrade_configs()
            configured_timeframes = {
                config.get("timeframe")
                for configs in all_configs.values()
                for config in configs
                if config.get("is_active") and config.get("timeframe") is not None
            }

            if not configured_timeframes:
                self._configured_timeframes = set()
                self._configured_timeframe = None
                self._config_last_updated = current_time
                return set()

            self._configured_timeframes = configured_timeframes
            self._configured_timeframe = min(configured_timeframes)
            self._config_last_updated = current_time

            if len(configured_timeframes) > 1:
                logger.info(f"[LIST] Timeframes configurados ativos: {sorted(configured_timeframes)}")

            return configured_timeframes
        except Exception as e:
            logger.error(f"Erro ao obter timeframes configurados do cache: {e}")
            return set()

    def _get_signal_metrics(self, signal: Signal, total_indicators: int) -> Dict[str, Any]:
        """Calcular métricas de confluência e votos para um sinal."""
        indicators = signal.indicators or []
        
        # Para CustomStrategy (lista de dicts com 'signal')
        buy_votes = sum(1 for ind in indicators if str(ind.get("signal", "")).upper() == "BUY")
        sell_votes = sum(1 for ind in indicators if str(ind.get("signal", "")).upper() == "SELL")
        max_agreeing = max(buy_votes, sell_votes)
        # Evitar divisão por zero
        resolved_total = max(total_indicators, max(len(indicators), 1))

        confluence = signal.confluence
        if confluence is None:
            confluence = (max_agreeing / resolved_total) * 100 if resolved_total > 0 else 0.0

        return {
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "agreeing": max_agreeing,
            "total_indicators": resolved_total,
            "confluence": confluence or 0.0,
        }

    def _calculate_price_range_score(
        self,
        symbol: str,
        timeframe_seconds: int,
        window: int = 5
    ) -> float:
        """Calcular movimento médio por candle (menor = mais consistente)."""
        buffer = self._candle_buffers.get(symbol, {}).get(timeframe_seconds, [])
        if len(buffer) < 2:
            return 0.0

        recent = buffer[-window:] if window and len(buffer) > window else buffer
        closes = [candle.get("close") for candle in recent if candle.get("close") is not None]
        if len(closes) < 2:
            return 0.0

        total_movement = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
        return total_movement / max(len(closes), 1)

    async def _collect_all_signals_and_execute_best(self, timeframe_seconds: int):
        """Coletar sinais de todos os ativos e executar apenas o melhor sinal

        Args:
            timeframe_seconds: Timeframe em segundos
        """
        try:
            # 🚨 VERIFICAÇÃO CRÍTICA: Só emitir sinais se conexão WS estiver ativa
            # Verificar se pelo menos um cliente ATIVOS está conectado e recebendo ticks
            has_active_connection = False
            for account_idx, client in enumerate(self.ativos_clients):
                if hasattr(client, 'is_connected') and client.is_connected:
                    # Verificar se está recebendo ticks (health status)
                    if account_idx in self._client_health_status:
                        health = self._client_health_status[account_idx]
                        if health.get('is_connected', False):
                            has_active_connection = True
                            break
            
            if not has_active_connection:
                logger.warning(
                    f"⏸️ [SINAIS] Timeframe {timeframe_seconds}s - Nenhuma conexão WS ativa. "
                    f"Sinais NÃO serão emitidos até a conexão ser estabelecida."
                )
                return
            
            # Obter timeframes configurados
            configured_timeframes = await self._get_configured_timeframes_cache()

            # Verificar se este timeframe está configurado
            if not configured_timeframes or timeframe_seconds not in configured_timeframes:
                logger.debug(f"⏭️ Timeframe {timeframe_seconds}s não configurado, ignorando")
                return

            logger.info(f"🔍 Coletando sinais de todos os ativos para timeframe {timeframe_seconds}s...")

            # Coletar sinais de todos os ativos
            all_signals = []

            # Obter todos os ativos que estão sendo monitorados
            for symbol in list(self._candle_buffers.keys()):
                # === VERIFICAÇÃO: Ignorar ativos que não estão mais sendo monitorados ===
                # Verificar se o símbolo ainda está na lista de ativos monitorados
                is_still_monitored = False
                for account_idx, monitored_symbols in self._monitored_assets_by_account.items():
                    if symbol in monitored_symbols:
                        is_still_monitored = True
                        break
                
                if not is_still_monitored:
                    # Ativo não está mais sendo monitorado - ignorar
                    logger.debug(f"⏭️ [{symbol}] Ativo não está mais na lista de monitorados, pulando")
                    continue
                
                # Verificar se tem buffer para este timeframe
                if timeframe_seconds in self._candle_buffers.get(symbol, {}):
                    # Executar estratégias e coletar sinal
                    results = await self._run_strategies(symbol, timeframe_seconds, collect_only=True)

                    if results:
                        for result in results:
                            if result and 'signal' in result:
                                all_signals.append(result)
                                account_id = result.get("account_id")
                                account_name = self._get_account_name_by_id(account_id) if account_id else "Unknown"
                                logger.info(
                                    f"[INFO] [{symbol}] Sinal coletado para {account_name}: "
                                    f"{result['signal'].signal_type.upper()} | confiança={result['signal'].confidence:.2f}"
                                )
            
            logger.info(f"[LIST] Total de sinais coletados: {len(all_signals)}")
            
            # Se não houver sinais, retornar
            if not all_signals:
                logger.info("[WARNING] Nenhum sinal encontrado")
                return

            payout_map: Dict[str, float] = {}
            symbols = [result.get("symbol") for result in all_signals if result.get("symbol")]
            if symbols:
                async with get_db_context() as db:
                    payout_result = await db.execute(
                        select(Asset.symbol, Asset.payout).where(Asset.symbol.in_(symbols))
                    )
                    payout_map = {
                        symbol: payout or 0.0
                        for symbol, payout in payout_result.all()
                    }

            for result in all_signals:
                signal = result["signal"]
                config = result["config"]
                account_id = result.get("account_id")
                symbol = result["symbol"]
                total_indicators = len(config.get("indicators") or [])
                metrics = self._get_signal_metrics(signal, total_indicators)
                payout = payout_map.get(symbol, 0.0)
                movement_score = self._calculate_price_range_score(symbol, timeframe_seconds)

                result["score"] = {
                    "confluence": metrics["confluence"],
                    "payout": payout,
                    "confidence": signal.confidence or 0.0,
                    "movement": movement_score,
                }
                # Prioridade: 1) Confluência (porcentagem de indicadores concordando), 2) Confiança,
                # 3) Payout, 4) Menor movimento por candle (mais consistência)
                result["score_tuple"] = (
                    metrics["confluence"],
                    signal.confidence or 0.0,
                    payout,
                    -movement_score,
                )

                logger.info(
                    f"[CHART] [{symbol}] confluência={metrics['confluence']:.1f}% | conf={signal.confidence:.2f} | "
                    f"payout={payout:.1f}% | movimento/candle={movement_score:.5f}"
                )
            
            # Selecionar o melhor sinal por conta
            if not all_signals:
                logger.info("[WARNING] Nenhum sinal encontrado")
                return

            best_results: Dict[str, Dict[str, Any]] = {}
            for result in all_signals:
                account_id = result.get("account_id")
                if not account_id:
                    logger.warning("[WARNING] Sinal ignorado: account_id ausente")
                    continue
                if account_id not in best_results or result.get("score_tuple", (0, 0, 0, 0)) > best_results[account_id].get("score_tuple", (0, 0, 0, 0)):
                    best_results[account_id] = result

            if not best_results:
                logger.info("[WARNING] Nenhum sinal válido por conta")
                return

            # Processar trades em PARALELO para múltiplos usuários
            tasks = []
            for account_id, best_result in best_results.items():
                task = self._process_account_trade(account_id, best_result, timeframe_seconds)
                tasks.append(task)
            
            # Executar todos os trades simultaneamente
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(
                f"[CRITICAL] Erro ao coletar sinais e executar melhor trade: {e}",
                extra={
                    "user_name": "",
                    "account_id": "",
                    "account_type": ""
                }
            )
            import traceback
            logger.error(traceback.format_exc())

    async def _process_account_trade(self, account_id: str, best_result: Dict[str, Any], timeframe_seconds: int):
        """Processar trade para uma conta específica (executado em paralelo)"""
        signal = best_result["signal"]
        config = best_result["config"]
        symbol = best_result["symbol"]
        metrics = best_result["score"]
        payout = metrics.get("payout", 0)
        account_name = self._get_account_name_by_id(account_id)
        
        # Obter nome da estratégia para logs
        strategy_display_name = config.get('strategy_name', f"AutoTrade-{account_id[:8]}")

        logger.success(
            f"🏆 MELHOR SINAL PARA {account_name}: [{symbol}] {signal.signal_type.upper()} | "
            f"confluência={metrics.get('confluence', signal.confluence or 0):.1f}% | "
            f"confiança={signal.confidence:.2f} | payout={payout:.1f}%"
        )

        # Salvar signal no banco de dados
        try:
            async with get_db_context() as db:
                # Obter asset_id
                result = await db.execute(
                    select(Asset.id).where(Asset.symbol == symbol)
                )
                asset_id = result.scalar_one_or_none()

                if not asset_id:
                    mapped_asset_id = ASSETS.get(symbol)
                    if mapped_asset_id:
                        asset_id = mapped_asset_id
                        asset_result = await db.execute(
                            select(Asset).where(Asset.id == asset_id)
                        )
                        asset = asset_result.scalar_one_or_none()
                        if not asset:
                            asset = Asset(
                                id=asset_id,
                                symbol=symbol,
                                name=symbol,
                                type="unknown",
                                payout=payout,
                                is_active=True,
                            )
                            db.add(asset)
                            await db.flush()
                            logger.warning(
                                f"[WARNING] [{symbol}] Asset não encontrado; criado automaticamente (id={asset_id})"
                            )
                    else:
                        logger.warning(
                            f"[WARNING] [{symbol}] Asset não encontrado e sem mapeamento; sinal não salvo"
                        )
                        return

                # Obter strategy_id da configuração
                strategy_id = config.get('strategy_id')
                if not strategy_id:
                    logger.warning(f"[WARNING] [{symbol}] strategy_id ausente na configuração; sinal não salvo")
                    return

                signal.asset_id = asset_id
                signal.strategy_id = strategy_id
                signal.timeframe = timeframe_seconds
                
                db.add(signal)
                await db.commit()
                logger.info(f"[OK] [{symbol}] Sinal salvo no banco de dados")

                # Verificar se deve executar trade
                if signal.confidence >= config.get('min_confidence', 0.7):
                    logger.info(f"[INFO] [{symbol}] Confiança suficiente ({signal.confidence:.2f}), verificando payout...")
                    
                    # Validar payout antes de executar trade
                    if payout < 92.0:
                        logger.warning(f"[WARNING] [{symbol}] Payout muito baixo ({payout:.1f}%), trade não executado (mínimo: 92%)")
                        return
                    
                    # Verificar se o melhor sinal tem payout suficiente
                    if payout < 80.0:
                        logger.warning(
                        f"[WARNING] [{symbol}] Payout do melhor sinal ({payout:.1f}%) abaixo do mínimo (80%), trade não executado",
                        extra={
                            "user_name": self._get_account_name_by_id(account_id),
                            "account_id": account_id[:8] if account_id else "",
                            "account_type": ""
                        }
                    )
                        return
                    
                    logger.info(
                        f"[INFO] [{symbol}] Payout válido ({payout:.1f}%), verificando conexão WS...",
                        extra={
                            "user_name": self._get_account_name_by_id(account_id),
                            "account_id": account_id[:8] if account_id else "",
                            "account_type": ""
                        }
                    )
                    
                    # Verificar se existe conexão WS ativa antes de tentar executar trade
                    connection = self.trade_executor.connection_manager.get_connection(account_id, 'demo')
                    if not connection or not connection.is_connected:
                        connection = self.trade_executor.connection_manager.get_connection(account_id, 'real')

                    # Tentar reativar conexão sob demanda se necessário
                    if not connection or not connection.is_connected:
                        connection, _ = await self.trade_executor._get_connection_for_account_id(account_id)

                    if not connection or not connection.is_connected:
                        account_name_ws = self._get_account_name_by_id(account_id)
                        logger.warning(
                            f"[WARNING] [{symbol}] Sem conexão WS ativa para {account_name_ws}; trade não executado",
                            extra={
                                "user_name": account_name_ws,
                                "account_id": account_id[:8] if account_id else "",
                                "account_type": ""
                            }
                        )
                        return
                    
                    logger.info(
                        f"[INFO] [{symbol}] Conexão WS ativa encontrada, executando trade...",
                        extra={
                            "user_name": self._get_account_name_by_id(account_id),
                            "account_id": account_id[:8] if account_id else "",
                            "account_type": ""
                        }
                    )
                    
                    # Executar trade usando trade_executor em task separada
                    # para não bloquear o event loop principal (evita lagada no watchdog)
                    try:
                        trade_task = asyncio.create_task(
                            self.trade_executor.execute_trade(
                                signal=signal,
                                symbol=symbol,
                                timeframe_seconds=timeframe_seconds,
                                strategy_name=f"AutoTrade-{self._get_account_name_by_id(account_id)}",
                                account_id=account_id,
                                autotrade_config=config
                            )
                        )
                        
                        # Aguardar o trade com timeout para não bloquear indefinidamente
                        trade = await asyncio.wait_for(trade_task, timeout=30.0)
                        
                        if trade:
                            logger.success(
                                f"✅ [{symbol}] Trade executado com sucesso: {trade.id[:8]}...",
                                extra={
                                    "user_name": self._get_account_name_by_id(account_id),
                                    "account_id": account_id[:8] if account_id else "",
                                    "account_type": getattr(trade, "connection_type", "")
                                }
                            )
                            
                            # Log de execução de trade no arquivo do usuário
                            user_name = self._get_account_name_by_id(account_id)
                            user_logger.log_trade_execution(
                                username=user_name,
                                account_id=account_id,
                                asset=symbol,
                                strategy_name=strategy_display_name,
                                trade_data={
                                    'direction': signal.signal_type if isinstance(signal.signal_type, str) else signal.signal_type.value,
                                    'amount': trade.amount if hasattr(trade, 'amount') else 0,
                                    'duration': signal.timeframe if hasattr(signal, 'timeframe') else timeframe_seconds,
                                    'order_id': trade.id if hasattr(trade, 'id') else 'N/A'
                                },
                                result='pending'
                            )
                            
                            # Buscar chat_id do usuário para notificação (async)
                            user_chat_id = None
                            account_name = None
                            user_name = None
                            try:
                                account_result = await db.execute(
                                    select(Account.name, User.name, User.telegram_chat_id)
                                    .join(User, Account.user_id == User.id)
                                    .where(Account.id == account_id)
                                )
                                account_row = account_result.first()
                                if account_row:
                                    account_name = account_row[0]
                                    user_name = account_row[1]
                                    user_chat_id = account_row[2]
                                    logger.info(
                                        f"[OK] Chat ID encontrado: {user_chat_id} para conta {account_name}",
                                        extra={
                                            "user_name": user_name or "",
                                            "account_id": account_id[:8] if account_id else "",
                                            "account_type": ""
                                        }
                                    )
                                else:
                                    logger.warning(
                                        f"[WARNING] Chat ID não encontrado para account_id={account_id}",
                                        extra={
                                            "user_name": user_name or "",
                                            "account_id": account_id[:8] if account_id else "",
                                            "account_type": ""
                                        }
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Erro ao buscar dados do usuário: {e}",
                                    extra={
                                        "user_name": user_name or "",
                                        "account_id": account_id[:8] if account_id else "",
                                        "account_type": ""
                                    }
                                )

                            # Obter informações do soros/martingale
                            trade_amount = trade.amount if hasattr(trade, 'amount') else None
                            account_type = getattr(trade, "connection_type", None)
                            martingale_level = None
                            soros_level = None
                            strategy_name = None
                            try:
                                config_result = await db.execute(
                                    select(AutoTradeConfig.martingale_level, AutoTradeConfig.soros_level)
                                    .where(AutoTradeConfig.account_id == account_id)
                                )
                                config_row = config_result.first()
                                if config_row:
                                    martingale_level = config_row[0]
                                    soros_level = config_row[1]

                                if config.get('strategy_id'):
                                    strategy_result = await db.execute(
                                        select(Strategy.name).where(Strategy.id == config.get('strategy_id'))
                                    )
                                    strategy_name = strategy_result.scalar_one_or_none()
                            except Exception as e:
                                logger.error(
                                    f"Erro ao buscar martingale_level/soros_level/strategy_name: {e}",
                                    extra={
                                        "user_name": account_name,
                                        "account_id": account_id[:8] if account_id else "",
                                        "account_type": ""
                                    }
                                )

                            # Notificação de trade executado removida daqui - agora enviada pelo trade_executor.py para evitar duplicatas
                            logger.info(
                                f"[OK] Trade executado, notificação será enviada pelo TradeExecutor",
                                extra={
                                    "user_name": user_name or "",
                                    "account_id": account_id[:8] if account_id else "",
                                    "account_type": account_type or ""
                                }
                            )
                        else:
                            logger.warning(
                                f"[WARNING] [{symbol}] Trade não foi executado",
                                extra={
                                    "user_name": self._get_account_name_by_id(account_id),
                                    "account_id": account_id[:8] if account_id else "",
                                    "account_type": ""
                                }
                            )
                    except Exception as e:
                        logger.error(
                            f"[CRITICAL] [{symbol}] Erro ao executar trade: {e}",
                            extra={
                                "user_name": self._get_account_name_by_id(account_id),
                                "account_id": account_id[:8] if account_id else "",
                                "account_type": ""
                            }
                        )
                else:
                    logger.info(
                        f"[PAUSED] [{symbol}] Confiança {signal.confidence:.2f} abaixo do mínimo "
                        f"{config.get('min_confidence', 0.7):.2f}",
                        extra={
                            "user_name": self._get_account_name_by_id(account_id),
                            "account_id": account_id[:8] if account_id else "",
                            "account_type": ""
                        }
                    )
        except Exception as e:
            account_name_error = self._get_account_name_by_id(account_id) if account_id else "Unknown"
            logger.error(
                f"[CRITICAL] [{symbol}] Erro ao salvar sinal para {account_name_error}: {e}",
                extra={
                    "user_name": account_name_error,
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": ""
                }
            )
            import traceback
            logger.error(traceback.format_exc())

    async def _run_strategies(self, symbol: str, timeframe_seconds: int, collect_only: bool = False):
        """Executar estratégias para um asset e timeframe usando CustomStrategy com indicadores
        
        Args:
            symbol: Símbolo do asset
            timeframe_seconds: Timeframe em segundos
            collect_only: Se True, apenas coleta sinais sem executar trades
        """
        try:
            # 🚨 VALIDAÇÃO: Ativos oficiais (sem _otc) só aceitam trades >= 60s
            from services.pocketoption.constants import is_otc_asset
            if not is_otc_asset(symbol) and timeframe_seconds < 60:
                logger.debug(f"⏭️ [{symbol}] Ativo oficial (não-OTC) ignorado: timeframe {timeframe_seconds}s < 60s mínimo")
                return None

            # Carregar todas as configurações de autotrade ativas
            all_configs = await self._get_all_autotrade_configs()

            if not all_configs:
                logger.debug(f"[WARNING] [{symbol}] Nenhuma configuração de autotrade ativa")
                return None

            # Log para debug
            total_configs = sum(len(configs) for configs in all_configs.values())
            # logger.debug(f"[INFO] [{symbol}] {total_configs} configurações carregadas para {len(all_configs)} contas")

            # Filtrar configs para este timeframe
            configs_for_timeframe = []
            for account_id, configs in all_configs.items():
                for config in configs:
                    if config['is_active'] and config['timeframe'] == timeframe_seconds:
                        configs_for_timeframe.append({
                            'account_id': account_id,
                            'config': config
                        })

            if not configs_for_timeframe:
                logger.debug(f"[WARNING] [{symbol}] Nenhuma configuração ativa para timeframe {timeframe_seconds}s")
                return None

            # Verificar saldo de cada conta antes de gerar sinais
            configs_with_sufficient_balance = []
            for user_config in configs_for_timeframe:
                account_id = user_config['account_id']
                config = user_config['config']

                try:
                    async with get_db_context() as db:
                        result = await db.execute(
                            select(
                                Account.balance_demo,
                                Account.balance_real,
                                Account.name,
                                Account.autotrade_demo,
                                Account.autotrade_real
                            )
                            .where(Account.id == account_id)
                        )
                        account_data = result.first()

                        if account_data:
                            balance_demo = account_data[0]
                            balance_real = account_data[1]
                            account_name = account_data[2]
                            autotrade_demo = account_data[3]
                            autotrade_real = account_data[4]

                            # Determinar qual saldo usar (demo ou real)
                            # Verificar se a conta tem autotrade configurado para demo ou real
                            current_balance = balance_demo if autotrade_demo else balance_real

                            # Verificar saldo mínimo
                            min_balance = self.trade_executor.MIN_BALANCE_THRESHOLD if hasattr(self.trade_executor, 'MIN_BALANCE_THRESHOLD') else 10.0

                            if current_balance <= min_balance:
                                logger.warning(
                                    f"[WARNING] [{symbol}] {account_name}: "
                                    f"saldo insuficiente (${current_balance:.2f} <= ${min_balance:.2f}), DESATIVANDO AUTOTRADE"
                                )
                                # 🚨 DESATIVAR AUTOTRADE por saldo insuficiente
                                try:
                                    from models import AutoTradeConfig
                                    result_configs = await db.execute(
                                        select(AutoTradeConfig).where(AutoTradeConfig.account_id == account_id)
                                    )
                                    configs_to_disable = result_configs.scalars().all()
                                    for cfg in configs_to_disable:
                                        cfg.is_active = False
                                        cfg.updated_at = datetime.utcnow()
                                    await db.commit()
                                    logger.warning(f"🛑 Autotrade DESATIVADO para {account_name} por saldo insuficiente")
                                    
                                    # Desconectar WebSocket
                                    if hasattr(self, 'connection_manager') and self.connection_manager:
                                        await self.connection_manager.disconnect_connection(account_id, 'demo')
                                        await self.connection_manager.disconnect_connection(account_id, 'real')
                                        logger.info(f"✓ Conexões desconectadas para {account_name}")
                                except Exception as e:
                                    logger.error(f"Erro ao desativar autotrade por saldo insuficiente: {e}")
                                continue

                            configs_with_sufficient_balance.append(user_config)
                        else:
                            account_name_unknown = self._get_account_name_by_id(account_id)
                            logger.warning(f"[WARNING] [{symbol}] Conta {account_name_unknown} não encontrada, ignorando")

                except Exception as e:
                    account_name_error = self._get_account_name_by_id(account_id) if account_id else "Unknown"
                    logger.error(f"Erro ao verificar saldo da conta {account_name_error}: {e}")
                    continue

            if not configs_with_sufficient_balance:
                logger.debug(f"[WARNING] [{symbol}] Nenhuma configuração com saldo suficiente")
                return None

            # logger.info(f"[MONEY] [{symbol}] {len(configs_with_sufficient_balance)} configuração(ões) com saldo suficiente")

            # Obter buffer de candles
            buffers = self._candle_buffers.get(symbol, {})
            buffer = buffers.get(timeframe_seconds, [])
            
            # Se o buffer estiver vazio ou insuficiente, converter candles de 1s para este timeframe
            if len(buffer) < 12 and '1' in buffers:
                candles_1s = buffers['1']
                if len(candles_1s) >= 12:
                    # Converter candles de 1s para o timeframe solicitado
                    candles_timeframe = self._convert_candles_to_timeframe(candles_1s, timeframe_seconds)
                    if candles_timeframe:
                        # Inicializar buffer para este timeframe
                        if timeframe_seconds not in buffers:
                            buffers[timeframe_seconds] = []
                        # Adicionar candles ao buffer
                        for candle in candles_timeframe:
                            buffers[timeframe_seconds].append(candle)
                        # Manter apenas últimos 200 candles
                        if len(buffers[timeframe_seconds]) > 200:
                            buffers[timeframe_seconds] = buffers[timeframe_seconds][-200:]
                        # Atualizar buffer
                        buffer = buffers[timeframe_seconds]
                        # logger.info(f"[OK] [{symbol}] {len(candles_timeframe)} candles convertidos de 1s para {timeframe_seconds}s")

            if len(buffer) < 12:
                logger.warning(f"[WARNING] [{symbol}] Buffer insuficiente ({len(buffer)} < 12)")
                return None  # Precisa de pelo menos 12 candles

            # Converter buffer para DataFrame
            df = await self._buffer_to_dataframe(buffer)
            if df is None:
                logger.warning(f"[WARNING] [{symbol}] Falha ao converter buffer para DataFrame")
                return None

            # Converter DataFrame para lista de CandleDataResponse
            candle_data_list = []
            for idx, row in df.iterrows():
                candle_data_list.append(CandleDataResponse(
                    timestamp=idx,
                    open=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    volume=0
                ))
            
            # Criar CandleResponse com a lista de candles
            candles_response = CandleResponse(
                symbol=symbol,
                timeframe=timeframe_seconds,
                candles=candle_data_list
            )

            # Executar estratégias para cada configuração
            best_by_account: Dict[str, Dict[str, Any]] = {}
            best_scores: Dict[str, Tuple[float, float, float]] = {}

            for user_config in configs_with_sufficient_balance:
                account_id = user_config['account_id']
                config = user_config['config']
                strategy_id = config.get('strategy_id')

                # Verificar se o ativo está em cooldown para esta conta/estratégia
                if account_id and strategy_id:
                    if self._is_asset_in_cooldown(account_id, symbol, strategy_id):
                            # Adicionar logs detalhados sobre o cooldown
                        try:
                            if hasattr(self, '_asset_cooldowns'):
                                if (account_id in self._asset_cooldowns and
                                    symbol in self._asset_cooldowns[account_id] and
                                    strategy_id in self._asset_cooldowns[account_id][symbol]):
                                    import time
                                    current_time = time.time()
                                    cooldown_end = self._asset_cooldowns[account_id][symbol][strategy_id]
                                    remaining_time = cooldown_end - current_time
                                    cooldown_end_str = datetime.fromtimestamp(cooldown_end).strftime('%Y-%m-%d %H:%M:%S')
                                    account_name_cooldown = self._get_account_name_by_id(account_id)
                                    logger.info(f" [{symbol}] Ativo em cooldown para {account_name_cooldown}, ignorando. Tempo restante: {remaining_time:.1f}s (expira em: {cooldown_end_str})")
                                    logger.info(f"⏳ [{symbol}] Ativo em cooldown para {account_name_cooldown}, ignorando. Tempo restante: {remaining_time:.1f}s (expira em: {cooldown_end_str})")
                                    # Log no arquivo do usuário
                                    user_logger.log_cooldown(
                                        username=account_name_cooldown,
                                        asset=symbol,
                                        remaining_time=remaining_time,
                                        expires_at=cooldown_end_str
                                    )
                                else:
                                    account_name_cooldown2 = self._get_account_name_by_id(account_id)
                                    logger.info(f"⏳ [{symbol}] Ativo em cooldown para {account_name_cooldown2}, ignorando")
                            else:
                                account_name_cooldown3 = self._get_account_name_by_id(account_id)
                                logger.info(f"⏳ [{symbol}] Ativo em cooldown para {account_name_cooldown3}, ignorando")
                        except Exception as e:
                            account_name_cooldown4 = self._get_account_name_by_id(account_id)
                            logger.info(f"⏳ [{symbol}] Ativo em cooldown para {account_name_cooldown4}, ignorando")
                        continue

                # Criar CustomStrategy com indicadores da configuração
                from services.strategies.custom_strategy import CustomStrategy
                strategy_params = config.get('strategy_parameters') or {}
                if isinstance(strategy_params, str):
                    try:
                        import json
                        strategy_params = json.loads(strategy_params)
                    except:
                        strategy_params = {}
                user_name = self._get_account_name_by_id(account_id)
                strategy_display_name = config.get('strategy_name', f"AutoTrade-{account_id[:8]}")
                indicators_config = config.get('indicators', [])
                
                # Log indicadores configurados para debug - SILENCIADO
                indicator_types = [ind.get('type', 'unknown') for ind in indicators_config]
                # logger.info(f"📊 [USUÁRIO: {user_name}] Indicadores configurados: {indicator_types}")
                
                strategy = CustomStrategy(
                    name=strategy_display_name,
                    strategy_type="custom",
                    account_id=account_id,
                    parameters={
                        'min_confidence': config.get('min_confidence', strategy_params.get('min_confidence', 0.7)),
                        'required_signals': strategy_params.get('required_signals', 1),
                        'timeframe': config.get('timeframe', strategy_params.get('timeframe', 60))
                    },
                    assets=[symbol],
                    indicators=indicators_config,
                    user_name=user_name,
                    strategy_display_name=strategy_display_name
                )
                strategy_name = "CustomStrategy"

                timeframe_name = next((k for k, v in self.timeframes.items() if v == timeframe_seconds), f"{timeframe_seconds}s")


                # Executar estratégia
                signal = await strategy.analyze(candle_data_list, symbol)

                # Logar resultado da análise
                if signal:
                    logger.success(f"✅ [{symbol}] SINAL {signal.signal_type.upper()} gerado por {strategy_name} ({timeframe_name}) | confiança={signal.confidence:.2f}")
                    
                    # 🔄 ATUALIZAR last_activity da conta (sinal gerado = atividade!)
                    if hasattr(self, 'connection_manager') and self.connection_manager:
                        try:
                            await self.connection_manager.update_last_activity(account_id)
                        except Exception as e:
                            logger.debug(f"[{account_id[:8]}...] Erro ao atualizar last_activity: {e}")

                    total_indicators = len(config.get('indicators') or [])
                    metrics = self._get_signal_metrics(signal, total_indicators)
                    score_tuple = (
                        metrics["agreeing"],
                        metrics["confluence"],
                        signal.confidence or 0.0,
                    )

                    # Verificar se é o melhor sinal desta conta
                    current_best = best_scores.get(account_id)
                    if current_best is None or score_tuple > current_best:
                        best_scores[account_id] = score_tuple
                        best_by_account[account_id] = {
                            "signal": signal,
                            "config": config,
                            "account_id": account_id,
                            "strategy_id": config.get('strategy_id'),
                            "symbol": symbol,
                            "timeframe_seconds": timeframe_seconds,
                        }
                        account_name_best = self._get_account_name_by_id(account_id)
                        logger.info(
                            f"🏆 [{symbol}] Novo melhor sinal para {account_name_best}: {signal.signal_type.upper()} | "
                            f"confluência={metrics['confluence']:.1f}% | conf={signal.confidence:.2f}"
                        )
                        
                        # 💾 SALVAR O MELHOR SINAL NO BANCO DE DADOS
                        await self._save_best_signal_to_db(
                            account_id=account_id,
                            symbol=symbol,
                            signal=signal,
                            strategy_id=config.get('strategy_id'),
                            timeframe_seconds=timeframe_seconds,
                            metrics=metrics
                        )
                        
                        # 📝 LOGAR APENAS O MELHOR SINAL NO ARQUIVO DO USUÁRIO
                        user_logger.log_final_signal(
                            username=account_name_best,
                            account_id=account_id,
                            asset=symbol,
                            strategy_name=strategy_display_name,
                            direction=signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type),
                            confidence=signal.confidence,
                            confluence_score=getattr(signal, 'confluence', 0),
                            num_indicators=total_indicators
                        )
                else:
                    logger.debug(f" [{symbol}] Nenhum sinal gerado por {strategy_name}")

            # Retornar o melhor sinal por conta
            if best_by_account:
                return list(best_by_account.values())

            return None

        except Exception as e:
            logger.error(f"[CRITICAL] [{symbol}] Erro ao executar estratégias: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _buffer_to_dataframe(self, buffer: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
        """Converter buffer de candles para DataFrame"""
        if not buffer:
            return None

        try:
            data = []
            for candle in buffer:
                data.append({
                    'open': candle['open'],
                    'high': candle['high'],
                    'low': candle['low'],
                    'close': candle['close']
                })

            df = pd.DataFrame(data)

            # Adicionar volume sintético baseado na força de movimento do preço
            try:
                from services.analysis.indicators.synthetic_volume import add_synthetic_volume
                df = add_synthetic_volume(df, price_column='close')
                # logger.debug(f"✓ Volume sintético adicionado ao DataFrame ({len(df)} candles)")
            except Exception as e:
                logger.warning(f"⚠️ Não foi possível adicionar volume sintético: {e}")

            return df
        except Exception as e:
            logger.error(f"Erro ao converter buffer para DataFrame: {e}")
            return None

    async def _log_candle_closes_loop(self):
        """Loop para logar fechamentos de velas agrupados"""
        while self.is_running:
            try:
                await asyncio.sleep(0.2)  # Logar com maior precisão
                
                if not self.is_running:
                    break
                
                # Logar fechamentos agrupados por timeframe
                for timeframe_seconds in sorted(self._candle_closes.keys()):
                    for close_time_str, symbols in list(self._candle_closes[timeframe_seconds].items()):
                        if symbols:
                            # Encontrar o nome do timeframe
                            timeframe_name = None
                            for name, seconds in self.timeframes.items():
                                if seconds == timeframe_seconds:
                                    timeframe_name = name
                                    break


                            # Obter os timeframes configurados
                            configured_timeframes = await self._get_configured_timeframes_cache()

                            # Apenas coletar sinais e executar para timeframes configurados
                            if configured_timeframes and timeframe_seconds in configured_timeframes:
                                logger.info(f"🎯 Timeframe configurado: {timeframe_seconds}s - Coletando sinais...")
                                await self._collect_all_signals_and_execute_best(timeframe_seconds)
                                
                                # 🎯 EXECUTAR TRADES PENDENTES NO FECHAMENTO DA VELA
                                for symbol in symbols:
                                    await self._execute_pending_trades_on_candle_close(
                                        symbol, timeframe_seconds, float(close_time_str)
                                    )
                            else:
                                logger.debug(f"⏭️ Timeframe {timeframe_seconds}s não configurado, ignorando")

                            # Enviar atualizações via WebSocket para cada símbolo
                            if self._candle_update_callback:
                                close_time = int(close_time_str)

                                for symbol in symbols:
                                    try:
                                        # Obter o candle mais recente do buffer
                                        if symbol in self._candle_buffers and timeframe_seconds in self._candle_buffers[symbol]:
                                            candles = self._candle_buffers[symbol][timeframe_seconds]
                                            if candles:
                                                latest_candle = candles[-1]
                                                # Enviar atualização via callback
                                                callback_result = self._candle_update_callback(symbol, latest_candle)
                                                if asyncio.iscoroutine(callback_result):
                                                    await callback_result
                                    except Exception as e:
                                        logger.error(f"Erro ao enviar atualização de candle para {symbol}: {e}")
                            else:
                                logger.warning(f"[WARNING] Nenhum callback registrado para enviar atualizações de candles")

                            # Remover do buffer após logar
                            del self._candle_closes[timeframe_seconds][close_time_str]
                
            except asyncio.CancelledError:
                logger.info("Tarefa de log de fechamentos cancelada")
                break
            except Exception as e:
                logger.error(f"Erro ao logar fechamentos de velas: {e}")
                await asyncio.sleep(1)

    async def _on_ativos_candles_received(self, data: Dict[str, Any], account_idx: int):
        """Processar histórico de candles recebido dos ativos"""
        try:
            asset = data.get("asset")
            period = data.get("period")
            history = data.get("history", [])
            candles = data.get("candles", [])
            
            if not asset:
                return
            
            # Combinar history e candles se ambos existirem
            all_candles = history if history else candles
            
            if not all_candles:
                return
            
            # Obter o último timestamp salvo para este ativo (se existir)
            from_timestamp = None
            if hasattr(self, '_last_saved_timestamps') and asset in self._last_saved_timestamps:
                from_timestamp = self._last_saved_timestamps[asset]
            elif asset in self._last_candle_close and '1' in self._last_candle_close[asset]:
                from_timestamp = self._last_candle_close[asset]['1']
            
            # Logar informações sobre o histórico recebido
            time_str = datetime.now().strftime('%H:%M:%S')
            account_name = self._get_account_name(account_idx)
            
            # Verificar formato dos dados
            if all_candles and len(all_candles) > 0:
                first_candle = all_candles[0]
            
            logger.info(f"[CHART] [{account_name}] Histórico recebido: {asset} | {len(all_candles)} candles | período={period}s @ {time_str}")
            
            # Salvar histórico localmente
            await self.local_storage.save_history(asset, period, all_candles)
            
            # Converter ticks em candles OHLC e carregar no buffer (passando from_timestamp)
            await self._load_history_to_buffer(asset, period, all_candles, from_timestamp)
            
            # Adicionar ao buffer de históricos recebidos
            if account_idx not in self._received_histories:
                self._received_histories[account_idx] = []
            self._received_histories[account_idx].append({
                'asset': asset,
                'period': period,
                'candles_count': len(all_candles),
                'time': time_str
            })
            
            # Logar resumo agrupado se já recebeu 10 históricos
            if len(self._received_histories[account_idx]) >= 10:
                histories = self._received_histories[account_idx]
                assets = [h['asset'] for h in histories]
                total_candles = sum(h['candles_count'] for h in histories)
                account_name = self._get_account_name(account_idx)
                logger.info(f"[INFO] [{account_name}] {len(histories)} históricos recebidos: {' | '.join(assets)} | Total: {total_candles} candles")
                # Limpar buffer
                self._received_histories[account_idx] = []
            
            # Salvar candles no banco de dados (opcional - descomente se precisar)
            # await self._save_candles_to_db(asset, all_candles, period)
            
        except Exception as e:
            logger.error(f"Erro ao processar candles_received da conta #{account_idx}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _load_history_to_buffer(self, asset: str, period: int, ticks: List[List[float]], from_timestamp: Optional[float] = None):
        """Converter dados históricos em candles OHLC para todos os timeframes e carregar no buffer"""
        try:
            # Filtrar ticks após o último timestamp salvo (se fornecido)
            filtered_ticks = ticks
            if from_timestamp is not None:
                filtered_ticks = [tick for tick in ticks if tick[0] > from_timestamp]
                if filtered_ticks and len(filtered_ticks) < len(ticks):
                    logger.info(f"[INFO] [{asset}] Filtrados {len(ticks) - len(filtered_ticks)} ticks antigos, usando {len(filtered_ticks)} ticks novos")

            # Ordenar ticks por timestamp para evitar timestamp regressivo
            filtered_ticks.sort(key=lambda x: x[0])

            # Converter ticks em candles OHLC de 1s
            candles_1s = []
            for tick in filtered_ticks:
                timestamp = tick[0]
                price = tick[1]
                
                # Calcular timestamp de fechamento da vela de 1s
                candle_start = int(timestamp // 1) * 1
                candle_close_time = candle_start + 1
                
                # Verificar se já existe candle para este fechamento
                existing_candle = None
                for candle in candles_1s:
                    if candle['close_time'] == candle_close_time:
                        existing_candle = candle
                        break
                
                if existing_candle:
                    # Atualizar candle existente
                    existing_candle['close'] = price
                    existing_candle['high'] = max(existing_candle['high'], price)
                    existing_candle['low'] = min(existing_candle['low'], price)
                else:
                    # Criar novo candle
                    candles_1s.append({
                        'close_time': candle_close_time,
                        'open': price,
                        'high': price,
                        'low': price,
                        'close': price,
                        'volume': 0
                    })
            
            # Converter candles de 1s em candles de timeframes maiores
            for timeframe_seconds in [3, 5, 30, 60, 300, 900, 3600, 14400, 86400]:
                candles_timeframe = self._convert_candles_to_timeframe(candles_1s, timeframe_seconds)
                
                if candles_timeframe:
                    # Carregar no buffer
                    if asset not in self._candle_buffers:
                        self._candle_buffers[asset] = {}
                    if timeframe_seconds not in self._candle_buffers[asset]:
                        self._candle_buffers[asset][timeframe_seconds] = []
                    
                    # Inicializar _last_candle_close para este asset e timeframe
                    if asset not in self._last_candle_close:
                        self._last_candle_close[asset] = {}
                    if timeframe_seconds not in self._last_candle_close[asset]:
                        self._last_candle_close[asset][timeframe_seconds] = None
                    
                    # Adicionar candles ao buffer
                    for candle in candles_timeframe:
                        self._candle_buffers[asset][timeframe_seconds].append(candle)
                    
                    # Manter apenas últimos 200 candles
                    if len(self._candle_buffers[asset][timeframe_seconds]) > 200:
                        self._candle_buffers[asset][timeframe_seconds] = self._candle_buffers[asset][timeframe_seconds][-200:]
                    
                    logger.info(f"[OK] [{asset}] {len(candles_timeframe)} candles carregados para timeframe {timeframe_seconds}s")
            
            logger.info(f"[OK] [{asset}] Dados históricos carregados no buffer para todos os timeframes")
            
        except Exception as e:
            logger.error(f"Erro ao carregar dados históricos para {asset}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _on_ativos_stream_update(self, data: Any, account_idx: int):
        """Processar atualizações de stream de ativos"""
        try:
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        symbol = item[0]
                        timestamp = item[1]
                        price = item[2]
                        
                        # Converter para float se necessário
                        try:
                            if isinstance(timestamp, str):
                                timestamp = float(timestamp)
                            if isinstance(price, str):
                                price = float(price)
                        except (ValueError, TypeError):
                            continue
                        
                        # Adicionar ao buffer
                        await self._add_tick_to_buffer(account_idx, symbol, price, timestamp)
        except Exception as e:
            logger.error(f"Erro ao processar stream update da conta #{account_idx}: {e}")
    
    def _convert_candles_to_timeframe(self, candles_1s: List[Dict], target_timeframe: int) -> List[Dict]:
        """Converter candles de 1s para candles de timeframe maior"""
        try:
            if not candles_1s:
                return []
            
            # Agrupar candles de 1s pelo timestamp de fechamento do timeframe alvo
            timeframe_groups = {}
            
            for candle in candles_1s:
                # Calcular timestamp de fechamento do timeframe alvo
                candle_close_time = candle['close_time']
                candle_start = (candle_close_time // target_timeframe) * target_timeframe
                timeframe_close_time = candle_start + target_timeframe
                
                if timeframe_close_time not in timeframe_groups:
                    timeframe_groups[timeframe_close_time] = []
                
                timeframe_groups[timeframe_close_time].append(candle)
            
            # Criar candles do timeframe alvo
            candles_timeframe = []
            for close_time, group in sorted(timeframe_groups.items()):
                # Criar candle OHLC a partir do grupo
                opens = [c['open'] for c in group]
                highs = [c['high'] for c in group]
                lows = [c['low'] for c in group]
                closes = [c['close'] for c in group]
                
                candles_timeframe.append({
                    'close_time': close_time,
                    'open': opens[0],
                    'high': max(highs),
                    'low': min(lows),
                    'close': closes[-1],
                    'volume': 0
                })
            
            return candles_timeframe
        
        except Exception as e:
            logger.error(f"Erro ao converter candles para timeframe {target_timeframe}s: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def _execute_pending_trades_on_candle_close(self, symbol: str, timeframe: int, close_time: float):
        """Executar trades pendentes quando uma vela fecha"""
        try:
            # Obter trades pendentes para este fechamento
            pending_trades = await self.trade_timing_manager.get_pending_trades_for_candle_close(
                symbol, timeframe, close_time
            )
            
            if not pending_trades:
                return
            
            logger.info(
                f"🎯 Executando {len(pending_trades)} trade(s) pendente(s) no fechamento da vela: "
                f"{symbol} {timeframe}s"
            )
            
            # Executar cada trade pendente
            for pending_trade in pending_trades:
                try:
                    from services.execute_on_candle_close import execute_trade_on_candle_close
                    
                    trade = await execute_trade_on_candle_close(
                        pending_trade,
                        self.trade_executor,
                        self
                    )
                    
                    # Remover trade pendente
                    await self.trade_timing_manager.remove_pending_trade(pending_trade.key)
                    
                except Exception as e:
                    logger.error(
                        f"Erro ao executar trade pendente {pending_trade.key[:20]}...: {e}",
                        exc_info=True
                    )
                    # Remover trade pendente mesmo se falhou
                    await self.trade_timing_manager.remove_pending_trade(pending_trade.key)
            
        except Exception as e:
            logger.error(f"Erro ao executar trades pendentes no fechamento da vela: {e}", exc_info=True)
    
    async def _save_candles_to_db(self, asset_symbol: str, candles: List[List[float]], period: int):
        """Salvar candles no banco de dados"""
        if not candles:
            return
        
        async with get_db_context() as db:
            try:
                # Buscar o asset pelo símbolo
                result = await db.execute(
                    select(Asset).where(Asset.symbol == asset_symbol)
                )
                asset = result.scalar_one_or_none()
                
                if not asset:
                    logger.warning(f"Asset {asset_symbol} não encontrado no banco de dados")
                    return
                
                # Processar cada candle
                saved_count = 0
                for candle_data in candles:
                    if not isinstance(candle_data, list) or len(candle_data) < 2:
                        continue
                    
                    timestamp = candle_data[0]
                    price = candle_data[1]
                    
                    # Converter timestamp para datetime
                    candle_time = datetime.fromtimestamp(timestamp)
                    
                    # Verificar se o candle já existe
                    existing = await db.execute(
                        select(Candle).where(
                            Candle.asset_id == asset.id,
                            Candle.timestamp == candle_time,
                            Candle.timeframe == period
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue
                    
                    # Criar novo candle
                    candle = Candle(
                        asset_id=asset.id,
                        timestamp=candle_time,
                        timeframe=period,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=0
                    )
                    db.add(candle)
                    saved_count += 1
                
                if saved_count > 0:
                    await db.commit()
                    logger.debug(f"[OK] {saved_count} candles salvos para {asset_symbol}")
                    
            except Exception as e:
                logger.error(f"Falha ao salvar candles no banco de dados: {e}")
                await db.rollback()

    async def _add_tick_to_buffer(self, account_idx: int, symbol: str, price: float, timestamp: float):
        """Adicionar tick ao buffer e salvar localmente"""
        
        # === VERIFICAÇÃO: Ignorar ticks de ativos não monitorados ===
        # Verificar se o símbolo está na lista de ativos monitorados para esta conta
        if account_idx in self._monitored_assets_by_account:
            if symbol not in self._monitored_assets_by_account[account_idx]:
                # Ativo não está sendo monitorado - ignorar tick
                return
        else:
            # Conta não existe na lista de monitorados - ignorar
            return
        
        current_time = time.time()

        # Normalizar timestamp para segundos
        timestamp_seconds = timestamp / 1000 if timestamp > 10000000000 else timestamp
        
        # Atualizar timestamp do último tick recebido para este ativo
        self._last_tick_time[symbol] = time.time()
        
        # Salvar tick localmente
        await self.local_storage.save_tick(symbol, price, timestamp_seconds)

        # Registrar histórico de ticks por símbolo
        history = self._tick_history.setdefault(symbol, deque())
        history.append((timestamp_seconds, price))
        cutoff = timestamp_seconds - self._tick_history_window_seconds
        while history and history[0][0] < cutoff:
            history.popleft()
        
        # Inicializar buffer para esta conta se necessário
        if account_idx not in self._tick_buffers:
            self._tick_buffers[account_idx] = {}
            self._last_log_time[account_idx] = current_time
        
        # Adicionar preço ao buffer
        self._tick_buffers[account_idx][symbol] = price
        
        # Adicionar tick ao candle de 1 segundo
        candle_start = int(timestamp_seconds // 1) * 1
        candle_close_time = candle_start + 1
        
        # Inicializar buffer de 1s para este símbolo
        if symbol not in self._candle_buffers:
            self._candle_buffers[symbol] = {}
        if '1' not in self._candle_buffers[symbol]:
            self._candle_buffers[symbol]['1'] = []
        if symbol not in self._last_candle_close:
            self._last_candle_close[symbol] = {}
        if '1' not in self._last_candle_close[symbol]:
            self._last_candle_close[symbol]['1'] = None
        
        # Verificar se já existe candle de 1s para este fechamento
        existing_candle = None
        for candle in self._candle_buffers[symbol]['1']:
            if candle['close_time'] == candle_close_time:
                existing_candle = candle
                break
        
        if existing_candle:
            # Atualizar candle existente
            existing_candle['close'] = price
            existing_candle['high'] = max(existing_candle['high'], price)
            existing_candle['low'] = min(existing_candle['low'], price)
        else:
            # Criar novo candle de 1s
            new_candle = {
                'close_time': candle_close_time,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0
            }
            self._candle_buffers[symbol]['1'].append(new_candle)
            
            # Manter apenas últimos 200 candles
            if len(self._candle_buffers[symbol]['1']) > 200:
                self._candle_buffers[symbol]['1'] = self._candle_buffers[symbol]['1'][-200:]
        
        # Verificar se passou 1 segundo desde o último log
        if current_time - self._last_log_time[account_idx] >= 1.0:
            # Criar resumo com apenas nomes: "EURUSD_otc | AUDCHF_otc | ..."
            buffer = self._tick_buffers[account_idx]
            symbol_names = list(buffer.keys())
            
            # Mostrar todos os símbolos separados por |
            summary = " | ".join(symbol_names)
            
            # Obter nome do usuário associado a esta conta
            user_name = "Unknown"
            if account_idx < len(self.ativos_clients):
                client = self.ativos_clients[account_idx]
                if hasattr(client, 'user_name'):
                    user_name = client.user_name
            
            total_ticks = len(buffer)
            time_str = datetime.fromtimestamp(timestamp_seconds).strftime('%H:%M:%S')
            logger.info(f"[INFO] [{user_name}] {total_ticks} ticks | {summary} @ {time_str}")
            
            # Atualizar timestamp
            self._last_log_time[account_idx] = current_time

    async def _on_ativos_stream_update(self, data: Any, account_idx: int):
        """Processar atualizações de dados de ativos"""
        try:
            # Atualizar health do cliente (tick recebido!)
            self._update_client_health(account_idx)
            
            # Verificar diferentes formatos de dados
            
            # Formato 1: Lista de ticks [["symbol", timestamp, price], ...]
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        symbol = item[0]
                        timestamp = item[1]
                        price = item[2]
                        
                        # Adicionar ao buffer
                        await self._add_tick_to_buffer(account_idx, symbol, price, timestamp)
                        
                        # Atualizar buffer de candles e verificar fechamento de vela
                        await self._update_candle_buffer(symbol, timestamp, price)
            
            # Formato 2: Dict com candles
            elif isinstance(data, dict):
                asset = data.get("asset")
                period = data.get("period")
                candles_data = data.get("data") or data.get("candles")
                
                if asset and period and candles_data:
                    # Extrair o preço atual (último candle)
                    if isinstance(candles_data, list) and len(candles_data) > 0:
                        last_candle = candles_data[-1]
                        if isinstance(last_candle, list) and len(last_candle) >= 2:
                            timestamp = last_candle[0]
                            price = last_candle[2]  # Close price
                            
                            # Adicionar ao buffer
                            await self._add_tick_to_buffer(account_idx, asset, price, timestamp)
                            
                            # Atualizar buffer de candles e verificar fechamento de vela
                            await self._update_candle_buffer(asset, timestamp, price)
        except Exception as e:
            account_name = self._get_account_name(account_idx)
            logger.error(f"Erro ao processar stream update da {account_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _on_json_data(self, data: Any, account_idx: int):
        """Processar dados JSON recebidos - pode conter ticks"""
        try:
            # Verificar se é uma lista de ticks [["symbol", timestamp, price], ...]
            if isinstance(data, list) and len(data) > 0:
                # Verificar se é lista de ticks (primeiro item é lista com 3 elementos)
                if isinstance(data[0], list) and len(data[0]) == 3:
                    # Atualizar health do cliente (ticks recebidos!)
                    self._update_client_health(account_idx)
                
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        symbol = item[0]
                        timestamp = item[1]
                        price = item[2]
                        
                        # Converter para float se necessário
                        try:
                            if isinstance(timestamp, str):
                                timestamp = float(timestamp)
                            if isinstance(price, str):
                                price = float(price)
                        except (ValueError, TypeError):
                            continue
                        
                        # Adicionar ao buffer
                        await self._add_tick_to_buffer(account_idx, symbol, price, timestamp)
            
            # Verificar se é uma lista de eventos Socket.IO
            elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
                event_type = data[0]
                event_data = data[1] if len(data) > 1 else None
                
                # Se for updateStream, processar
                if event_type == "updateStream" and event_data:
                    await self._on_ativos_stream_update(event_data, account_idx)
        except Exception as e:
            account_name = self._get_account_name(account_idx)
            logger.error(f"Erro ao processar json_data da {account_name}: {e}")

    async def _ativos_monitoring_loop(self):
        """Loop de monitoramento contínuo de ativos (apenas rebalanceamento)"""
        logger.info("Loop de monitoramento de ativos iniciado")

        while self.is_running:
            try:
                await asyncio.sleep(60)  # Rebalancear a cada 60 segundos

                if not self.is_running:
                    break

                # Rebalancear ativos baseado em payout
                logger.info("[REBALANCE] Iniciando rebalanceamento de ativos...")
                await self._rebalance_assets()

            except asyncio.CancelledError:
                logger.info("Loop de monitoramento de ativos cancelado")
                break
            except Exception as e:
                logger.error(f"[CRITICAL] Erro no loop de monitoramento de ativos: {type(e).__name__}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(10)

        logger.info("Loop de monitoramento de ativos encerrado")

    async def _client_connection_watchdog(self):
        """Watchdog para monitorar saúde das conexões de ativos e reconectar rapidamente se necessário"""
        logger.info("[WATCHDOG] Iniciando watchdog de conexões de ativos...")
        
        while self.is_running:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                if not self.is_running:
                    break
                
                current_time = time.time()
                
                for account_idx, client in enumerate(self.ativos_clients):
                    if account_idx not in self._client_health_status:
                        # Inicializar health status
                        self._client_health_status[account_idx] = {
                            'last_tick': current_time,
                            'is_connected': True,
                            'reconnect_count': 0,
                            'last_check': current_time
                        }
                        continue
                    
                    health = self._client_health_status[account_idx]
                    last_tick = health.get('last_tick', current_time)
                    tick_gap = current_time - last_tick
                    
                    # Verificar se o cliente está conectado
                    is_websocket_connected = False
                    if hasattr(client, '_keep_alive_manager') and client._keep_alive_manager:
                        # is_connected pode ser método ou atributo
                        is_connected_attr = getattr(client._keep_alive_manager, 'is_connected', None)
                        if callable(is_connected_attr):
                            is_websocket_connected = is_connected_attr()
                        else:
                            is_websocket_connected = bool(is_connected_attr)
                    elif hasattr(client, '_websocket') and client._websocket:
                        is_websocket_connected = client._websocket.is_connected
                    
                    # Detectar problema: gap muito grande sem ticks OU websocket desconectado
                    has_problem = (tick_gap > self._max_tick_gap_seconds) or not is_websocket_connected
                    
                    if has_problem and health['is_connected']:
                        account_name = self._get_account_name(account_idx)
                        logger.warning(f"[WATCHDOG] ⚠️ {account_name}: PROBLEMA DETECTADO! "
                                       f"Gap: {tick_gap:.1f}s, WS connected: {is_websocket_connected}")
                        
                        health['is_connected'] = False
                        health['reconnect_count'] = 0
                        
                        # Iniciar reconexão imediata
                        try:
                            await self._reconnect_client_with_retry(account_idx)
                        except Exception as e:
                            logger.error(f"[WATCHDOG] Erro ao reconectar cliente {account_idx}: {e}")
                        
                        health['last_check'] = current_time
                        
            except asyncio.CancelledError:
                logger.info("[WATCHDOG] Watchdog de conexões cancelado")
                break
            except Exception as e:
                logger.error(f"[WATCHDOG] Erro no watchdog: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)
        
        logger.info("[WATCHDOG] Watchdog de conexões encerrado")

    async def _reconnect_client_with_retry(self, account_idx: int):
        """Reconectar um cliente de ativos com retry e backoff exponencial"""
        async with self._reconnect_lock:
            if account_idx >= len(self.ativos_clients):
                logger.error(f"[RECONNECT] Índice de conta inválido: {account_idx}")
                return
            
            account_name = self._get_account_name(account_idx)
            health = self._client_health_status.get(account_idx, {})
            retry_count = health.get('reconnect_count', 0)
            
            if retry_count >= self._max_reconnect_retries:
                logger.error(f"[RECONNECT] ❌ {account_name}: Máximo de tentativas atingido ({retry_count}). "
                             f"Desistindo de reconectar.")
                return
            
            # Calcular delay com backoff exponencial (2^retry segundos, max 30s)
            delay = min(self._reconnect_backoff_base ** retry_count, 30)
            
            logger.info(f"[RECONNECT] 🔄 {account_name}: Tentativa {retry_count + 1}/{self._max_reconnect_retries} "
                        f"(delay: {delay}s)...")
            
            try:
                client = self.ativos_clients[account_idx]
                
                # Desconectar forçadamente primeiro
                logger.debug(f"[RECONNECT] {account_name}: Forçando disconnect...")
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"[RECONNECT] {account_name}: Timeout no disconnect, continuando...")
                except Exception as e:
                    logger.debug(f"[RECONNECT] {account_name}: Erro no disconnect (ignorado): {e}")
                
                # Aguardar delay antes de reconectar
                if delay > 0:
                    await asyncio.sleep(delay)
                
                # Reconectar
                logger.info(f"[RECONNECT] {account_name}: Reconectando...")
                connect_result = await client.connect()
                
                if connect_result:
                    logger.success(f"[RECONNECT] ✅ {account_name}: RECONECTADO COM SUCESSO!")
                    
                    # Resetar contador de retry
                    health['reconnect_count'] = 0
                    health['is_connected'] = True
                    health['last_tick'] = time.time()
                    
                    # Reinscrever nos ativos
                    if account_idx in self._monitored_assets_by_account:
                        symbols = list(self._monitored_assets_by_account[account_idx])
                        logger.info(f"[RECONNECT] {account_name}: Reinscrevendo em {len(symbols)} ativos...")
                        
                        for symbol in symbols:
                            try:
                                await self._subscribe_asset(client, symbol)
                                await asyncio.sleep(0.1)  # Evitar flood
                            except Exception as e:
                                logger.error(f"[RECONNECT] Erro ao reinscrever em {symbol}: {e}")
                        
                        logger.success(f"[RECONNECT] {account_name}: Reinscrito em {len(symbols)} ativos")
                else:
                    logger.error(f"[RECONNECT] ❌ {account_name}: Falha na reconexão")
                    health['reconnect_count'] = retry_count + 1
                    health['is_connected'] = False
                    
                    # Agendar nova tentativa após delay
                    await asyncio.sleep(5)
                    try:
                        await self._reconnect_client_with_retry(account_idx)
                    except Exception as e:
                        logger.error(f"[RECONNECT] Erro na tentativa subsequente: {e}")
                    
            except Exception as e:
                logger.error(f"[RECONNECT] ❌ {account_name}: Erro durante reconexão: {e}")
                import traceback
                logger.error(traceback.format_exc())
                health['reconnect_count'] = retry_count + 1
                health['is_connected'] = False
    
    def _update_client_health(self, account_idx: int):
        """Atualizar timestamp do último tick recebido para um cliente"""
        if account_idx in self._client_health_status:
            self._client_health_status[account_idx]['last_tick'] = time.time()
            self._client_health_status[account_idx]['is_connected'] = True

    async def _on_payout_data(self, data: Dict[str, Any]):
        """"Processar atualizações de dados de payout"""
        try:
            if isinstance(data, list) and len(data) > 0:
                # Logar início do processamento
                logger.debug(f"Iniciando processamento de {len(data)} assets de payout")
                
                # Se o payload estiver encapsulado (ex: [[asset1,...],[asset2,...]]) ou aninhado, achatar
                items = []
                for item in data:
                    if isinstance(item, list) and len(item) > 0 and isinstance(item[0], list):
                        items.extend(item)
                    else:
                        items.append(item)

                # Processar cada asset
                assets_to_update = []
                for item in items:
                    if isinstance(item, list) and len(item) > 5:
                        asset_id = item[0]
                        raw_symbol = item[1]
                        name = item[2]
                        asset_type = item[3]
                        payout = item[5]
                        timeframes = None
                        # Timeframes estão no índice 15
                        if len(item) > 15 and isinstance(item[15], list):
                            timeframes = [tf.get("time") if isinstance(tf, dict) else tf for tf in item[15] if tf]
                        
                        # Encontrar o símbolo correto usando o mapa reverso
                        symbol = ASSET_ID_TO_SYMBOL.get(asset_id, raw_symbol)
                        
                        assets_to_update.append({
                            'asset_id': asset_id,
                            'symbol': symbol,
                            'name': name,
                            'asset_type': asset_type,
                            'payout': payout,
                            'timeframes': timeframes
                        })
                
                # Atualizar todos os assets em lote (uma única transação)
                if assets_to_update:
                    logger.debug(f"Atualizando {len(assets_to_update)} assets no banco de dados...")
                    await self._update_assets_payout_batch(assets_to_update)
                    logger.debug(f"[OK] {len(assets_to_update)} assets atualizados")
                
                # Logar apenas atualizações significativas (mais de 10 assets)
                if len(data) > 10:
                    logger.info(f"[OK] Dados de payout atualizados para {len(data)} assets")

        except Exception as e:
            logger.error(f"Erro ao processar dados de payout: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _update_assets_payout_batch(self, assets: List[Dict[str, Any]]):
        """Atualizar payout e timeframes de múltiplos assets em lote com retry"""
        from utils.retry import retry_on_db_lock
        import time
        
        @retry_on_db_lock(max_retries=3, retry_delay=1.0, timeout=15.0)
        async def _do_update():
            start_time = time.time()
            
            async with get_db_context() as db:
                try:
                    # Buscar todos os assets existentes em uma única query
                    asset_ids = [asset['asset_id'] for asset in assets]
                    query_start = time.time()
                    result = await db.execute(
                        select(Asset).where(Asset.id.in_(asset_ids))
                    )
                    existing_assets = {asset.id: asset for asset in result.scalars().all()}
                    query_time = time.time() - query_start
                    logger.debug(f"Query SELECT levou {query_time:.3f}s para {len(asset_ids)} assets")
                    
                    # Processar cada asset
                    update_start = time.time()
                    for asset_data in assets:
                        asset = existing_assets.get(asset_data['asset_id'])
                        
                        if asset:
                            # Atualizar payout e timeframes
                            asset.payout = asset_data['payout']
                            if asset_data['timeframes']:
                                asset.available_timeframes = asset_data['timeframes']
                            # Atualizar o nome para o símbolo correto
                            asset.name = asset_data['symbol']
                            asset.updated_at = datetime.utcnow()
                        else:
                            # Criar novo asset
                            asset = Asset(
                                id=asset_data['asset_id'],
                                symbol=asset_data['symbol'],
                                name=asset_data['symbol'],  # Usar o símbolo no campo name também
                                type=asset_data['asset_type'],
                                payout=asset_data['payout'],
                                available_timeframes=asset_data['timeframes'],
                                is_active=True
                            )
                            db.add(asset)
                    
                    update_time = time.time() - update_start
                    
                    # Commit
                    commit_start = time.time()
                    await db.commit()
                    commit_time = time.time() - commit_start
                    
                    total_time = time.time() - start_time
                    logger.debug(f"[OK] {len(assets)} assets atualizados em lote em {total_time:.3f}s (query: {query_time:.3f}s, update: {update_time:.3f}s, commit: {commit_time:.3f}s)")

                except Exception as e:
                    logger.error(f"Falha ao atualizar payouts em lote: {e}")
                    # Try rollback only if session is still active
                    try:
                        if db.is_active:
                            await db.rollback()
                    except Exception:
                        pass  # Ignore rollback errors if connection is closed
                    raise
        
        await _do_update()

    async def get_status(self) -> Dict[str, Any]:
        """Obter status do coletor de dados"""
        return {
            "is_running": self.is_running,
            "payout_connected": self.payout_client.is_connected if self.payout_client else False,
            "assets_count": await self._get_assets_count()
        }


# Global instance
data_collector = DataCollectorService()

# Função para obter a instância global
def get_realtime_data_collector():
    """Retorna a instância global do coletor de dados em tempo real"""
    return data_collector
