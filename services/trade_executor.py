"""Executor de trades conectado ao UserConnectionManager"""
import asyncio
import pandas as pd
from typing import Optional, Dict, Any, List, Set
from datetime import datetime, timedelta
from loguru import logger

from sqlalchemy import select, text, update, and_, or_, exists
from core.database import get_db_context
from core.resilience import ResilienceExecutor, ResiliencePresets
from models import Account, Asset, Trade, TradeStatus, TradeDirection, SignalType, AutoTradeConfig, Strategy, User, Signal
from services.pocketoption.constants import ASSETS
from services.pocketoption.maintenance_checker import maintenance_checker
from services.pocketoption.models import OrderDirection, OrderStatus
from services.notifications.telegram import telegram_service
from core.system_manager import get_system_manager, SystemModule


class TradeExecutor:
    """Executor de trades que usa UserConnectionManager"""

    MIN_BALANCE_THRESHOLD = 0.10
    
    def __init__(self, connection_manager):
        self.connection_manager = connection_manager
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_monitoring = False
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._asset_locks: Dict[str, asyncio.Lock] = {}  # Lock por ativo para evitar trades simultâneos
        self._asset_locks_creation_lock = asyncio.Lock()  # Lock para proteger criação de asset locks
        self._order_callback_connections: Set[str] = set()
        self.trade_timing_manager = None  # Será injetado pelo RealtimeDataCollector
        self._sent_notifications: Set[str] = set()  # Rastrear trades notificados (evitar duplicatas)
        
        # Resilience executor para operações de trade com timeout protegido
        self._resilience = ResiliencePresets.trade_executor()
    
    async def start_monitoring(self):
        """Iniciar monitoramento de trades ativos"""
        if self._is_monitoring:
            return

        self._is_monitoring = True

        # Configurar callbacks de eventos de ordem (WebSocket)
        self._setup_order_callbacks()

        # Iniciar monitoramento apenas para trades expirados (fallback)
        self._monitoring_task = asyncio.create_task(self._monitor_active_trades())
        logger.info(
            "Monitoramento de trades ativos iniciado (WebSocket events + fallback polling)",
            extra={
                "user_name": "",
                "account_id": "",
                "account_type": ""
            }
        )
    
    async def stop_monitoring(self):
        """Parar monitoramento de trades ativos"""
        self._is_monitoring = False
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await asyncio.wait_for(
                    self._monitoring_task,
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.debug("Timeout ao aguardar finalização da task de monitoramento")
            except asyncio.CancelledError:
                pass
        logger.info(
            "Monitoramento de trades ativos parado",
            extra={
                "user_name": "",
                "account_id": "",
                "account_type": ""
            }
        )

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        """Obter ou criar lock para uma conta"""
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]
    
    def _setup_order_callbacks(self):
        """Configurar callbacks para eventos de ordem (WebSocket events)."""
        try:
            # Registrar callbacks em todas as conexões ativas
            for connection in self.connection_manager.connections.values():
                if connection.client:
                    key = f"{connection.account_id}_{connection.connection_type}"
                    if key in self._order_callback_connections:
                        continue

                    async def order_closed_wrapper(
                        data,
                        account_id=connection.account_id,
                        connection_type=connection.connection_type,
                    ):
                        await self._on_order_closed_event(
                            data,
                            account_id=account_id,
                            connection_type=connection_type,
                        )

                    # Registrar handler para evento order_closed diretamente no cliente
                    connection.client.add_event_callback(
                        "order_closed",
                        order_closed_wrapper,
                    )
                    self._order_callback_connections.add(key)
                    logger.debug(
                        "Callback order_closed registrado para conta %s (%s)",
                        connection.account_id[:8],
                        connection.connection_type,
                        extra={
                            "user_name": connection.user_name,
                            "account_id": connection.account_id[:8],
                            "account_type": connection.connection_type
                        }
                    )

            if self._order_callback_connections:
                logger.info(
                    "Callbacks de eventos de ordem registrados em todas as conexões",
                    extra={
                        "user_name": "",
                        "account_id": "",
                        "account_type": ""
                    }
                )
        except Exception as e:
            logger.error(
                f"Erro ao configurar callbacks de eventos de ordem: {e}",
                extra={
                    "user_name": "",
                    "account_id": "",
                    "account_type": ""
                }
            )
    
    async def _on_order_closed_event(
        self,
        data: Any,
        account_id: Optional[str] = None,
        connection_type: Optional[str] = None,
    ):
        """Handler para evento de ordem fechada via WebSocket"""
        try:
            # Extrair order_id do evento (pode ser dict ou OrderResult)
            order_id = None
            if isinstance(data, dict):
                order_id = data.get("order_id") or data.get("id") or data.get("request_id")
            elif hasattr(data, 'order_id'):
                order_id = data.order_id

            if not order_id:
                account_label = account_id[:8] if account_id else "?"
                logger.warning(
                    f"Evento order_closed recebido sem order_id (conta={account_label}): {data}",
                    extra={
                        "user_name": "",
                        "account_id": account_id[:8] if account_id else "",
                        "account_type": connection_type or ""
                    }
                )
                return

            # Buscar trade correspondente no banco de dados
            async with get_db_context() as db:
                # Tentar buscar por order_id primeiro
                trade_query = select(Trade).where(Trade.order_id == order_id)
                if account_id:
                    trade_query = trade_query.where(Trade.account_id == account_id)
                if connection_type:
                    trade_query = trade_query.where(Trade.connection_type == connection_type)
                result = await db.execute(trade_query)
                trade = result.scalar_one_or_none()

                # Se não encontrar, tentar buscar por id (caso o order_id seja o ID do trade)
                if not trade:
                    trade_query = select(Trade).where(Trade.id == order_id)
                    if account_id:
                        trade_query = trade_query.where(Trade.account_id == account_id)
                    if connection_type:
                        trade_query = trade_query.where(Trade.connection_type == connection_type)
                    result = await db.execute(trade_query)
                    trade = result.scalar_one_or_none()

                if not trade:
                    logger.debug(
                        f"Trade não encontrado para order_id: {order_id}",
                        extra={
                            "user_name": "",
                            "account_id": account_id[:8] if account_id else "",
                            "account_type": connection_type or ""
                        }
                    )
                    # Tentar buscar trades ativos expirados recentemente
                    # FIX: Buscar IDs primeiro, depois processar em sessões separadas
                    five_minutes_ago = datetime.utcnow() - pd.Timedelta(minutes=5)
                    expired_trade_ids = []
                    try:
                        expired_query = select(Trade.id).where(
                            Trade.status == TradeStatus.ACTIVE,
                            Trade.expires_at <= five_minutes_ago,
                        )
                        if account_id:
                            expired_query = expired_query.where(Trade.account_id == account_id)
                        if connection_type:
                            expired_query = expired_query.where(Trade.connection_type == connection_type)
                        result = await db.execute(expired_query)
                        expired_trade_ids = [row[0] for row in result.all()]
                    except Exception as e:
                        logger.error(f"Erro ao buscar trades expirados: {e}")
                        return
                    
                    if expired_trade_ids:
                        account_label = account_id[:8] if account_id else "?"
                        logger.info(
                            f"Verificando {len(expired_trade_ids)} trades expirados "
                            f"(conta={account_label}, order_id não encontrado)",
                            extra={
                                "user_name": "",
                                "account_id": account_id[:8] if account_id else "",
                                "account_type": connection_type or ""
                            }
                        )
                        # Processar cada trade em sua própria sessão
                        for expired_trade_id in expired_trade_ids:
                            try:
                                async with get_db_context() as trade_db:
                                    # Buscar trade completo nesta sessão
                                    trade_result = await trade_db.execute(
                                        select(Trade).where(Trade.id == expired_trade_id)
                                    )
                                    expired_trade = trade_result.scalar_one_or_none()
                                    if expired_trade:
                                        account_lock = self._get_account_lock(expired_trade.account_id)
                                        async with account_lock:
                                            await self._check_trade_result(expired_trade, trade_db)
                            except Exception as e:
                                logger.error(f"Erro ao processar trade expirado {expired_trade_id[:8]}: {e}")
                    return

                # Se o trade ainda está ativo, verificar resultado
                if trade.status == TradeStatus.ACTIVE:
                    logger.info(
                        f"Evento order_closed recebido para trade {trade.id[:8]}... (order_id={order_id})",
                        extra={
                            "user_name": "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": trade.connection_type or ""
                        }
                    )
                    account_lock = self._get_account_lock(trade.account_id)
                    async with account_lock:
                        await self._check_trade_result(trade, db)
        except Exception as e:
            logger.error(
                f"Erro ao processar evento order_closed: {e}",
                extra={
                    "user_name": "",
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": connection_type or ""
                },
                exc_info=True
            )
    
    async def _monitor_active_trades(self):
        """Monitorar trades ativos (fallback para trades que não receberam evento WebSocket)"""
        while self._is_monitoring:
            try:
                # Polling menos frequente (60 segundos) como fallback
                # WebSocket events devem tratar a maioria dos casos
                await asyncio.sleep(60)

                active_connections = [
                    connection
                    for connection in self.connection_manager.connections.values()
                    if connection.is_connected
                ]
                if not active_connections:
                    logger.debug(
                        "Sem conexões ativas para monitorar trades expirados",
                        extra={
                            "user_name": "",
                            "account_id": "",
                            "account_type": ""
                        }
                    )
                    continue

                active_account_ids = {connection.account_id for connection in active_connections}
                
                # Buscar IDs dos trades ativos expirados há mais de 1 minuto
                expired_trade_ids = []
                try:
                    async with get_db_context() as db:
                        one_minute_ago = datetime.utcnow() - pd.Timedelta(minutes=1)
                        trade_query = select(Trade.id).where(
                            Trade.status == TradeStatus.ACTIVE,
                            Trade.expires_at <= one_minute_ago,
                            Trade.account_id.in_(active_account_ids),
                        )
                        result = await db.execute(trade_query)
                        expired_trade_ids = [row[0] for row in result.all()]
                except Exception as e:
                    logger.error(f"Erro ao buscar trades expirados: {e}")
                    continue
                    
                if expired_trade_ids:
                    logger.info(
                        f"Verificando {len(expired_trade_ids)} trades expirados (fallback polling)",
                        extra={
                            "user_name": "",
                            "account_id": "",
                            "account_type": ""
                        }
                    )
                
                # Processar cada trade em sua própria sessão
                for trade_id in expired_trade_ids:
                    try:
                        async with get_db_context() as trade_db:
                            # Buscar trade completo nesta sessão
                            trade_result = await trade_db.execute(
                                select(Trade).where(Trade.id == trade_id)
                            )
                            trade = trade_result.scalar_one_or_none()
                            if trade:
                                # Trade expirou há mais de 1 minuto, verificar resultado
                                account_lock = self._get_account_lock(trade.account_id)
                                async with account_lock:
                                    await self._check_trade_result(trade, trade_db)
                    except Exception as e:
                        logger.error(f"Erro ao processar trade expirado {trade_id[:8]}: {e}")
                
            except asyncio.CancelledError:
                break
            except ConnectionError as e:
                logger.error(
                    f"Erro de conexão ao monitorar trades ativos: {e}",
                    extra={
                        "user_name": "",
                        "account_id": "",
                        "account_type": ""
                    }
                )
            except Exception as e:
                logger.error(
                    f"Erro ao monitorar trades ativos: {e}",
                    extra={
                        "user_name": "",
                        "account_id": "",
                        "account_type": ""
                    },
                    exc_info=True
                )
    
    async def _check_trade_result(self, trade: Trade, db):
        """Verificar resultado de um trade expirado com retry e timeout"""
        max_retries = 3
        retry_delay = 2  # segundos

        # Buscar informações da conta e usuário para logs
        account_name = None
        user_name = None
        try:
            from models import Account, User
            account_result = await db.execute(
                select(Account.name, Account.id, User.name)
                .join(User, Account.user_id == User.id)
                .where(Account.id == trade.account_id)
            )
            account_row = account_result.first()
            if account_row:
                account_name = account_row[0]
                user_name = account_row[2]
        except Exception:
            pass

        log_prefix = f"[{user_name or 'Unknown'} / {account_name or trade.account_id[:8] if trade.account_id else 'Unknown'}]"

        for attempt in range(max_retries):
            try:
                # Se o trade expirou há mais de 24 horas, marcar como fechado sem resultado
                if trade.expires_at:
                    hours_since_expiry = (datetime.utcnow() - trade.expires_at).total_seconds() / 3600
                    if hours_since_expiry > 24:
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.utcnow()
                        await db.commit()
                        logger.warning(
                            f"[{trade.id[:8]}...] Trade expirado há {hours_since_expiry:.1f}h, marcado como fechado sem resultado",
                            extra={
                                "user_name": "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )
                        return

                # Obter conexão da conta usando o connection_type salvo
                connection_type = trade.connection_type or 'demo'
                connection = self.connection_manager.get_connection(trade.account_id, connection_type)

                if not connection or not connection.is_connected:
                    logger.warning(
                        f"Conexão não encontrada para trade {trade.id[:8]}... (account_id={trade.account_id[:8]}..., type={connection_type})",
                        extra={
                            "user_name": connection.user_name if connection else "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": connection_type
                        }
                    )
                    # Fechar trade sem resultado se a conexão não estiver disponível
                    trade.status = TradeStatus.CLOSED
                    trade.closed_at = datetime.utcnow()
                    trade.exit_price = trade.entry_price if trade.entry_price else 0
                    trade.profit = 0
                    trade.payout = 0

                    await db.commit()
                    logger.warning(
                        f"[{trade.id[:8]}...] Trade fechado sem resultado (conexão indisponível)",
                        extra={
                            "user_name": "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": connection_type
                        }
                    )
                    return

                # Usar o order_id da PocketOption para verificar o resultado
                order_id_to_check = trade.order_id if trade.order_id else trade.id

                # Verificar resultado da ordem no cliente com timeout
                try:
                    order_result = await asyncio.wait_for(
                        connection.client.check_order_result(order_id_to_check),
                        timeout=10.0  # Timeout de 10 segundos
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[{trade.id[:8]}...] Timeout ao verificar resultado (tentativa {attempt + 1}/{max_retries})",
                        extra={
                            "user_name": connection.user_name if connection else "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": connection_type
                        }
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        # YIELD: Permitir que o event loop processe outras tarefas
                        await asyncio.sleep(0)
                        continue
                    else:
                        # Última tentativa falhou, marcar como fechado sem resultado
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.utcnow()
                        trade.exit_price = trade.entry_price if trade.entry_price else 0
                        trade.profit = 0
                        trade.payout = 0
                        await db.commit()
                        logger.warning(
                        f"[{trade.id[:8]}...] Trade fechado sem resultado (timeout após {max_retries} tentativas)",
                        extra={
                            "user_name": connection.user_name if connection else "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": connection_type
                        }
                    )
                        return

                if order_result and order_result.status in [OrderStatus.WIN, OrderStatus.LOSS, OrderStatus.DRAW]:
                    # Atualizar trade
                    if order_result.status == OrderStatus.DRAW:
                        trade.status = TradeStatus.DRAW
                        trade.profit = 0
                        trade.exit_price = order_result.exit_price
                        trade.closed_at = datetime.utcnow()
                        trade.payout = 0
                    else:
                        trade.status = TradeStatus.WIN if order_result.status == OrderStatus.WIN else TradeStatus.LOSS
                        trade.profit = order_result.profit
                        trade.exit_price = order_result.exit_price
                        trade.closed_at = datetime.utcnow()

                    # Rastrear resultado do trade para cooldown
                    result = 'win' if trade.status == TradeStatus.WIN else 'loss'
                    symbol = None
                    strategy_id = None
                    try:
                        asset_result = await db.execute(
                            select(Asset.symbol).where(Asset.id == trade.asset_id)
                        )
                        symbol = asset_result.scalar_one_or_none()
                        strategy_id = trade.strategy_id
                    except Exception as e:
                        logger.error(
                            f"Erro ao buscar symbol/strategy_id para cooldown: {e}",
                            extra={
                                "user_name": "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )

                    if symbol and strategy_id:
                        # Notificar realtime collector para rastrear resultado e acionar cooldown se necessário
                        from services.data_collector.realtime import get_realtime_data_collector
                        realtime_collector = get_realtime_data_collector()
                        if realtime_collector:
                            realtime_collector._add_asset_to_cooldown(
                                account_id=trade.account_id,
                                symbol=symbol,
                                strategy_id=strategy_id,
                                result=result
                            )

                    # Obter payout: da ordem ou calcular como porcentagem com base no amount e profit
                    if order_result.payout:
                        trade.payout = order_result.payout
                    elif trade.amount and trade.amount > 0:
                        # Calcular payout como porcentagem
                        if order_result.status == OrderStatus.WIN and trade.profit and trade.profit > 0:
                            # payout % = (profit / amount) * 100
                            trade.payout = (trade.profit / trade.amount) * 100
                        else:
                            # LOSS: payout = 0%
                            trade.payout = 0
                    else:
                        trade.payout = 0

                    await db.commit()

                    # 🔴 REGISTRAR FIM DE TRADE no system_manager
                    system_manager = get_system_manager()
                    system_manager.register_trade_end(trade.id)

                    # Buscar account_name para log
                    account_name_for_log = None
                    try:
                        account_result = await db.execute(
                            select(Account.name)
                            .where(Account.id == trade.account_id)
                        )
                        account_name_for_log = account_result.scalar_one_or_none()
                    except Exception:
                        account_name_for_log = None

                    # Buscar dados do usuário e asset para user_logger e notificação
                    user_chat_id = None
                    account_name = None
                    user_name = None
                    asset_name = None
                    current_balance = None
                    try:
                        account_result = await db.execute(
                            select(Account.name, User.telegram_chat_id, User.name, Account.balance_demo, Account.balance_real, Account.autotrade_demo)
                            .join(User, Account.user_id == User.id)
                            .where(Account.id == trade.account_id)
                        )
                        account_row = account_result.first()
                        if account_row:
                            account_name = account_row[0]
                            user_chat_id = account_row[1]
                            user_name = account_row[2]
                            # Obter saldo da conta (demo ou real)
                            balance_demo = account_row[3]
                            balance_real = account_row[4]
                            autotrade_demo = account_row[5]
                            current_balance = balance_demo if autotrade_demo else balance_real

                        asset_result = await db.execute(
                            select(Asset.symbol).where(Asset.id == trade.asset_id)
                        )
                        asset_name = asset_result.scalar_one_or_none()
                    except Exception as e:
                        logger.error(
                            f"Erro ao buscar dados do usuário: {e}",
                            extra={
                                "user_name": user_name or account_name or "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )

                    # Importar e usar o user_logger para registrar resultado do trade
                    try:
                        from services.user_logger import user_logger
                        # Buscar user_name e asset_name
                        user_name_log = user_name or account_name_for_log or ""
                        asset_name_log = asset_name or ""
                        
                        user_logger.log_trade_result(
                            username=user_name_log,
                            account_id=trade.account_id,
                            asset=asset_name_log,
                            order_id=trade.id,
                            result='win' if trade.status == TradeStatus.WIN else 'loss' if trade.status == TradeStatus.LOSS else 'draw',
                            profit=trade.profit if trade.profit else 0,
                            balance_before=None,  # Não temos saldo anterior aqui
                            balance_after=None
                        )
                    except Exception as e:
                        logger.debug(f"[USER LOGGER] Erro ao logar resultado: {e}")

                    logger.success(
                        f"[{trade.id[:8]}...] Trade fechou: {trade.status} (lucro: ${trade.profit if trade.profit else 0:.2f}, payout: {trade.payout if trade.payout else 0:.1f}%)",
                        extra={
                            "user_name": account_name_for_log or user_name or "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": trade.connection_type or ""
                        }
                    )

                    # Calcular saldo antes e depois do trade
                    balance_after = current_balance if current_balance else 0
                    profit = trade.profit if trade.profit else 0
                    balance_before = balance_after - profit
                    
                    # DEBUG: Log detalhado da notificação
                    notification_key = f"{trade.id}_{trade.status.value}"
                    logger.info(
                        f"[NOTIFICATION DEBUG] Trade {trade.id[:8]} | "
                        f"Status: {trade.status.value} | "
                        f"User: {user_name} | "
                        f"Chat ID: {user_chat_id} | "
                        f"Asset: {asset_name} | "
                        f"Key: {notification_key} | "
                        f"Already Sent: {notification_key in self._sent_notifications}"
                    )
                    
                    # Enviar notificação de resultado via Telegram (async) - com deduplicação
                    if user_chat_id and notification_key not in self._sent_notifications:
                        try:
                            # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
                            system_manager = get_system_manager()
                            if not system_manager.is_notifications_enabled():
                                logger.debug(f"🔕 Notificação de resultado bloqueada - módulo de notificações desligado")
                            else:
                                logger.info(f"[NOTIFICATION] Enviando notificação de resultado para {user_name} (chat: {user_chat_id})")
                                # YIELD: Cedendo controle ao event loop antes de enviar notificação
                                await asyncio.sleep(0)
                                # Executar notificação em task separada para não bloquear
                                asyncio.create_task(
                                    telegram_service.send_trade_result_notification(
                                        asset=asset_name,
                                        direction=self._map_direction_to_signal(trade.direction.value),
                                        result=trade.status.value,
                                        profit=profit,
                                        account_name=account_name,
                                        chat_id=user_chat_id,
                                        account_type=getattr(trade, "connection_type", None),
                                        user_name=user_name,
                                        balance_before=balance_before,
                                        balance_after=balance_after
                                    )
                                )
                                logger.success(f"[NOTIFICATION] Notificação enviada com sucesso: {notification_key}")
                            self._sent_notifications.add(notification_key)
                        except Exception as e:
                            logger.error(
                                f"[NOTIFICATION ERROR] Falha ao enviar notificação: {e}",
                                exc_info=True
                            )
                    elif not user_chat_id:
                        logger.warning(f"[NOTIFICATION] Não enviado - user_chat_id é None para trade {trade.id[:8]}")
                    elif notification_key in self._sent_notifications:
                        logger.debug(f"[NOTIFICATION] Notificação duplicada ignorada: {notification_key}")

                    # Atualizar contadores de autotrade quando trade fecha (usar mesma sessão)
                    # Não atualizar contadores quando for empate
                    if order_result.status != OrderStatus.DRAW:
                        # Obter saldo atual antes de atualizar contadores
                        account_result = await db.execute(
                            select(Account).where(Account.id == trade.account_id)
                        )
                        account = account_result.scalar_one_or_none()

                        current_balance = None
                        if account:
                            current_balance = account.balance_demo if account.autotrade_demo else account.balance_real

                        configs = await self._fetch_account_configs(db, trade.account_id)
                        config = self._choose_account_config(configs, trade.account_id, warn_on_multiple=False)
                        if not config:
                            logger.warning(
                                f"Configuração de autotrade não encontrada para conta {trade.account_id}",
                                extra={
                                    "user_name": "",
                                    "account_id": trade.account_id[:8] if trade.account_id else "",
                                    "account_type": trade.connection_type or ""
                                }
                            )
                        else:
                            await self._update_autotrade_counters_after_trade(trade, config, db, current_balance)
                    else:
                        logger.info(
                            f"[{trade.id[:8]}...] Empate detectado - contadores não atualizados, continuando operação",
                            extra={
                                "user_name": "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )
                    return  # Sucesso, sair do loop de retry

                elif order_result and order_result.status == OrderStatus.CANCELLED:
                    # Trade cancelado
                    trade.status = TradeStatus.CANCELLED
                    trade.closed_at = datetime.utcnow()

                    await db.commit()

                    # 🔴 REGISTRAR FIM DE TRADE no system_manager
                    system_manager = get_system_manager()
                    system_manager.register_trade_end(trade.id)

                    logger.warning(
                        f"[{trade.id[:8]}...] Trade cancelado",
                        extra={
                            "user_name": "",
                            "account_id": trade.account_id[:8] if trade.account_id else "",
                            "account_type": trade.connection_type or ""
                        }
                    )

                    # Buscar dados para notificação (async)
                    user_chat_id = None
                    account_name = None
                    user_name = None
                    asset_name = None
                    try:
                        account_result = await db.execute(
                            select(Account.name, User.telegram_chat_id, User.name)
                            .join(User, Account.user_id == User.id)
                            .where(Account.id == trade.account_id)
                        )
                        account_row = account_result.first()
                        if account_row:
                            account_name = account_row[0]
                            user_chat_id = account_row[1]
                            user_name = account_row[2]

                        asset_result = await db.execute(
                            select(Asset.symbol).where(Asset.id == trade.asset_id)
                        )
                        asset_name = asset_result.scalar_one_or_none()
                    except Exception as e:
                        logger.error(
                            f"Erro ao buscar dados do usuário: {e}",
                            extra={
                                "user_name": user_name or account_name or "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )

                    # Enviar notificação de resultado via Telegram (async) - com deduplicação
                    notification_key = f"{trade.id}_{trade.status.value}"
                    if user_chat_id and notification_key not in self._sent_notifications:
                        try:
                            # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
                            system_manager = get_system_manager()
                            if not system_manager.is_notifications_enabled():
                                logger.debug(f"🔕 Notificação de cancelamento bloqueada - módulo de notificações desligado")
                            else:
                                # YIELD: Cedendo controle ao event loop antes de enviar notificação
                                await asyncio.sleep(0)
                                # Executar notificação em task separada para não bloquear
                                asyncio.create_task(
                                    telegram_service.send_trade_result_notification(
                                        asset=asset_name,
                                        direction=self._map_direction_to_signal(trade.direction.value),
                                        result=trade.status.value,
                                        profit=0,
                                        account_name=account_name,
                                        chat_id=user_chat_id,
                                        account_type=getattr(trade, "connection_type", None),
                                        user_name=user_name,
                                        balance_before=None,
                                        balance_after=None
                                    )
                                )
                                logger.debug(f"[NOTIFICATION] Notificação de cancelamento enviada: {notification_key}")
                            self._sent_notifications.add(notification_key)
                        except Exception as e:
                            logger.error(f"Erro ao enviar notificação de resultado: {e}")
                    elif notification_key in self._sent_notifications:
                        logger.debug(f"[NOTIFICATION] Notificação duplicada ignorada: {notification_key}")
                    return  # Sucesso, sair do loop de retry

                else:
                    # Trade ainda não tem resultado, tentar novamente se não for a última tentativa
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{log_prefix} [{trade.id[:8]}...] Resultado ainda não disponível (tentativa {attempt + 1}/{max_retries})",
                            extra={
                                "user_name": user_name or "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )
                        await asyncio.sleep(retry_delay)
                        # YIELD: Permitir que o event loop processe outras tarefas
                        await asyncio.sleep(0)
                        continue
                    else:
                        # Última tentativa, marcar como CLOSED
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.utcnow()
                        # Preencher campos com valores padrão quando não há resultado
                        trade.exit_price = trade.entry_price if trade.entry_price else 0
                        trade.profit = 0
                        trade.payout = 0

                        await db.commit()

                        # 🔴 REGISTRAR FIM DE TRADE no system_manager
                        system_manager = get_system_manager()
                        system_manager.register_trade_end(trade.id)

                        logger.warning(
                            f"{log_prefix} [{trade.id[:8]}...] Trade fechado sem resultado definido após {max_retries} tentativas",
                            extra={
                                "user_name": user_name or "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )

                        # Buscar dados para notificação (async)
                        user_chat_id = None
                        account_name = None
                        user_name = None
                        asset_name = None
                        try:
                            account_result = await db.execute(
                                select(Account.name, User.telegram_chat_id, User.name)
                                .join(User, Account.user_id == User.id)
                                .where(Account.id == trade.account_id)
                            )
                            account_row = account_result.first()
                            if account_row:
                                account_name = account_row[0]
                                user_chat_id = account_row[1]
                                user_name = account_row[2]

                            asset_result = await db.execute(
                                select(Asset.symbol).where(Asset.id == trade.asset_id)
                            )
                            asset_name = asset_result.scalar_one_or_none()
                        except Exception as e:
                            logger.error(
                            f"Erro ao buscar dados do usuário: {e}",
                            extra={
                                "user_name": user_name or account_name or "",
                                "account_id": trade.account_id[:8] if trade.account_id else "",
                                "account_type": trade.connection_type or ""
                            }
                        )

                        # Enviar notificação de resultado via Telegram (async) - com deduplicação
                        notification_key = f"{trade.id}_{trade.status.value}"
                        if user_chat_id and notification_key not in self._sent_notifications:
                            try:
                                # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
                                system_manager = get_system_manager()
                                if not system_manager.is_notifications_enabled():
                                    logger.debug(f"🔕 Notificação de fechamento bloqueada - módulo de notificações desligado")
                                else:
                                    # YIELD: Cedendo controle ao event loop antes de enviar notificação
                                    await asyncio.sleep(0)
                                    # Executar notificação em task separada para não bloquear
                                    asyncio.create_task(
                                        telegram_service.send_trade_result_notification(
                                            asset=asset_name,
                                            direction=self._map_direction_to_signal(trade.direction.value),
                                            result=trade.status.value,
                                            profit=trade.profit if trade.profit else 0,
                                            account_name=account_name,
                                            chat_id=user_chat_id,
                                            account_type=getattr(trade, "connection_type", None),
                                            user_name=user_name,
                                            balance_before=None,
                                            balance_after=None
                                        )
                                    )
                                    logger.debug(f"[NOTIFICATION] Notificação de fechamento enviada: {notification_key}")
                                self._sent_notifications.add(notification_key)
                            except Exception as e:
                                logger.error(f"Erro ao enviar notificação de resultado: {e}")
                        elif notification_key in self._sent_notifications:
                            logger.debug(f"[NOTIFICATION] Notificação duplicada ignorada: {notification_key}")
                        return  # Sucesso, sair do loop de retry

            except Exception as e:
                logger.error(f"[{trade.id[:8]}...] Erro ao verificar resultado (tentativa {attempt + 1}/{max_retries}): {e}", extra={
                    "user_name": user_name or "",
                    "account_id": trade.account_id[:8] if trade.account_id else "",
                    "account_type": trade.connection_type or ""
                })
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    # YIELD: Permitir que o event loop processe outras tarefas
                    await asyncio.sleep(0)
                    continue
                else:
                    # Última tentativa falhou, marcar como fechado sem resultado
                    trade.status = TradeStatus.CLOSED
                    trade.closed_at = datetime.utcnow()
                    trade.exit_price = trade.entry_price if trade.entry_price else 0
                    trade.profit = 0
                    trade.payout = 0
                    await db.commit()

                    # 🔴 REGISTRAR FIM DE TRADE no system_manager
                    system_manager = get_system_manager()
                    system_manager.register_trade_end(trade.id)

                    logger.error(f"[{trade.id[:8]}...] Trade fechado sem resultado após erro: {e}", extra={
                        "user_name": user_name or "",
                        "account_id": trade.account_id[:8] if trade.account_id else "",
                        "account_type": trade.connection_type or ""
                    })
                    return
    
    async def execute_trade(
        self,
        signal: Dict[str, Any],
        symbol: str,
        timeframe_seconds: int,
        strategy_name: str,
        account_id: Optional[str] = None,
        autotrade_config: Optional[Dict[str, Any]] = None
    ) -> Optional[Trade]:
        """
        Executar trade baseado em sinal
        
        Args:
            signal: Sinal gerado pela estratégia
            symbol: Símbolo do asset
            timeframe_seconds: Timeframe em segundos
            strategy_name: Nome da estratégia
            account_id: ID da conta (obrigatório para execução automática multiusuário)
            autotrade_config: Configuração de autotrade (opcional, se fornecido usa essa configuração)
            
        Returns:
            Trade criado ou None se falhar
        """
        try:
            # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se execução de novos trades está habilitada
            system_manager = get_system_manager()
            if not system_manager.can_execute_new_trade():
                logger.warning(
                    f"🛑 [TradeExecutor] NOVO TRADE BLOQUEADO - Sistema desligado (modo acompanhamento apenas). "
                    f"Trades em andamento: {system_manager.state.trades_in_progress}"
                )
                return None
            
            logger.success(f"🎯 [TradeExecutor] Iniciando execução de trade | {symbol} | {strategy_name} | {timeframe_seconds}s | {signal.signal_type.upper()} | confiança={signal.confidence:.2f}")
            
            # 🚨 VALIDAÇÃO DE SEGURANÇA: Ativos oficiais (sem _otc) só aceitam trades >= 60s
            from services.pocketoption.constants import is_otc_asset
            if not is_otc_asset(symbol) and timeframe_seconds < 60:
                logger.warning(f"⏸️ [TradeExecutor] [{symbol}] Trade bloqueado: ativo oficial (não-OTC) requer timeframe >= 60s (atual: {timeframe_seconds}s)")
                return None
            
            # Obter asset_id
            asset_id = ASSETS.get(symbol)
            if not asset_id:
                logger.warning(f"⚠️ [TradeExecutor] Asset não encontrado: {symbol}")
                return None
            
            if not account_id:
                logger.warning("⚠️ [TradeExecutor] account_id é obrigatório para execução multiusuário")
                return None

            connection, account = await self._get_connection_for_account_id(account_id)
            if not connection:
                logger.warning(f"⚠️ [TradeExecutor] Nenhuma conexão ativa para conta {account_id}")
                return None
            
            logger.info(f"📋 [TradeExecutor] Conta específica solicitada: {account.name}")
            
            # Se autotrade_config foi fornecido, usar essa configuração
            if autotrade_config:
                # Se for um dict, converter para objeto AutoTradeConfig
                if isinstance(autotrade_config, dict):
                    from models import AutoTradeConfig
                    # Remover campos que não existem no modelo AutoTradeConfig
                    config_dict = autotrade_config.copy()
                    config_dict.pop('indicators', None)  # Remover campo 'indicators'
                    config_dict.pop('strategy_parameters', None)  # Remover campo 'strategy_parameters'
                    autotrade_config = AutoTradeConfig(**config_dict)
                
                logger.info(f"✓ [TradeExecutor] Configuração de autotrade fornecida: timeframe={autotrade_config.timeframe}s, strategy={autotrade_config.strategy_id}")
                
                # Verificar se autotrade está ativo
                if not autotrade_config.is_active:
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Autotrade desativado")
                    return None
                
                # Verificar se o timeframe está configurado
                if autotrade_config.timeframe != timeframe_seconds:
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Timeframe {timeframe_seconds}s não configurado (configurado: {autotrade_config.timeframe}s)")
                    return None
                
                logger.success(f"✓ [TradeExecutor] Timeframe {timeframe_seconds}s OK")
            else:
                # Buscar configuração de autotrade da conta
                autotrade_config = await self._get_autotrade_config(account.id)
                if not autotrade_config:
                    logger.warning(f"⚠️ [TradeExecutor] Configuração de autotrade não encontrada para conta {account.name}")
                    return None
                
                logger.info(f"✓ [TradeExecutor] Configuração de autotrade carregada: is_active={autotrade_config.is_active}, timeframe={autotrade_config.timeframe}s, strategy={autotrade_config.strategy_id}")
                
                # Verificar se autotrade está ativo
                if not autotrade_config.is_active:
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Autotrade desativado")
                    return None
                
                # Verificar se o timeframe está configurado
                if not await self._check_timeframe(autotrade_config, timeframe_seconds):
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Timeframe {timeframe_seconds}s não configurado")
                    return None
                
                logger.success(f"✓ [TradeExecutor] Timeframe {timeframe_seconds}s OK")
            logger.info(f"📋 [TradeExecutor] Conta selecionada: {account.name}")
            
            # Verificar trade_timing da configuração
            trade_timing = getattr(autotrade_config, 'trade_timing', 'on_signal')
            logger.debug(f"[TradeExecutor] trade_timing={trade_timing}")
            
            # Se trade_timing for 'on_candle_close', agendar para fechamento da vela
            if trade_timing == 'on_candle_close' and self.trade_timing_manager:
                logger.info(f"📅 [TradeExecutor] Agendando trade para fechamento da vela: {symbol} {timeframe_seconds}s")
                
                # Agendar trade para fechamento da vela
                pending_trade = await self.trade_timing_manager.add_pending_trade(
                    signal=signal,
                    symbol=symbol,
                    timeframe=timeframe_seconds,
                    strategy_id=autotrade_config.strategy_id or '',
                    account_id=account.id,
                    autotrade_config={
                        'id': autotrade_config.id,
                        'account_id': autotrade_config.account_id,
                        'strategy_id': autotrade_config.strategy_id,
                        'amount': autotrade_config.amount,
                        'stop1': autotrade_config.stop1,
                        'stop2': autotrade_config.stop2,
                        'soros': autotrade_config.soros,
                        'martingale': autotrade_config.martingale,
                        'timeframe': autotrade_config.timeframe,
                        'min_confidence': autotrade_config.min_confidence,
                        'cooldown_seconds': autotrade_config.cooldown_seconds,
                        'stop_amount_win': getattr(autotrade_config, 'stop_amount_win', 0),
                        'stop_amount_loss': getattr(autotrade_config, 'stop_amount_loss', 0),
                        'no_hibernate_on_consecutive_stop': getattr(autotrade_config, 'no_hibernate_on_consecutive_stop', False),
                    }
                )
                
                if pending_trade:
                    logger.success(f"✅ [TradeExecutor] Trade agendado para fechamento da vela: {symbol} {timeframe_seconds}s")
                    return None  # Não executar trade agora, será executado no fechamento
                else:
                    logger.warning(f"⚠️ [TradeExecutor] Falha ao agendar trade para fechamento da vela")
                    return None
            
            # Obter lock da conta para evitar race condition no cooldown
            account_lock = self._get_account_lock(account.id)
            
            # Usar o timeframe do sinal (parâmetro passado pelo usuário)
            duration = timeframe_seconds
            
            async with account_lock:
                # 🚨 CRITICAL FIX: Processar trades expirados PENDENTES antes de recarregar config
                # Isso garante que smart_reduction e outros contadores estejam atualizados
                # antes de calcular o valor do próximo trade
                await self._process_pending_expired_trades(account.id)
                
                # Recarregar configuração do banco para obter last_trade_time atualizado
                autotrade_config = await self._get_autotrade_config(account.id)
                if not autotrade_config:
                    logger.warning(f"⚠️ [TradeExecutor] Configuração de autotrade não encontrada para conta {account.name}")
                    return None

                # Garantir que usamos o estado mais recente após recarregar do banco
                if not autotrade_config.is_active:
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Autotrade desativado (config atual)")
                    return None

                if not await self._check_timeframe(autotrade_config, timeframe_seconds):
                    logger.info(
                        f"⏸️ [TradeExecutor] [{account.name}] Timeframe {timeframe_seconds}s não configurado (config atual)"
                    )
                    return None

                if maintenance_checker.is_under_maintenance:
                    logger.warning(
                        f"⏸️ [TradeExecutor] [{account.name}] PocketOption em manutenção. Trade bloqueado."
                    )
                    return None

                # Verificar stop amount antes de executar nova operação
                async with get_db_context() as db:
                    stop_amount_ok = await self._check_stop_amount(
                        None,
                        autotrade_config,
                        db,
                        connection_type=getattr(connection, "connection_type", None)
                    )
                    if not stop_amount_ok:
                        logger.info(f"⏸️ [TradeExecutor] [{account.name}] Stop amount atingido")
                        return None

                # Verificar cooldown (tempo mínimo entre operações)
                if not await self._check_cooldown(autotrade_config, duration):
                    return None
                
                # Verificar limites diários
                if not await self._check_daily_limits(autotrade_config):
                    logger.info(f"⏸️ [TradeExecutor] [{account.name}] Limites diários atingidos")
                    return None

                # Verificar se há trades ativos para garantir funcionamento correto do soros/martingale
                # Também verifica se há trades ativos no mesmo ativo (symbol) para evitar trades fantasma
                
                # Usar lock por ativo para evitar race conditions
                # Criação do lock deve ser thread-safe
                asset_lock_key = f"{account.id}:{symbol}"
                async with self._asset_locks_creation_lock:
                    if asset_lock_key not in self._asset_locks:
                        self._asset_locks[asset_lock_key] = asyncio.Lock()
                
                async with self._asset_locks[asset_lock_key]:
                    # Verificar novamente dentro do lock (double-check)
                    # Se execute_all_signals estiver ativo, ignorar bloqueio de trades simultâneos
                    execute_all_signals = getattr(autotrade_config, 'execute_all_signals', False)
                    if not await self._check_no_active_trades(account.id, symbol, execute_all_signals=execute_all_signals):
                        logger.warning(f"[TradeExecutor] [{account.name}] 🔒 LOCK: Trade bloqueado - já existe trade ativo no ativo {symbol}")
                        return None
                    
                    # Verificar se deve executar trade baseado na confiança
                    # Se execute_all_signals estiver ativo, ignorar verificação de confiança mínima
                    if not execute_all_signals and signal.confidence < autotrade_config.min_confidence:
                        logger.info(f"[TradeExecutor] [{symbol}] Confiança {signal.confidence:.2f} abaixo do mínimo {autotrade_config.min_confidence:.2f}")
                        return None

                    # Verificar Stop Gain/Stop Loss antes de executar
                    if not await self._check_stop_loss(autotrade_config):
                        logger.info(f"⏸️ [TradeExecutor] [{account.name}] Stop Gain/Stop Loss atingido")
                        return None

                    # Calcular valor do trade (aplicar soros ou martingale se necessário)
                    amount = await self._calculate_trade_amount(autotrade_config)

                    # Validar trade amount antes de executar
                    if amount is None or amount <= 0:
                        logger.error(f"[TradeExecutor] [{account.name}] Trade amount inválido: ${amount}")
                        return None

                    if amount > 10000:  # Limite máximo de segurança
                        logger.error(f"[TradeExecutor] [{account.name}] Trade amount excede limite máximo: ${amount}")
                        return None

                    # Verificar saldo insuficiente ANTES de executar o trade
                    balance_ok = await self._check_insufficient_balance(
                        autotrade_config,
                        db,
                        connection_type=getattr(connection, "connection_type", None),
                        trade_amount=amount
                    )
                    if not balance_ok:
                        logger.info(f"⏸️ [TradeExecutor] [{account.name}] Saldo insuficiente, trade não executado")
                        return None

                    # Usar o timeframe do sinal (parâmetro passado pelo usuário)
                    duration = timeframe_seconds
                    
                    # Verificar cooldown (tempo mínimo entre operações)
                    if not await self._check_cooldown(autotrade_config, duration):
                        return None
                    
                    # Verificar cooldown por ativo após loss
                    from services.data_collector.realtime import get_realtime_data_collector
                    realtime_collector = get_realtime_data_collector()
                    if realtime_collector and autotrade_config.strategy_id:
                        logger.debug(f"[COOLDOWN CHECK] Verificando cooldown para {symbol} - account_id={autotrade_config.account_id[:8]}, strategy_id={autotrade_config.strategy_id[:8]}")
                        
                        # Verificar todos os strategy_ids possíveis para este ativo
                        is_in_cooldown = False
                        try:
                            # Tentar com o strategy_id da config
                            is_in_cooldown = realtime_collector._is_asset_in_cooldown(autotrade_config.account_id, symbol, autotrade_config.strategy_id)
                            logger.debug(f"[COOLDOWN CHECK] Verificação com config.strategy_id: is_in_cooldown={is_in_cooldown}")
                            
                            # Se não estiver em cooldown, verificar se há algum cooldown para qualquer strategy_id
                            if not is_in_cooldown:
                                # Verificar se há algum cooldown registrado para este ativo/conta
                                if hasattr(realtime_collector, '_asset_cooldowns'):
                                    if autotrade_config.account_id in realtime_collector._asset_cooldowns:
                                        if symbol in realtime_collector._asset_cooldowns[autotrade_config.account_id]:
                                            # Se houver qualquer cooldown para este ativo, bloquear
                                            logger.debug(f"[COOLDOWN CHECK] Cooldown encontrado para {symbol}, bloqueando trade")
                                            is_in_cooldown = True
                        except Exception as e:
                            logger.error(f"[COOLDOWN CHECK] Erro ao verificar cooldown: {e}")
                        
                        logger.debug(f"[COOLDOWN CHECK] Resultado final: is_in_cooldown={is_in_cooldown}")
                        if is_in_cooldown:
                            # Adicionar logs detalhados sobre o cooldown
                            try:
                                if hasattr(realtime_collector, '_asset_cooldowns'):
                                    if (autotrade_config.account_id in realtime_collector._asset_cooldowns and
                                        symbol in realtime_collector._asset_cooldowns[autotrade_config.account_id] and
                                        autotrade_config.strategy_id in realtime_collector._asset_cooldowns[autotrade_config.account_id][symbol]):
                                        import time
                                        from datetime import datetime
                                        current_time = time.time()
                                        cooldown_end = realtime_collector._asset_cooldowns[autotrade_config.account_id][symbol][autotrade_config.strategy_id]
                                        remaining_time = cooldown_end - current_time
                                        cooldown_end_str = datetime.fromtimestamp(cooldown_end).strftime('%Y-%m-%d %H:%M:%S')
                                        logger.info(f"⏳ [TradeExecutor] [{symbol}] Ativo em cooldown para conta {autotrade_config.account_id[:8]}, trade não executado. Tempo restante: {remaining_time:.1f}s (expira em: {cooldown_end_str})")
                                    else:
                                        logger.info(f"⏳ [TradeExecutor] [{symbol}] Ativo em cooldown para conta {autotrade_config.account_id[:8]}, trade não executado")
                                else:
                                    logger.info(f"⏳ [TradeExecutor] [{symbol}] Ativo em cooldown para conta {autotrade_config.account_id[:8]}, trade não executado")
                            except Exception as e:
                                logger.info(f"⏳ [TradeExecutor] [{symbol}] Ativo em cooldown para conta {autotrade_config.account_id[:8]}, trade não executado")
                            return None
                    
                    # Executar trade
                    logger.info(f"[TradeExecutor] [{account.name}] Executando trade {signal.signal_type.upper()} (confiança: {signal.confidence:.2f}, valor: ${amount})")
                    
                    trade = await self._place_order(
                        connection=connection,
                        symbol=symbol,
                        signal=signal,
                        amount=amount,
                        duration=duration,
                        strategy_id=autotrade_config.strategy_id
                    )
                    
                    if trade:
                        logger.success(f"[TradeExecutor] [{account.name}] Trade executado: {trade.direction} ${trade.amount} @ {trade.entry_price}")
                        
                        # Registrar trade no performance monitor
                        try:
                            from services.performance_monitor import performance_monitor
                            performance_monitor.record_trade(success=True)
                        except Exception as e:
                            logger.debug(f"[PerformanceMonitor] Erro ao registrar trade: {e}")
                        
                        # Enviar notificação de trade executado via Telegram
                        try:
                            # Buscar dados do usuário para notificação
                            user_chat_id = None
                            account_name_notify = None
                            user_name_notify = None
                            async with get_db_context() as db:
                                account_result = await db.execute(
                                    select(Account.name, User.name, User.telegram_chat_id)
                                    .join(User, Account.user_id == User.id)
                                    .where(Account.id == account.id)
                                )
                                account_row = account_result.first()
                                if account_row:
                                    account_name_notify = account_row[0]
                                    user_name_notify = account_row[1]
                                    user_chat_id = account_row[2]
                            
                            if user_chat_id:
                                # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas para NOVOS sinais
                                system_manager = get_system_manager()
                                if not system_manager.is_notifications_enabled():
                                    logger.debug(f"🔕 Notificação de novo trade bloqueada - módulo de notificações desligado")
                                else:
                                    logger.info(f"[NOTIFICATION] Enviando notificação de trade executado para {user_name_notify} (chat: {user_chat_id})")
                                    # Converter direção do formato do banco (CALL/PUT) para BUY/SELL
                                    direction_mapped = "BUY" if signal.signal_type.value.upper() in ["CALL", "BUY"] else "SELL"
                                    
                                    # YIELD: Cedendo controle ao event loop antes de enviar notificação
                                    await asyncio.sleep(0)
                                    
                                    # Executar notificação em task separada para não bloquear
                                    asyncio.create_task(
                                        telegram_service.send_signal_notification(
                                            asset=symbol,
                                            direction=direction_mapped,
                                            confidence=signal.confidence,
                                            timeframe=duration,
                                            account_name=account_name_notify,
                                            chat_id=user_chat_id,
                                            trade_amount=trade.amount if hasattr(trade, 'amount') else None,
                                            account_type=getattr(trade, "connection_type", None),
                                        )
                                    )
                                    logger.success(f"[NOTIFICATION] Notificação de trade executado enviada com sucesso")
                            else:
                                logger.warning(f"[NOTIFICATION] Não enviado - user_chat_id é None para conta {account.id[:8]}")
                        except Exception as e:
                            logger.error(f"[NOTIFICATION ERROR] Falha ao enviar notificação de trade executado: {e}")
                    else:
                        logger.error(f"[TradeExecutor] Falha ao executar trade")
                
                return trade
            
        except ConnectionError as e:
            logger.error(f"[TradeExecutor] Erro de conexão ao executar trade para {symbol}: {e}", extra={
                "user_name": "",
                "account_id": "",
                "account_type": ""
            }, exc_info=True)
        except ValueError as e:
            logger.error(f"[TradeExecutor] Erro de validação ao executar trade para {symbol}: {e}", extra={
                "user_name": "",
                "account_id": "",
                "account_type": ""
            }, exc_info=True)
        except Exception as e:
            logger.error(f"[TradeExecutor] Erro ao executar trade para {symbol}: {e}", extra={
                "user_name": "",
                "account_id": "",
                "account_type": ""
            }, exc_info=True)
            return None
    
    def _map_direction_to_signal(self, direction: str) -> str:
        """Converter direção do formato do banco (CALL/PUT) para formato de sinal (BUY/SELL)"""
        direction_upper = direction.upper() if direction else ""
        if direction_upper in ["CALL", "BUY"]:
            return "BUY"
        elif direction_upper in ["PUT", "SELL"]:
            return "SELL"
        return direction_upper

    async def _get_connection_for_account_id(self, account_id: str) -> Optional:
        """Obter conexão ativa para uma conta específica"""
        async with get_db_context() as db:
            # Buscar conta específica (ativa OU com configs de autotrade ativas)
            result = await db.execute(
                select(Account).where(
                    or_(
                        and_(Account.id == account_id, Account.is_active == True),
                        and_(
                            Account.id == account_id,
                            exists().where(
                                and_(
                                    AutoTradeConfig.account_id == Account.id,
                                    AutoTradeConfig.is_active == True
                                )
                            )
                        )
                    )
                )
            )
            account = result.scalar_one_or_none()
            
            if not account:
                return None, None
            
            # Preferir conexão já ativa (real > demo)
            for connection_type in ("real", "demo"):
                connection = self.connection_manager.get_connection(account.id, connection_type)
                if connection and connection.is_connected:
                    logger.debug(f"Usando conexão {connection_type} da conta {account.name}")
                    return connection, account

            # Determinar qual conexão deve ser usada/reativada
            # Só reativar se autotrade estiver ativo para o tipo correspondente
            connection_type = None
            ssid = None
            if account.autotrade_real and account.ssid_real:
                connection_type = "real"
                ssid = account.ssid_real
            elif account.autotrade_demo and account.ssid_demo:
                connection_type = "demo"
                ssid = account.ssid_demo
            # Não reconectar se autotrade_demo e autotrade_real estão desativados

            if connection_type and ssid:
                await self.connection_manager.ensure_connection(account.id, connection_type, ssid)
                connection = self.connection_manager.get_connection(account.id, connection_type)
                if connection and connection.is_connected:
                    logger.debug(f"Conexão {connection_type} reativada para conta {account.name}")
                    return connection, account

            return None, account

    async def _get_strategy_parameters(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """Obter parâmetros da estratégia do banco de dados"""
        # Parâmetros padrão para estratégias
        default_params = {
            'scalping': {
                'amount': 1,
                'duration': 5,
                'min_confidence': 0.7
            },
            'multi_oscillator': {
                'amount': 2,
                'duration': 60,
                'min_confidence': 0.7
            },
            'breakout': {
                'amount': 5,
                'duration': 300,
                'min_confidence': 0.7
            },
            'trend_following': {
                'amount': 10,
                'duration': 900,
                'min_confidence': 0.7
            },
            'confluence': {
                'amount': 20,
                'duration': 3600,
                'min_confidence': 0.75
            },
            'confluence_long_term': {
                'amount': 50,
                'duration': 3600,
                'min_confidence': 0.9
            }
        }
        
        return default_params.get(strategy_name)
    
    async def _get_autotrade_config(self, account_id: str) -> Optional[AutoTradeConfig]:
        """Obter configuração de autotrade da conta, lidando com duplicatas"""
        async with get_db_context() as db:
            configs = await self._fetch_account_configs(db, account_id)
            return self._choose_account_config(configs, account_id)

    async def _fetch_account_configs(self, db, account_id: str) -> List[AutoTradeConfig]:
        result = await db.execute(
            select(AutoTradeConfig)
            .where(AutoTradeConfig.account_id == account_id)
            .order_by(AutoTradeConfig.updated_at.desc())
        )
        return result.scalars().all()

    def _choose_account_config(
        self,
        configs: List[AutoTradeConfig],
        account_id: str,
        *,
        warn_on_multiple: bool = True
    ) -> Optional[AutoTradeConfig]:
        if not configs:
            return None

        # Filtrar apenas configurações ativas
        active_configs = [c for c in configs if c.is_active]

        if not active_configs:
            logger.warning(f"⚠️ [TradeExecutor] Nenhuma configuração ativa encontrada para a conta {account_id}")
            return None

        if warn_on_multiple and len(active_configs) > 1:
            logger.warning(
                f"⚠️ [TradeExecutor] {len(active_configs)} configurações ativas encontradas para a conta {account_id}. Usando a mais recente."
            )

        # Sempre retornar a configuração ativa mais recente (índice 0, pois já está ordenada por updated_at.desc())
        return active_configs[0]
    
    async def _check_timeframe(self, config: AutoTradeConfig, timeframe_seconds: int) -> bool:
        """Verificar se o timeframe está configurado"""
        # Obter timeframe configurado
        configured_timeframe = config.timeframe or 5
        
        # Verificar se o timeframe é igual ao configurado
        return timeframe_seconds == configured_timeframe
    
    async def _check_daily_limits(self, config: AutoTradeConfig) -> bool:
        """Verificar limites diários de trades"""
        # Resetar contadores se for um novo dia
        today = datetime.utcnow().date()
        if config.last_trade_date:
            # Handle both date and datetime objects
            last_date = config.last_trade_date
            if hasattr(last_date, 'date'):
                last_date = last_date.date()
            if last_date != today:
                config.daily_trades_count = 0
                config.soros_level = 0  # Resetar nível do Soros
                config.soros_amount = 0.0  # Resetar valor do Soros
                config.martingale_level = 0  # Resetar nível do Martingale
                config.martingale_amount = 0.0  # Resetar valor do Martingale
                config.updated_at = datetime.utcnow()  # Atualizar timestamp

                logger.info(f"📅 Novo dia detectado: contadores resetados")

        return True

    async def _apply_consecutive_stop_cooldown(
        self,
        config: AutoTradeConfig,
        *,
        reason: str,
        account_name: str | None = None,
        account_type: str | None = None
    ) -> None:
        """Aplicar cooldown quando stop consecutivo é atingido sem hibernar."""
        try:
            now = datetime.utcnow()
            # Usar cooldown configurado pelo usuário (suporta formato randomizado "X-X")
            from utils.cooldown_utils import parse_cooldown
            cooldown_duration = parse_cooldown(config.cooldown_seconds, default=0)

            async with get_db_context() as db:
                result = await db.execute(
                    select(AutoTradeConfig).where(AutoTradeConfig.account_id == config.account_id)
                )
                autotrade_configs = result.scalars().all()

                if autotrade_configs:
                    for autotrade_config in autotrade_configs:
                        autotrade_config.loss_consecutive = 0
                        autotrade_config.win_consecutive = 0
                        autotrade_config.total_losses = 0
                        autotrade_config.total_wins = 0
                        autotrade_config.soros_level = 0
                        autotrade_config.soros_amount = 0.0
                        autotrade_config.martingale_level = 0
                        autotrade_config.martingale_amount = 0.0
                        # NOTA: NÃO resetar smart_reduction_loss_count e smart_reduction_win_count
                        # para permitir que a Redução Inteligente continue acumulando perdas
                        # mesmo durante o cooldown de stop
                        # Definir cooldown específico para stop consecutivo (usando valor configurado pelo usuário)
                        if cooldown_duration > 0:
                            autotrade_config.consecutive_stop_cooldown_until = now + timedelta(seconds=cooldown_duration)
                        autotrade_config.updated_at = now
                    await db.commit()

            config.loss_consecutive = 0
            config.win_consecutive = 0
            config.total_losses = 0  # Reset: ciclo terminou
            config.total_wins = 0      # Reset: ciclo terminou
            config.soros_level = 0
            config.soros_amount = 0.0
            config.martingale_level = 0
            config.martingale_amount = 0.0
            # NOTA: NÃO resetar smart_reduction_loss_count e smart_reduction_win_count
            # para permitir que a Redução Inteligente continue acumulando perdas
            # mesmo durante o cooldown de stop
            if cooldown_duration > 0:
                config.consecutive_stop_cooldown_until = now + timedelta(seconds=cooldown_duration)
            config.updated_at = now

            # Persistir cooldown no banco
            async with get_db_context() as db:
                await db.flush()
                await db.commit()

            if cooldown_duration > 0:
                logger.warning(
                    f"⏸️ [{account_name or config.account_id}] {reason}. Cooldown aplicado ({cooldown_duration}s, não hibernar ativo)."
                )
            else:
                logger.warning(
                    f"⏸️ [{account_name or config.account_id}] {reason}. Contadores resetados (cooldown=0, não hibernar ativo)."
                )
            
            # Enviar notificação Telegram sobre stop gain/loss consecutivo
            try:
                async with get_db_context() as db:
                    # Buscar chat_id do usuário
                    result = await db.execute(
                        select(Account.user_id).where(Account.id == config.account_id)
                    )
                    user_id = result.scalar_one_or_none()
                    
                    if user_id:
                        from models import User
                        user_result = await db.execute(
                            select(User.telegram_chat_id).where(User.id == user_id)
                        )
                        chat_id = user_result.scalar_one_or_none()
                        
                        if chat_id:
                            # Verificar se no_hibernate está ativo
                            no_hibernate = getattr(config, 'no_hibernate_on_consecutive_stop', False)
                            
                            if "Stop Loss" in reason:
                                await telegram_service.send_stop_loss_notification(
                                    account_name or "Desconhecida",
                                    config.total_losses or 0,
                                    config.stop2 or 0,
                                    chat_id,
                                    account_type=account_type,
                                    no_hibernate=no_hibernate
                                )
                                logger.info(f"✓ Notificação Telegram de Stop Loss enviada para {chat_id[:8]}...")
                            elif "Stop Gain" in reason:
                                await telegram_service.send_stop_gain_notification(
                                    account_name or "Desconhecida",
                                    config.total_wins or 0,
                                    config.stop1 or 0,
                                    chat_id,
                                    account_type=account_type,
                                    no_hibernate=no_hibernate
                                )
                                logger.info(f"✓ Notificação Telegram de Stop Gain enviada para {chat_id[:8]}...")
            except Exception as e:
                logger.error(f"Erro ao enviar notificação de stop consecutivo: {e}")
                
        except Exception as e:
            logger.error(f"Erro ao aplicar cooldown do stop consecutivo: {e}", exc_info=True)

    async def _resolve_account_balance(
        self,
        config: AutoTradeConfig,
        db,
        *,
        connection_type: Optional[str] = None,
        trade: Optional[Trade] = None
    ):
        account_result = await db.execute(
            select(Account).where(Account.id == config.account_id)
        )
        account = account_result.scalar_one_or_none()

        if not account:
            logger.warning(f"Conta {config.account_id} não encontrada", extra={
                "user_name": "",
                "account_id": config.account_id[:8] if config.account_id else "",
                "account_type": connection_type or ""
            })
            return None, None, 0.0

        # Sempre verificar o estado atual da conta para garantir que estamos usando o saldo correto
        # Isso evita problemas quando a conexão foi trocada recentemente (real ↔ demo)
        if account.autotrade_real:
            resolved_connection_type = "real"
        elif account.autotrade_demo:
            resolved_connection_type = "demo"
        else:
            # Fallback: usar connection_type se fornecido, ou trade.connection_type
            resolved_connection_type = connection_type
            if not resolved_connection_type and trade and getattr(trade, "connection_type", None):
                resolved_connection_type = trade.connection_type

        # Tentar obter saldo da conexão WebSocket em tempo real
        connection_key = f"{config.account_id}_{resolved_connection_type}"

        current_balance = None
        if self.connection_manager and connection_key in self.connection_manager.connections:
            connection = self.connection_manager.connections[connection_key]
            if connection.client and hasattr(connection.client, 'get_balance'):
                try:
                    # Usar ResilienceExecutor para proteger contra timeout
                    balance_obj = await self._resilience.execute(
                        connection.client.get_balance(),
                        operation_name=f"get_balance_{connection_key}"
                    )
                    if balance_obj and hasattr(balance_obj, 'balance'):
                        current_balance = balance_obj.balance
                        logger.info(f"✓ Saldo obtido da conexão WebSocket: ${current_balance:.2f}")
                except Exception as e:
                    logger.warning(f"Erro ao obter saldo da conexão WebSocket: {e}")

        # Se não conseguiu obter da conexão, usar saldo do banco de dados
        if current_balance is None:
            if resolved_connection_type == "real":
                current_balance = account.balance_real or 0
            elif resolved_connection_type == "demo":
                current_balance = account.balance_demo or 0
            else:
                current_balance = account.balance_real if account.balance_real is not None else (account.balance_demo or 0)
            logger.warning(f"⚠️ Usando saldo do banco de dados: ${current_balance:.2f} (conexão não disponível)")

        return account, resolved_connection_type, current_balance
    
    async def _check_insufficient_balance(
        self,
        config: AutoTradeConfig,
        db,
        *,
        connection_type: Optional[str] = None,
        trade: Optional[Trade] = None,
        trade_amount: float | None = None,
        min_balance: float | None = None
    ) -> bool:
        """Verificar saldo insuficiente e desativar autotrade"""
        try:
            account, resolved_connection_type, current_balance = await self._resolve_account_balance(
                config,
                db,
                connection_type=connection_type,
                trade=trade
            )

            if not account:
                return True

            effective_min_balance = self.MIN_BALANCE_THRESHOLD if min_balance is None else min_balance

            if current_balance <= effective_min_balance:
                logger.warning(f"🛑 Saldo insuficiente: ${current_balance:.2f} <= ${effective_min_balance:.2f}")
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Saldo insuficiente (saldo ${current_balance:.2f})",
                    account_name=account.name,
                    current_balance=current_balance,
                    account_type=resolved_connection_type,
                    min_balance=effective_min_balance,
                    required_amount=trade_amount
                )
                return False

            if trade_amount is not None and trade_amount > current_balance:
                logger.warning(f"🛑 Saldo insuficiente para operação: ${current_balance:.2f} < ${trade_amount:.2f}")
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Saldo insuficiente para operação (saldo ${current_balance:.2f})",
                    account_name=account.name,
                    current_balance=current_balance,
                    account_type=resolved_connection_type,
                    min_balance=effective_min_balance,
                    required_amount=trade_amount
                )
                return False

            return True
        except Exception as e:
            logger.error(f"Erro ao verificar saldo insuficiente: {e}", exc_info=True)
            return True

    async def _check_cooldown(self, config: AutoTradeConfig, duration: int = None) -> bool:
        """Verificar se passou o tempo mínimo entre operações"""
        # Verificar cooldown de stop consecutivo (quando no_hibernate está ativo e stop foi atingido)
        if config.consecutive_stop_cooldown_until:
            now = datetime.utcnow()
            
            # 🚨 FIX: Garantir que consecutive_stop_cooldown_until seja datetime, não string
            cooldown_until = config.consecutive_stop_cooldown_until
            if isinstance(cooldown_until, str):
                try:
                    from datetime import datetime as dt
                    cooldown_until = dt.fromisoformat(cooldown_until.replace('Z', '+00:00'))
                except Exception:
                    # Se não conseguir converter, ignorar cooldown
                    cooldown_until = None
            
            if cooldown_until and now < cooldown_until:
                remaining_time = (cooldown_until - now).total_seconds()
                logger.info(f"⏸️ [TradeExecutor] Cooldown de stop consecutivo ativo: {remaining_time:.1f}s restantes")
                # BUG FIX: Não bloquear trades completamente, apenas respeitar cooldown entre trades
                # O cooldown deve impedir trades muito próximos, não bloquear todos os trades
                # Isso permite que o sistema continue operando mesmo após um stop consecutivo
                pass
            elif cooldown_until:
                # Cooldown expirou, limpar o campo
                async with get_db_context() as db:
                    await db.execute(
                        update(AutoTradeConfig)
                        .where(AutoTradeConfig.id == config.id)
                        .values(consecutive_stop_cooldown_until=None)
                    )
                    await db.commit()

        # NOTA: O cooldown entre trades (cooldown_seconds) deve ser respeitado
        # independentemente do no_hibernate_on_consecutive_stop.
        # O no_hibernate controla apenas se a estratégia é desligada ao atingir stop,
        # não afeta o cooldown configurado entre trades normais.

        # Obter cooldown configurado (suporta formato "X-X" para randomizado)
        from utils.cooldown_utils import parse_cooldown
        cooldown_duration = parse_cooldown(config.cooldown_seconds, default=0)
        
        # Se cooldown configurado = 0, executar trades normalmente (sem espera)
        if cooldown_duration == 0:
            return True

        # Se cooldown configurado > 0, respeitar o tempo de espera entre trades
        # Se não houver timestamp do último trade, permitir
        if not config.last_trade_time:
            return True

        # Calcular tempo desde o último trade
        now = datetime.utcnow()
        
        # 🚨 FIX: Garantir que last_trade_time seja datetime, não string
        last_trade = config.last_trade_time
        if isinstance(last_trade, str):
            try:
                from datetime import datetime as dt
                last_trade = dt.fromisoformat(last_trade.replace('Z', '+00:00'))
            except Exception:
                # Se não conseguir converter, permitir trade
                return True
        
        if not isinstance(last_trade, datetime):
            # Tipo inesperado, permitir trade
            return True
            
        time_since_last_trade = (now - last_trade).total_seconds()

        # Verificar se passou o tempo mínimo configurado
        if time_since_last_trade < cooldown_duration:
            remaining_time = cooldown_duration - time_since_last_trade
            logger.info(f"⏸️ [TradeExecutor] Cooldown ativo: {remaining_time:.1f}s restantes (configurado: {config.cooldown_seconds}s)")
            return False

        return True
    
    async def _disable_autotrade(
        self,
        account_id: str,
        reason: str,
        account_name: str = None,
        loss_consecutive: int = None,
        win_consecutive: int = None,
        stop1: int = None,
        stop2: int = None,
        stop_amount: float = None,
        stop_amount_type: str = None,
        current_balance: float = None,
        account_type: str | None = None,
        min_balance: float | None = None,
        required_amount: float | None = None
    ):
        """Desativar autotrade da conta"""
        try:
            async with get_db_context() as db:
                # Desativar autotrade_demo e autotrade_real na conta
                await db.execute(
                    update(Account)
                    .where(Account.id == account_id)
                    .values(
                        autotrade_demo=False,
                        autotrade_real=False,
                        updated_at=datetime.utcnow()
                    )
                )
                logger.info(f"✓ autotrade_demo e autotrade_real desativados na conta {account_id}")
                
                # Desativar configuração de autotrade e resetar contadores
                result = await db.execute(
                    select(AutoTradeConfig).where(AutoTradeConfig.account_id == account_id)
                )
                autotrade_configs = result.scalars().all()
                
                # Buscar usuário da conta para notificação (evitar lazy-load em async)
                user_chat_id = None
                account_user_result = await db.execute(
                    select(Account.user_id).where(Account.id == account_id)
                )
                account_user_id = account_user_result.scalar_one_or_none()
                if account_user_id:
                    user_result = await db.execute(
                        select(User.telegram_chat_id).where(User.id == account_user_id)
                    )
                    user_chat_id = user_result.scalar_one_or_none()
                
                if autotrade_configs:
                    for autotrade_config in autotrade_configs:
                        autotrade_config.is_active = False
                        autotrade_config.updated_at = datetime.utcnow()
                        # Resetar contadores
                        autotrade_config.loss_consecutive = 0
                        autotrade_config.win_consecutive = 0
                        autotrade_config.soros_level = 0
                        autotrade_config.soros_amount = 0.0
                        autotrade_config.martingale_level = 0
                        autotrade_config.martingale_amount = 0.0
                        # Resetar totais para evitar que stop seja atingido novamente na reativação
                        autotrade_config.total_losses = 0
                        autotrade_config.total_wins = 0
                        # Resetar highest_balance para ser reinicializado ao ligar novamente
                        autotrade_config.highest_balance = None
                    logger.info(f"✓ Contadores, totais e highest_balance resetados")
                
                # Desativar estratégia associada
                if autotrade_configs and autotrade_configs[0].strategy_id:
                    await db.execute(
                        update(Strategy)
                        .where(Strategy.id == autotrade_configs[0].strategy_id)
                        .values(is_active=False, updated_at=datetime.utcnow())
                    )
                    logger.info(f"✓ Estratégia {autotrade_configs[0].strategy_id} desativada")
                
                await db.commit()

                logger.warning(f"🛑 Autotrade DESATIVADO para conta {account_id}: {reason}")

                # Invalidar cache das configurações de autotrade
                if hasattr(self, 'data_collector') and self.data_collector:
                    self.data_collector.invalidate_autotrade_configs_cache()

                # Desconectar conexão WebSocket do usuário
                if hasattr(self, 'connection_manager') and self.connection_manager:
                    # Desconectar ambas as conexões (demo e real) com flag PERMANENT quando apropriado
                    is_permanent = ("saldo insuficiente" in reason.lower() or 
                                    "stop amount" in reason.lower() or
                                    "all-win" in reason.lower())
                    await self.connection_manager.disconnect_connection(account_id, 'demo', permanent=is_permanent)
                    await self.connection_manager.disconnect_connection(account_id, 'real', permanent=is_permanent)
                    logger.info(f"✓ Conexões WebSocket desconectadas para conta {account_id} (permanente={is_permanent})")

                # Notificar frontend sobre mudança de status da estratégia
                if autotrade_configs and autotrade_configs[0].strategy_id and account_user_id:
                    try:
                        # Importação tardia para evitar ciclo de importação
                        from api.routers.websocket import broadcast_strategy_status_update
                        await broadcast_strategy_status_update(
                            user_id=account_user_id,
                            strategy_id=autotrade_configs[0].strategy_id,
                            is_active=False,
                            reason=reason
                        )
                        logger.info(f"✓ Notificação WebSocket enviada para usuário {account_user_id[:8]}... sobre estratégia desativada")
                    except Exception as e:
                        logger.error(f"Erro ao enviar notificação WebSocket: {e}")

                # Enviar notificação via Telegram para o usuário correto
                # Nota: Quando _disable_autotrade é chamado, a estratégia foi desligada (no_hibernate=False)
                if "Stop Loss" in reason and loss_consecutive is not None and stop2 is not None:
                    await telegram_service.send_stop_loss_notification(
                        account_name or "Desconhecida",
                        loss_consecutive,
                        stop2,
                        user_chat_id,
                        account_type=account_type,
                        no_hibernate=False
                    )
                elif "Stop Gain" in reason and win_consecutive is not None and stop1 is not None:
                    await telegram_service.send_stop_gain_notification(
                        account_name or "Desconhecida",
                        win_consecutive,
                        stop1,
                        user_chat_id,
                        account_type=account_type,
                        no_hibernate=False
                    )
                elif stop_amount_type and stop_amount is not None and current_balance is not None:
                    await telegram_service.send_stop_amount_notification(
                        account_name or "Desconhecida",
                        current_balance,
                        stop_amount,
                        stop_amount_type,
                        user_chat_id,
                        account_type=account_type
                    )
                elif min_balance is not None and current_balance is not None:
                    await telegram_service.send_insufficient_balance_notification(
                        account_name or "Desconhecida",
                        current_balance,
                        min_balance,
                        user_chat_id,
                        required_amount=required_amount,
                        account_type=account_type
                    )
                
        except Exception as e:
            logger.error(f"Erro ao desativar autotrade: {e}", exc_info=True)
    
    async def _check_stop_amount(
        self,
        trade: Optional[Trade],
        config: AutoTradeConfig,
        db,
        *,
        connection_type: Optional[str] = None
    ) -> bool:
        """Verificar stop amount (valores monetários) baseado no saldo da conta"""
        try:
            stop_amount_win = config.stop_amount_win or 0
            stop_amount_loss = config.stop_amount_loss or 0

            # Se ambos stop_amount_win e stop_amount_loss são 0, não verificar
            if stop_amount_win <= 0 and stop_amount_loss <= 0:
                return True

            account, resolved_connection_type, current_balance = await self._resolve_account_balance(
                config,
                db,
                connection_type=connection_type,
                trade=trade
            )

            if not account:
                return True
            logger.info(f"💰 Saldo atual da conta: ${current_balance:.2f}")

            # Verificar Stop Amount Win (saldo da conta)
            if stop_amount_win > 0 and current_balance >= stop_amount_win:
                logger.warning(f"🎯 Stop Amount Win atingido: saldo ${current_balance:.2f} >= ${stop_amount_win:.2f}")
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Stop Amount Win atingido (saldo ${current_balance:.2f})",
                    account_name=account.name,
                    stop_amount=stop_amount_win,
                    stop_amount_type="win",
                    current_balance=current_balance,
                    account_type=resolved_connection_type
                )
                return False

            # Verificar Stop Amount Loss (saldo da conta)
            if stop_amount_loss > 0 and current_balance <= stop_amount_loss:
                logger.warning(f"🛑 Stop Amount Loss atingido: saldo ${current_balance:.2f} <= ${stop_amount_loss:.2f}")
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Stop Amount Loss atingido (saldo ${current_balance:.2f})",
                    account_name=account.name,
                    stop_amount=stop_amount_loss,
                    stop_amount_type="loss",
                    current_balance=current_balance,
                    account_type=resolved_connection_type
                )
                return False

            return True
        except Exception as e:
            logger.error(f"Erro ao verificar stop amount: {e}", exc_info=True)
            return True

    async def _check_stop_loss(self, config: AutoTradeConfig) -> bool:
        """Verificar stop gain e stop loss baseado em totais (não consecutivos)"""
        # Se ambos stop1 e stop2 são 0, funciona indefinidamente (sem stops)
        if config.stop1 == 0 and config.stop2 == 0:
            return True

        # Carregar account explicitamente para evitar lazy load fora da sessão
        account_name = None
        account_type = None
        if config.account_id:
            async with get_db_context() as db:
                result = await db.execute(select(Account).where(Account.id == config.account_id))
                account = result.scalar_one_or_none()
                if account:
                    account_name = account.name
                    if account.autotrade_real:
                        account_type = "real"
                    elif account.autotrade_demo:
                        account_type = "demo"

        # Verificar stop loss primeiro (prioridade máxima)
        if config.stop2 > 0 and config.total_losses is not None and config.total_losses >= config.stop2:
            logger.warning(f"🛑 Stop Loss atingido: {config.total_losses} perdas totais")
            if config.no_hibernate_on_consecutive_stop:
                await self._apply_consecutive_stop_cooldown(
                    config,
                    reason="Stop Loss atingido",
                    account_name=account_name,
                    account_type=account_type,
                )
                return False
            else:
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Stop Loss atingido ({config.total_losses} perdas totais)",
                    account_name=account_name or "Desconhecida",
                    loss_consecutive=config.total_losses,
                    stop2=config.stop2,
                    account_type=account_type,
                )
                return False

        # Verificar stop gain
        if config.stop1 > 0 and config.total_wins is not None and config.total_wins >= config.stop1:
            logger.info(f"🎯 Stop Gain atingido: {config.total_wins} vitórias totais")
            if config.no_hibernate_on_consecutive_stop:
                await self._apply_consecutive_stop_cooldown(
                    config,
                    reason="Stop Gain atingido",
                    account_name=account_name,
                    account_type=account_type,
                )
                return False
            else:
                await self._disable_autotrade(
                    account_id=config.account_id,
                    reason=f"Stop Gain atingido ({config.total_wins} vitórias totais)",
                    account_name=account_name or "Desconhecida",
                    win_consecutive=config.total_wins,
                    stop1=config.stop1,
                    account_type=account_type,
                )
                return False

        return True
    
    async def _process_pending_expired_trades(self, account_id: str) -> None:
        """Processar trades expirados pendentes para garantir estado atualizado dos contadores
        
        Esta função é CRÍTICA para evitar race conditions onde um trade é executado
        antes que o resultado do trade anterior seja processado e commitado.
        
        Args:
            account_id: ID da conta para verificar trades pendentes
        """
        try:
            async with get_db_context() as db:
                now = datetime.utcnow()
                # Buscar trades ativos que já expiraram (há pelo menos 1 segundo)
                # mas ainda não tiveram seu resultado processado
                query = select(Trade).where(
                    Trade.account_id == account_id,
                    Trade.status == TradeStatus.ACTIVE,
                    Trade.expires_at <= now
                )
                result = await db.execute(query)
                expired_trades = result.scalars().all()
                
                if expired_trades:
                    logger.info(
                        f"🔄 [TradeExecutor] {len(expired_trades)} trade(s) expirado(s) pendente(s) "
                        f"para conta {account_id[:8]}... Processando antes de executar novo trade"
                    )
                    
                    for trade in expired_trades:
                        try:
                            # Processar resultado do trade expirado
                            await self._check_trade_result(trade, db)
                            logger.info(
                                f"✅ [TradeExecutor] Trade pendente {trade.id[:8]} processado "
                                f"(status: {trade.status.value})"
                            )
                        except Exception as e:
                            logger.error(
                                f"❌ [TradeExecutor] Erro ao processar trade pendente {trade.id[:8]}: {e}",
                                exc_info=True
                            )
                            # Continuar processando outros trades mesmo se um falhar
                            continue
                    
                    logger.info(
                        f"✅ [TradeExecutor] Todos os trades pendentes processados para conta {account_id[:8]}"
                    )
                else:
                    logger.debug(
                        f"✅ [TradeExecutor] Nenhum trade expirado pendente para conta {account_id[:8]}"
                    )
        except Exception as e:
            # Não bloquear a execução se houver erro ao processar trades pendentes
            # Apenas logar o erro e continuar
            logger.error(
                f"⚠️ [TradeExecutor] Erro ao verificar trades pendentes para conta {account_id[:8]}: {e}",
                exc_info=True
            )

    async def _check_no_active_trades(
        self, 
        account_id: str, 
        symbol: Optional[str] = None,
        execute_all_signals: bool = False
    ) -> bool:
        """Verificar se não há trades ativos para garantir funcionamento correto do soros/martingale
        
        Args:
            account_id: ID da conta
            symbol: Símbolo do ativo (opcional) - se fornecido, verifica se há trades ativos especificamente para este ativo
            execute_all_signals: Se True, ignora o bloqueio e permite múltiplas operações simultâneas
        """
        # Se execute_all_signals estiver ativo, ignorar verificação de trades ativos
        if execute_all_signals:
            logger.info(f"[TradeExecutor] 🚀 EXECUTAR TODOS SINAIS ativo - ignorando bloqueio de trades simultâneos para {account_id[:8]}...")
            return True
        
        async with get_db_context() as db:
            # Construir query base
            query = select(Trade).where(
                Trade.account_id == account_id,
                Trade.status == TradeStatus.ACTIVE
            )
            
            # Se symbol fornecido, verificar também por ativo específico
            if symbol:
                asset_id = ASSETS.get(symbol)
                if asset_id:
                    query = query.where(Trade.asset_id == asset_id)
            
            result = await db.execute(query)
            active_trades = result.scalars().all()

            if not active_trades:
                logger.debug(f"✅ [TradeExecutor] Nenhum trade ativo para conta {account_id[:8]}... no ativo {symbol}")
                return True

            now = datetime.utcnow()
            expired_trades = [trade for trade in active_trades if trade.expires_at and trade.expires_at <= now]

            if expired_trades:
                logger.info(
                    f"🔄 [TradeExecutor] {len(expired_trades)} trade(s) expirado(s) para conta {account_id[:8]}... verificando resultado"
                )
                for trade in expired_trades:
                    await self._check_trade_result(trade, db)

                # Recarregar trades ativos após verificar resultados
                result = await db.execute(query)
                active_trades = result.scalars().all()

            if active_trades:
                trade_info = f" ({len(active_trades)} trade(s) ativo(s)"
                if symbol:
                    trade_info += f" no ativo {symbol}"
                trade_info += f" - IDs: {[t.id[:8] for t in active_trades]}"
                trade_info += ")"
                logger.warning(f"🚫 [TradeExecutor] {account_id[:8]}...{trade_info} - BLOQUEANDO novo trade")
                return False

            logger.debug(f"✅ [TradeExecutor] Trades expirados processados, nenhum trade ativo restante para {account_id[:8]}... no ativo {symbol}")
            return True
    
    async def _calculate_trade_amount(self, config: AutoTradeConfig) -> float:
        """Calcular valor do trade aplicando soros ou martingale"""
        base_amount = config.amount

        # Validar base_amount
        if base_amount is None or base_amount <= 0:
            logger.error(f"❌ Base amount inválido: ${base_amount}")
            return base_amount or 0

        # Verificar All-win ao chegar em % da banca
        all_win_percentage = getattr(config, 'all_win_percentage', 0)
        if all_win_percentage and all_win_percentage > 0 and config.highest_balance:
            try:
                # Não acessar config.account para evitar lazy-loading
                # Tentar obter saldo da conexão WebSocket existente
                balance = None

                # Tentar conexão demo primeiro
                connection_key_demo = f"{config.account_id}_demo"
                connection_key_real = f"{config.account_id}_real"

                if self.connection_manager and connection_key_demo in self.connection_manager.connections:
                    connection = self.connection_manager.connections[connection_key_demo]
                    if connection.client and hasattr(connection.client, 'get_balance'):
                        try:
                            # Usar ResilienceExecutor para proteger contra timeout
                            balance_obj = await self._resilience.execute(
                                connection.client.get_balance(),
                                operation_name=f"get_balance_{connection_key_demo}"
                            )
                            if balance_obj and hasattr(balance_obj, 'balance'):
                                balance = balance_obj.balance
                        except Exception as e:
                            logger.warning(f"Erro ao obter saldo da conexão WebSocket: {e}")

                # Se não conseguiu da demo, tentar real
                if balance is None and self.connection_manager and connection_key_real in self.connection_manager.connections:
                    connection = self.connection_manager.connections[connection_key_real]
                    if connection.client and hasattr(connection.client, 'get_balance'):
                        try:
                            # Usar ResilienceExecutor para proteger contra timeout
                            balance_obj = await self._resilience.execute(
                                connection.client.get_balance(),
                                operation_name=f"get_balance_{connection_key_real}"
                            )
                            if balance_obj and hasattr(balance_obj, 'balance'):
                                balance = balance_obj.balance
                        except Exception as e:
                            logger.warning(f"Erro ao obter saldo da conexão WebSocket: {e}")

                # Se não conseguiu obter da WebSocket, não podemos verificar all-win
                if balance is None:
                    logger.debug(f"⚠️ All-win configurado ({all_win_percentage}%) mas não foi possível obter saldo atual. highest_balance=${config.highest_balance:.2f}")
                    return base_amount

                # Calcular threshold
                threshold = config.highest_balance * (all_win_percentage / 100)

                if balance < threshold:
                    logger.info(f"🎯 All-win ativado! Saldo atual ${balance:.2f} < {all_win_percentage}% do highest_balance (${config.highest_balance:.2f}, threshold=${threshold:.2f})")
                    # All-win: desativar autotrade para evitar mais perdas
                    await self._disable_autotrade(config, reason=f"All-win ativado: saldo ${balance:.2f} < {all_win_percentage}% do highest_balance (${config.highest_balance:.2f})")
                    return 0.0  # Retorna 0 para indicar que trade não deve ser executado
                else:
                    logger.debug(f"💰 Saldo atual ${balance:.2f} >= {all_win_percentage}% do highest_balance (${threshold:.2f}), all-win desativado")
            except Exception as e:
                logger.warning(f"⚠️ Erro ao verificar all-win: {e}")

        # PASSO 1: Aplicar Redução Inteligente primeiro (se ativa)
        # Isso garante que Soros/Martingale trabalhem com o valor correto
        smart_reduction_enabled = getattr(config, 'smart_reduction_enabled', False)
        smart_reduction_active = getattr(config, 'smart_reduction_active', False)
        smart_reduction_percentage = getattr(config, 'smart_reduction_percentage', 50.0)
        smart_reduction_base_amount = getattr(config, 'smart_reduction_base_amount', 0.0)
        smart_reduction_cascading = getattr(config, 'smart_reduction_cascading', False)
        smart_reduction_cascade_level = getattr(config, 'smart_reduction_cascade_level', 0)
        
        effective_base_amount = base_amount  # Valor que será usado para Soros/Martingale
        
        logger.info(f"🔍 [_calculate_trade_amount] Redução Inteligente: enabled={smart_reduction_enabled}, active={smart_reduction_active}, percentage={smart_reduction_percentage}, base_amount_saved={smart_reduction_base_amount}, cascading={smart_reduction_cascading}, cascade_level={smart_reduction_cascade_level}")
        
        if smart_reduction_enabled and smart_reduction_active:
            # Calcular redução efetiva total
            reduction_factor = (100 - smart_reduction_percentage) / 100
            if smart_reduction_cascading and smart_reduction_cascade_level > 1:
                effective_reduction_pct = (1 - reduction_factor ** smart_reduction_cascade_level) * 100
                logger.info(f"📉 Redução Inteligente: ATIVA (nível={smart_reduction_cascade_level}, cascata={smart_reduction_cascading}, redução_efetiva={effective_reduction_pct:.1f}%, base=${base_amount:.2f} → efetivo=${effective_base_amount:.2f})")
            
            if smart_reduction_cascading and smart_reduction_cascade_level > 0:
                # Redução em cascata: aplica a redução múltiplas vezes baseado no nível
                # Ex: base $10, 50% redução, nível 2 → $10 * 0.5 * 0.5 = $2.50
                total_reduction_factor = reduction_factor ** smart_reduction_cascade_level
                effective_base_amount = base_amount * total_reduction_factor
                logger.info(f"📉 Redução Inteligente CASCATA ATIVA (nível {smart_reduction_cascade_level}): ${effective_base_amount:.2f} (redução {smart_reduction_percentage}% aplicada {smart_reduction_cascade_level}x, valor original: ${base_amount:.2f})")
            else:
                # Redução simples (nível 1)
                effective_base_amount = base_amount * reduction_factor
                logger.info(f"📉 Redução Inteligente ATIVA: ${effective_base_amount:.2f} (reduzido em {smart_reduction_percentage}%, valor original: ${base_amount:.2f})")
            
            # FLOOR: Garantir valor mínimo de $1 (mínimo da corretora)
            MIN_TRADE_AMOUNT = 1.0
            if effective_base_amount < MIN_TRADE_AMOUNT:
                effective_base_amount = MIN_TRADE_AMOUNT
                logger.warning(f"⚠️ Valor reduzido abaixo do mínimo (${MIN_TRADE_AMOUNT}). Ajustado para: ${effective_base_amount:.2f}")
                
        elif smart_reduction_enabled and not smart_reduction_active:
            logger.info(f"📊 Redução Inteligente DESATIVADA - usando base amount: ${base_amount:.2f}")

        # PASSO 2: Aplicar Soros/Martingale sobre o valor efetivo (já reduzido se necessário)
        
        # Se Soros estiver ativo e houver vitórias consecutivas
        if config.soros > 0 and config.soros_level is not None and config.soros_level > 0:
            # Soros: Usa o valor acumulado (soros_amount), mas respeita o valor base efetivo
            # Se não houver soros_amount, usa o valor efetivo (reduzido ou não)
            soros_amount = config.soros_amount if config.soros_amount and config.soros_amount > 0 else effective_base_amount
            # Garantir que o valor do Soros não seja menor que o valor efetivo base
            if soros_amount < effective_base_amount:
                soros_amount = effective_base_amount
                logger.info(f"📊 Soros ajustado para valor efetivo base: ${soros_amount:.2f}")
            logger.info(f"📊 Usando Soros: ${soros_amount:.2f} (nível={config.soros_level})")
            return soros_amount

        # Se Martingale estiver ativo e houver perdas consecutivas
        if config.martingale > 0 and config.martingale_level is not None and config.martingale_level > 0:
            # Martingale: Usa o valor atual do Martingale, mas respeita o valor base efetivo
            martingale_amount = config.martingale_amount if config.martingale_amount and config.martingale_amount > 0 else effective_base_amount
            # Garantir que o valor do Martingale não seja menor que o valor efetivo base
            if martingale_amount < effective_base_amount:
                martingale_amount = effective_base_amount
                logger.info(f"📊 Martingale ajustado para valor efetivo base: ${martingale_amount:.2f}")
            logger.info(f"📊 Usando Martingale: ${martingale_amount:.2f} (nível={config.martingale_level})")
            return martingale_amount

        # Se não houver Soros/Martingale ativo, retorna o valor efetivo (reduzido ou base)
        logger.info(f"📊 Usando valor efetivo: ${effective_base_amount:.2f}")
        return effective_base_amount
    
    async def _update_autotrade_counters_after_trade(self, trade: Trade, config: AutoTradeConfig, db, current_balance: float = None):
        """Atualizar contadores da configuração de autotrade após executar trade"""
        try:
            # Atualizar contadores diretamente no objeto config (já está no contexto do banco)
            config.daily_trades_count += 1
            config.last_trade_date = datetime.utcnow()
            config.last_trade_time = datetime.utcnow()  # Atualizar timestamp para cooldown
            config.last_activity_timestamp = datetime.utcnow()  # Atualizar timestamp de atividade para desconexão de inativos
            config.updated_at = datetime.utcnow()

            logger.info(f"Contadores atualizados: trades={config.daily_trades_count}")

            # Atualizar highest_balance se o saldo atual for maior
            if current_balance:
                # Se highest_balance ainda não foi inicializado, inicializar com o saldo atual
                if config.highest_balance is None:
                    config.highest_balance = current_balance
                    logger.info(f"💰 highest_balance inicializado: ${current_balance:.2f} para config {config.id}")
                elif current_balance > config.highest_balance:
                    old_highest = config.highest_balance
                    config.highest_balance = current_balance
                    logger.info(f"📈 highest_balance atualizado: ${old_highest:.2f} → ${current_balance:.2f}")

            if trade.status == TradeStatus.WIN:
                # Contador de vitórias totais (não consecutivas)
                if config.total_wins is None:
                    config.total_wins = 0
                config.total_wins += 1
                logger.info(f"📈 Vitória total: {config.total_wins}")

                # Contador de vitórias consecutivas para stop gain (independente de soros)
                if config.win_consecutive is None:
                    config.win_consecutive = 0
                config.win_consecutive += 1
                logger.info(f"📈 Vitória consecutiva: {config.win_consecutive}")

                # Soros: Incrementar nível e somar lucro ao valor
                if config.soros > 0:
                    # Validar profit antes de usar
                    profit = 0
                    if trade.profit is not None:
                        if trade.profit > 0:
                            profit = trade.profit
                        else:
                            logger.warning(f"⚠️ Profit não positivo: ${trade.profit:.2f}, usando 0")
                    else:
                        logger.warning(f"⚠️ Profit é None, usando 0")

                    # Determinar o valor base efetivo para Soros (considerando redução inteligente)
                    smart_reduction_active = getattr(config, 'smart_reduction_active', False)
                    smart_reduction_percentage = getattr(config, 'smart_reduction_percentage', 50.0)
                    
                    if smart_reduction_active:
                        # Se redução está ativa, usar valor reduzido como base
                        effective_soros_base = config.amount * ((100 - smart_reduction_percentage) / 100)
                        logger.info(f"📊 Soros com Redução Ativa: base=${effective_soros_base:.2f} (reduzido de ${config.amount:.2f})")
                    else:
                        # Sem redução, usar valor normal
                        effective_soros_base = config.amount

                    if config.soros_level is None or config.soros_level == 0:
                        # Primeira vitória: iniciar Soros nível 1 (primeiro trade aumentado)
                        config.soros_level = 1
                        # Valor = base efetiva + lucro do trade anterior
                        config.soros_amount = effective_soros_base + profit
                        logger.info(f"📈 Soros iniciado: nível={config.soros_level}/{config.soros}, amount=${config.soros_amount:.2f} (base=${effective_soros_base:.2f}, profit=${profit:.2f})")
                    elif config.soros_level >= config.soros:
                        # ATINGIU LIMITE: resetar soros, não fazer mais trades aumentados
                        logger.warning(f"✅ Soros atingiu limite {config.soros}! Resetando para valor base efetivo")
                        config.soros_level = 0
                        config.soros_amount = 0.0
                    else:
                        # Continuar Soros: próximo nível (se ainda não atingiu limite)
                        config.soros_level += 1
                        config.soros_amount += profit
                        logger.info(f"📈 Soros continuando: nível={config.soros_level}/{config.soros}, amount=${config.soros_amount:.2f} (profit=${profit:.2f})")

                # Martingale: Resetar após vitória
                if config.martingale > 0:
                    config.martingale_level = 0
                    config.martingale_amount = 0.0
                    logger.info(f"✅ Martingale resetado após vitória")

                # Resetar contador de perdas consecutivas
                config.loss_consecutive = 0
                logger.info(f"✅ Contador de perdas consecutivas resetado")
                
                # Redução Inteligente: Verificar se atingiu wins consecutivos para restaurar
                smart_reduction_enabled = getattr(config, 'smart_reduction_enabled', False)
                smart_reduction_active = getattr(config, 'smart_reduction_active', False)
                smart_reduction_win_restore = getattr(config, 'smart_reduction_win_restore', 2)
                
                if smart_reduction_enabled and smart_reduction_active:
                    # Incrementar contador específico de wins para restauração
                    if config.smart_reduction_win_count is None:
                        config.smart_reduction_win_count = 0
                    config.smart_reduction_win_count += 1
                    logger.info(f"🔄 Redução Inteligente: win {config.smart_reduction_win_count}/{smart_reduction_win_restore} para restaurar valor")
                    
                    if config.smart_reduction_win_count >= smart_reduction_win_restore:
                        # Restaurar valor normal
                        config.smart_reduction_active = False
                        smart_reduction_base_amount = getattr(config, 'smart_reduction_base_amount', 0.0)
                        if smart_reduction_base_amount > 0:
                            config.amount = smart_reduction_base_amount
                            logger.info(f"🔄 Redução Inteligente DESATIVADA após {config.smart_reduction_win_count} vitórias. Valor restaurado para: ${config.amount:.2f}")
                        else:
                            logger.info(f"🔄 Redução Inteligente DESATIVADA após {config.smart_reduction_win_count} vitórias.")
                        # Resetar AMBOS os contadores específicos para começar fresh
                        config.smart_reduction_loss_count = 0
                        config.smart_reduction_win_count = 0
                        config.smart_reduction_base_amount = 0.0
                        # Resetar nível de cascata
                        config.smart_reduction_cascade_level = 0
                        logger.info(f"✅ Contadores da Redução Inteligente resetados (loss_count=0, win_count=0, cascade_level=0)")
                elif smart_reduction_enabled and not smart_reduction_active:
                    # Redução desativada e vitória ocorreu - resetar contador de losses para não acumular
                    if config.smart_reduction_loss_count is not None and config.smart_reduction_loss_count > 0:
                        logger.info(f"✅ Redução Inteligente: Vitória com redução inativa. Resetando loss_count de {config.smart_reduction_loss_count} para 0")
                        config.smart_reduction_loss_count = 0

                logger.info(f"✓ WIN: lucro=${trade.profit if trade.profit else 0:.2f}")

            elif trade.status == TradeStatus.LOSS:
                # Contador de perdas totais (não consecutivas)
                if config.total_losses is None:
                    config.total_losses = 0
                config.total_losses += 1
                # Log silenciado
                # logger.info(f"📉 Perda total: {config.total_losses}")

                # Soros: Resetar após perda
                if config.soros > 0:
                    if config.soros_amount > 0:
                        logger.warning(f"❌ Soros resetado após perda, valor acumulado perdido: ${config.soros_amount:.2f}")
                    config.soros_level = 0
                    config.soros_amount = 0.0

                # Resetar contador de vitórias consecutivas
                config.win_consecutive = 0
                logger.info(f"❌ Contador de vitórias consecutivas resetado")

                # Contador de perdas consecutivas para stop loss (independente de martingale)
                if config.loss_consecutive is None:
                    config.loss_consecutive = 0
                config.loss_consecutive += 1
                logger.info(f"📉 Perda consecutiva: {config.loss_consecutive}")
                
                # Redução Inteligente: Verificar se atingiu losses para reduzir (usando contadores separados)
                smart_reduction_enabled = getattr(config, 'smart_reduction_enabled', False)
                smart_reduction_loss_trigger = getattr(config, 'smart_reduction_loss_trigger', 3)
                smart_reduction_percentage = getattr(config, 'smart_reduction_percentage', 50.0)
                smart_reduction_active = getattr(config, 'smart_reduction_active', False)
                smart_reduction_win_restore = getattr(config, 'smart_reduction_win_restore', 2)
                
                # Só incrementar contador de losses se Redução Inteligente estiver habilitada
                if smart_reduction_enabled:
                    # Inicializar contador específico se necessário
                    if config.smart_reduction_loss_count is None:
                        config.smart_reduction_loss_count = 0
                    
                    # Incrementar contador específico de losses
                    config.smart_reduction_loss_count += 1
                    
                    logger.info(f"🔍 [REDUÇÃO INTELIGENTE] Contadores: loss_count={config.smart_reduction_loss_count}/{smart_reduction_loss_trigger}, win_count={config.smart_reduction_win_count}, cascade_level={getattr(config, 'smart_reduction_cascade_level', 0)}, enabled={smart_reduction_enabled}, active={smart_reduction_active}, cascading={getattr(config, 'smart_reduction_cascading', False)}")
                    
                    if not smart_reduction_active:
                        if config.smart_reduction_loss_count >= smart_reduction_loss_trigger:
                            # Ativar redução - salvar valor base e ativar
                            if getattr(config, 'smart_reduction_base_amount', 0.0) == 0:
                                config.smart_reduction_base_amount = config.amount
                            config.smart_reduction_active = True
                            # Inicializar nível de cascata (nível 1 = primeira redução)
                            config.smart_reduction_cascade_level = 1
                            # NÃO resetar contador de losses aqui - queremos ver o total acumulado
                            # Resetar contador de wins para restauração
                            config.smart_reduction_win_count = 0
                            logger.warning(f"🚨 Redução Inteligente ATIVADA (nível cascata=1) após {config.smart_reduction_loss_count} losses. Redução de {smart_reduction_percentage}% aplicada.")
                        else:
                            logger.info(f"⏳ Redução Inteligente: {config.smart_reduction_loss_count}/{smart_reduction_loss_trigger} losses. Ainda não atingiu trigger.")
                    else:
                        # Se já está ativa e teve loss
                        smart_reduction_cascading = getattr(config, 'smart_reduction_cascading', False)
                        
                        if smart_reduction_cascading and config.smart_reduction_loss_count >= smart_reduction_loss_trigger:
                            # CASCATA: Já está em redução, atingiu trigger de novo → aumentar nível
                            config.smart_reduction_cascade_level += 1
                            # NÃO resetar contador de losses - manter acumulado para visibilidade
                            # Resetar apenas contador de wins para restauração
                            config.smart_reduction_win_count = 0
                            
                            # Calcular novo valor reduzido
                            reduction_factor = (100 - smart_reduction_percentage) / 100
                            new_reduced_amount = config.amount * (reduction_factor ** config.smart_reduction_cascade_level)
                            
                            # FLOOR: Garantir mínimo de $1
                            MIN_TRADE_AMOUNT = 1.0
                            if new_reduced_amount < MIN_TRADE_AMOUNT:
                                new_reduced_amount = MIN_TRADE_AMOUNT
                                logger.warning(f"⚠️ Redução Cascata limitada ao mínimo de ${MIN_TRADE_AMOUNT}")
                            
                            logger.warning(f"🚨🚨 REDUÇÃO CASCATA ATIVADA! Nível {config.smart_reduction_cascade_level} após {config.smart_reduction_loss_count} losses. "
                                         f"Novo valor: ${new_reduced_amount:.2f} (redução {smart_reduction_percentage}% sobre valor já reduzido)")
                        else:
                            # Sem cascata ou não atingiu trigger: apenas resetar contadores de wins
                            config.smart_reduction_win_count = 0
                            logger.info(f"📉 Redução Inteligente ATIVA. Perda registrada - win_count resetado. Aguardando {smart_reduction_win_restore} wins consecutivos para restaurar.")
                else:
                    # Redução Inteligente desativada - não incrementar contadores
                    logger.debug(f"🔍 [REDUÇÃO INTELIGENTE] Desativada - contadores não alterados")

                # Martingale: Incrementar nível após perda (apenas se configurado)
                if config.martingale > 0:
                    if config.martingale_level is None:
                        config.martingale_level = 0
                    elif config.martingale_level < config.martingale:
                        config.martingale_level += 1

                        # Limitar martingale_level para evitar overflow
                        if config.martingale_level > 10:
                            config.martingale_level = 10
                            logger.warning(f"⚠️ Martingale nível limitado a 10 para evitar overflow")

                        # Se Soros estava ativo antes da perda, usar o soros_amount como base
                        # Caso contrário, usar o valor base
                        base_amount = config.soros_amount if config.soros_amount and config.soros_amount > config.amount else config.amount
                        config.martingale_amount = base_amount * (2 ** config.martingale_level)

                        # Validar martingale_amount
                        if config.martingale_amount > 10000:  # Limite de segurança
                            logger.error(f"❌ Martingale amount excede limite: ${config.martingale_amount:.2f} > $10000")
                            config.martingale_amount = 10000

                        if config.martingale_amount < config.amount:
                            logger.warning(f"⚠️ Martingale amount menor que base: ${config.martingale_amount:.2f} < ${config.amount:.2f}, usando base")
                            config.martingale_amount = config.amount

                        logger.info(f"📉 Martingale: nível={config.martingale_level}/{config.martingale}, amount=${config.martingale_amount:.2f} (base=${base_amount:.2f})")
                    else:
                        # Martingale atingiu o limite: resetar
                        logger.warning(f"⚠️ Martingale atingiu limite! Resetando para valor base")
                        config.martingale_level = 0
                        config.martingale_amount = 0.0

                logger.info(f"✗ LOSS: lucro=${trade.profit if trade.profit else 0:.2f}")

                # Logging detalhado para identificar causa raiz
                logger.info(f"📊 DETALHES DO TRADE FINALIZADO:")
                logger.info(f"  - Status: {trade.status.value}")
                logger.info(f"  - Amount: ${trade.amount:.2f}")
                logger.info(f"  - Profit: ${trade.profit if trade.profit else 0:.2f}")
                logger.info(f"  - Entry Price: ${trade.entry_price:.5f}")
                logger.info(f"  - Exit Price: ${trade.exit_price:.5f}")
                logger.info(f"  - Payout: {trade.payout if trade.payout else 0:.1f}%")
                logger.info(f"  - Soros: nível={config.soros_level}, amount=${config.soros_amount:.2f}")
                logger.info(f"  - Martingale: nível={config.martingale_level}, amount=${config.martingale_amount:.2f}")
                logger.info(f"  - Base Amount: ${config.amount:.2f}")
                logger.info(f"  - Consecutive Wins: {config.win_consecutive}")
                logger.info(f"  - Consecutive Losses: {config.loss_consecutive}")
                # Redução Inteligente - resumo estruturado
                sr_active = getattr(config, 'smart_reduction_active', False)
                sr_cascading = getattr(config, 'smart_reduction_cascading', False)
                sr_level = getattr(config, 'smart_reduction_cascade_level', 0)
                sr_percentage = getattr(config, 'smart_reduction_percentage', 50.0)
                if sr_active:
                    effective_reduction = (1 - ((100 - sr_percentage) / 100) ** sr_level) * 100 if sr_level > 0 else sr_percentage
                    logger.info(f"  - Redução: ATIVA (nível={sr_level}, cascata={sr_cascading}, efetiva={effective_reduction:.1f}%)")

            # Atualizar timestamp
            config.updated_at = datetime.utcnow()

            await db.flush()
            await db.commit()
            logger.info(f"Contadores atualizados: soros_level={config.soros_level}, martingale_level={config.martingale_level}")

            # Verificar Stop Amount (valores monetários)
            stop_amount_ok = await self._check_stop_amount(trade, config, db)
            if not stop_amount_ok:
                return

            balance_ok = await self._check_insufficient_balance(
                config,
                db,
                trade=trade
            )
            if not balance_ok:
                return

            # Verificar Stop Gain/Loss após atualizar contadores
            await self._check_stop_loss(config)

            # Atualizar estatísticas da estratégia
            await self._update_strategy_stats(trade, db)

        except Exception as e:
            logger.error(f"Erro ao atualizar contadores de autotrade: {e}", exc_info=True)

    async def _update_strategy_stats(self, trade: Trade, db):
        """Atualizar estatísticas da estratégia quando um trade é fechado"""
        try:
            if not trade.strategy_id:
                return

            from models import Strategy
            from sqlalchemy import update

            # Buscar a estratégia
            result = await db.execute(
                select(Strategy).where(Strategy.id == trade.strategy_id)
            )
            strategy = result.scalar_one_or_none()

            if not strategy:
                return

            # Atualizar estatísticas
            strategy.total_trades += 1
            strategy.last_executed = datetime.utcnow()

            if trade.status == TradeStatus.WIN:
                strategy.winning_trades += 1
                if trade.profit and trade.profit > 0:
                    strategy.total_profit += trade.profit
            elif trade.status == TradeStatus.LOSS:
                strategy.losing_trades += 1
                if trade.profit and trade.profit < 0:
                    strategy.total_loss += abs(trade.profit)

            strategy.updated_at = datetime.utcnow()

            await db.commit()
            logger.info(f"✓ Estatísticas da estratégia {strategy.id[:8]}... atualizadas: total_trades={strategy.total_trades}, winning={strategy.winning_trades}, losing={strategy.losing_trades}")

        except Exception as e:
            logger.error(f"Erro ao atualizar estatísticas da estratégia: {e}", exc_info=True)

    async def _update_autotrade_counters_on_close(self, trade: Trade, db):
        """Atualizar contadores após o fechamento do trade"""
        try:
            configs = await self._fetch_account_configs(db, trade.account_id)
            config = self._choose_account_config(configs, trade.account_id)

            if not config:
                logger.warning(f"Configuração de autotrade não encontrada para conta {trade.account_id}")
                return

            await self._update_autotrade_counters_after_trade(trade, config, db)

        except Exception as e:
            logger.error(f"Erro ao atualizar contadores após fechamento do trade: {e}", exc_info=True)

    async def _place_order(
        self,
        connection: Any,
        symbol: str,
        signal: Dict[str, Any],
        amount: float,
        duration: int,
        strategy_id: Optional[str] = None
    ) -> Optional[Trade]:
        """Colocar ordem na PocketOption"""
        try:
            # Converter sinal para direção
            if signal.signal_type == 'buy':
                direction = OrderDirection.CALL
            elif signal.signal_type == 'sell':
                direction = OrderDirection.PUT
            else:
                logger.warning(f"Tipo de sinal inválido: {signal.signal_type}")
                return None
            
            # Executar ordem com ResilienceExecutor para timeout protegido
            order_result = await self._resilience.execute(
                connection.client.place_order(
                    asset=symbol,
                    amount=amount,
                    direction=direction,
                    duration=duration
                ),
                operation_name=f"place_order_{symbol}"
            )
            
            # Verificar se a ordem foi colocada com sucesso
            if not order_result or order_result.error_message:
                logger.error(f"Falha ao executar ordem: {order_result.error_message if order_result else 'No result'}")
                return None
            
            # Salvar trade no banco de dados
            trade = await self._save_trade(
                connection=connection,
                symbol=symbol,
                signal=signal,
                amount=amount,
                duration=duration,
                order_result=order_result,
                strategy_id=strategy_id
            )
            
            return trade
            
        except ConnectionError as e:
            logger.error(f"Erro de conexão ao colocar ordem: {e}", exc_info=True)
        except ValueError as e:
            logger.error(f"Erro de validação ao colocar ordem: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Erro ao colocar ordem: {e}", exc_info=True)
            return None
    
    async def _save_trade(
        self,
        connection: Any,
        symbol: str,
        signal: Dict[str, Any],
        amount: float,
        duration: int,
        order_result: Any,
        strategy_id: Optional[str] = None
    ) -> Optional[Trade]:
        """Salvar trade no banco de dados"""
        try:
            async with get_db_context() as db:
                # Obter asset_id
                asset_id = ASSETS.get(symbol)
                
                # Obter indicadores do sinal
                indicators = signal.indicators if hasattr(signal, 'indicators') else {}
                
                # Tratar dados de ML nos indicadores para evitar notação científica
                if isinstance(indicators, dict):
                    if indicators.get('ml_win_probability') is not None:
                        indicators['ml_win_probability'] = round(float(indicators['ml_win_probability']), 4)
                    if indicators.get('ml_expected_movement') is not None:
                        indicators['ml_expected_movement'] = round(float(indicators['ml_expected_movement']), 8)
                    if indicators.get('ml_sample_count') is not None:
                        indicators['ml_sample_count'] = int(indicators['ml_sample_count'])
                    if indicators.get('ml_pattern_id') is not None:
                        indicators['ml_pattern_id'] = str(indicators['ml_pattern_id'])

                # YIELD: Cedendo controle ao event loop antes de operações pesadas
                await asyncio.sleep(0)
                
                # Log resumido dos indicadores (evitar bloqueio com dados enormes)
                indicator_summary = []
                if isinstance(indicators, list):
                    indicator_summary = [f"{i.get('name', i.get('type', 'unknown'))}:{i.get('signal', '?')}" for i in indicators[:5]]
                    logger.info(f"Salvando trade com {len(indicators)} indicadores: {', '.join(indicator_summary)}{'...' if len(indicators) > 5 else ''}")
                elif isinstance(indicators, dict):
                    keys = list(indicators.keys())[:5]
                    logger.info(f"Salvando trade com indicadores dict: {', '.join(keys)}{'...' if len(indicators) > 5 else ''}")
                else:
                    logger.info(f"Salvando trade com indicadores (tipo: {type(indicators)})")
                
                # Log do order_result para debug
                logger.info(f"Order result: {order_result}")
                logger.info(f"Order result type: {type(order_result)}")
                if hasattr(order_result, '__dict__'):
                    logger.info(f"Order result attributes: {order_result.__dict__}")
                
                # Obter order_id e entry_price do order_result
                order_id = None
                entry_price = 0.0
                
                if hasattr(order_result, 'order_id'):
                    order_id = order_result.order_id
                    logger.info(f"Order ID from order_result: {order_id}")
                
                # Tentar obter o preço real de execução da corretora
                if hasattr(order_result, 'price') and order_result.price and float(order_result.price) > 0:
                    entry_price = float(order_result.price)
                    logger.info(f"Entry price from order_result: {entry_price}")
                elif hasattr(order_result, 'entry_price') and order_result.entry_price and float(order_result.entry_price) > 0:
                    entry_price = float(order_result.entry_price)
                    logger.info(f"Entry price from order_result attributes: {entry_price}")
                
                # Fallback: Se a corretora não retornou o preço, usa o preço do sinal
                if not entry_price or entry_price <= 0:
                    signal_price = getattr(signal, 'price', 0.0)
                    if signal_price and float(signal_price) > 0:
                        entry_price = float(signal_price)
                        logger.info(f"Preço da corretora não disponível, usando preço do sinal: {entry_price}")
                    else:
                        logger.warning("Nenhum preço disponível (corretora ou sinal), o trade ficará com preço 0.0")

                # Criar trade
                trade = Trade(
                    account_id=connection.account_id,
                    asset_id=asset_id,
                    strategy_id=strategy_id,
                    direction=TradeDirection.CALL if signal.signal_type == 'buy' else TradeDirection.PUT,
                    amount=amount,
                    entry_price=entry_price,
                    duration=duration,
                    status=TradeStatus.ACTIVE,
                    placed_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + pd.Timedelta(seconds=duration),
                    signal_confidence=signal.confidence,
                    signal_indicators=indicators,
                    order_id=order_id,
                    connection_type=connection.connection_type
                )
                
                db.add(trade)
                await db.commit()
                
                # 🟢 REGISTRAR TRADE EM ANDAMENTO no system_manager
                system_manager = get_system_manager()
                system_manager.register_trade_start(trade.id)
                
                # YIELD: Cedendo controle após commit do banco
                await asyncio.sleep(0)
                
                logger.info(f"Trade salvo com ID: {trade.id}, order_id: {trade.order_id}, entry_price: {trade.entry_price}, indicadores: {len(indicators) if isinstance(indicators, list) else 'N/A'}")

                # Atualizar sinal como executado (com tratamento de erro e verificação)
                if getattr(signal, "id", None):
                    try:
                        # Verificar se o trade realmente existe no banco antes de atualizar o sinal
                        trade_verify = await db.execute(
                            select(Trade).where(Trade.id == trade.id)
                        )
                        trade_exists = trade_verify.scalar_one_or_none()
                        
                        if trade_exists:
                            executed_at = trade.placed_at or datetime.utcnow()
                            await db.execute(
                                update(Signal)
                                .where(Signal.id == signal.id)
                                .values(
                                    is_executed=True,
                                    trade_id=trade.id,
                                    executed_at=executed_at
                                )
                            )
                            await db.commit()
                            logger.info(f"Sinal atualizado como executado: {signal.id} -> trade {trade.id}")
                            
                            # Registrar sinal como executado no performance monitor
                            try:
                                from services.performance_monitor import performance_monitor
                                performance_monitor.record_signal(executed=True)
                            except Exception:
                                pass
                        else:
                            logger.warning(f"Trade {trade.id} não encontrado no banco, sinal não atualizado")
                    except Exception as signal_err:
                        logger.error(f"Erro ao atualizar sinal {signal.id}: {signal_err}")
                        # Não propagar erro - o trade já foi salvo com sucesso
                
                # Atualizar daily_trades_count no mesmo contexto do banco
                configs = await self._fetch_account_configs(db, connection.account_id)
                config = self._choose_account_config(configs, connection.account_id)

                if config:
                    # Resetar contadores se for um novo dia
                    today = datetime.utcnow().date()
                    if config.last_trade_date:
                        # Handle both date and datetime objects
                        last_date = config.last_trade_date
                        if hasattr(last_date, 'date'):
                            last_date = last_date.date()
                        if last_date != today:
                            config.daily_trades_count = 0
                            config.soros_level = 0
                            config.soros_amount = 0.0
                            config.martingale_level = 0
                            config.martingale_amount = 0.0
                        logger.info(f"📅 Novo dia detectado: contadores resetados")
                    
                    # Incrementar contador de trades diários
                    config.daily_trades_count += 1
                    config.last_trade_date = datetime.utcnow()
                    config.last_trade_time = datetime.utcnow()
                    config.updated_at = datetime.utcnow()
                    
                    await db.commit()
                    logger.info(f"Contadores atualizados: trades={config.daily_trades_count}")
                    
                    # YIELD: Cedendo controle após atualização de contadores
                    await asyncio.sleep(0)
                
                return trade
                
        except Exception as e:
            logger.error(f"Erro ao salvar trade: {e}", exc_info=True)
            return None
