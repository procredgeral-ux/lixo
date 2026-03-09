from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from core.database import get_db_context
from core.config import settings
from core.system_manager import get_system_manager
from models import AutoTradeConfig, User
from services.pocketoption.maintenance_checker import maintenance_checker
from services.notifications.telegram import telegram_service


class MaintenanceHandler:
    """Gerencia ações quando manutenção é detectada"""

    def __init__(self) -> None:
        self._is_handling = False
        self._data_collector = None  # Será injetado depois

    def set_data_collector(self, data_collector) -> None:
        """Injetar referência ao DataCollectorService"""
        self._data_collector = data_collector

    async def register_callbacks(self) -> None:
        """Registrar callbacks no maintenance_checker"""
        maintenance_checker.on_maintenance_start(self._on_maintenance_start)
        maintenance_checker.on_maintenance_end(self._on_maintenance_end)

    async def _on_maintenance_start(self) -> None:
        """Ações quando manutenção é detectada"""
        if self._is_handling:
            return
        self._is_handling = True

        logger.warning("[TOOL] [MaintenanceHandler] Manutenção detectada! Desativando estratégias, desconectando usuários e deslogando...")

        # Enviar notificação Telegram
        try:
            await self._notify_maintenance_start()
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao enviar notificação Telegram: {exc}")

        # 1. Desativar todas as estratégias
        await self._disable_all_strategies()

        # 2. Desconectar todos os websockets
        await self._disconnect_all_websockets()

        # 3. Deslogar todos os usuários
        await self._logout_all_users()

        logger.warning("[WARNING] [MaintenanceHandler] Sistema em modo manutenção. Aguardando retorno da corretora...")

    async def _on_maintenance_end(self) -> None:
        """Ações quando manutenção termina"""
        if not self._is_handling:
            return
        self._is_handling = False

        logger.info("[SUCCESS] [MaintenanceHandler] Manutenção encerrada. Sistema pronto para operar.")

        # Enviar notificação Telegram
        try:
            await self._notify_maintenance_end()
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao enviar notificação Telegram: {exc}")

        # Reativar estratégias que foram desativadas
        try:
            await self._reactivate_strategies()
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reativar estratégias: {exc}")

        # Limpar cooldowns de stop consecutivo
        try:
            await self._clear_consecutive_stop_cooldowns()
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao limpar cooldowns: {exc}")

        # Reconectar websockets
        try:
            await self._reconnect_websockets()
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reconectar websockets: {exc}")

    async def _disable_all_strategies(self) -> None:
        """Desativar todas as estratégias de autotrade e salvar estado original"""
        async with get_db_context() as db:
            try:
                from sqlalchemy import select
                
                # Buscar todas as configurações de autotrade (ativas e inativas)
                stmt = select(AutoTradeConfig)
                result = await db.execute(stmt)
                configs = result.scalars().all()

                # Salvar estado original das estratégias
                self._original_strategy_states = {}
                for config in configs:
                    self._original_strategy_states[config.id] = config.is_active
                
                logger.info(f"📊 [MaintenanceHandler] Estado original salvo: {len(self._original_strategy_states)} estratégias")
                
                # Desativar apenas estratégias que estavam ativas
                count = 0
                for config in configs:
                    if config.is_active:
                        config.is_active = False
                        count += 1

                await db.commit()
                logger.success(f"✓ [MaintenanceHandler] {count} estratégias desativadas")

            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao desativar estratégias: {exc}")

    async def _disconnect_all_websockets(self) -> None:
        """Desconectar todos os clientes WebSocket"""
        try:
            if not self._data_collector:
                logger.warning("[MaintenanceHandler] DataCollector não disponível para desconectar websockets")
                return

            # Acessar o data_collector para desconectar clientes
            if self._data_collector.payout_client:
                try:
                    await self._data_collector.payout_client.disconnect()
                    logger.info("✓ [MaintenanceHandler] Cliente PAYOUT desconectado")
                except Exception as exc:
                    logger.error(f"[ERROR] [MaintenanceHandler] Erro ao desconectar PAYOUT: {exc}")

            for idx, client in enumerate(self._data_collector.ativos_clients):
                try:
                    await client.disconnect()
                    logger.info(f"✓ [MaintenanceHandler] Cliente ATIVOS #{idx+1} desconectado")
                except Exception as exc:
                    logger.error(f"[ERROR] [MaintenanceHandler] Erro ao desconectar ATIVOS #{idx+1}: {exc}")

            logger.success("✓ [MaintenanceHandler] Todos os websockets desconectados")

        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao desconectar websockets: {exc}")

    async def _logout_all_users(self) -> None:
        """Deslogar todos os usuários invalidando suas sessões"""
        async with get_db_context() as db:
            try:
                from sqlalchemy import select
                from datetime import datetime
                
                # Buscar todos os usuários
                stmt = select(User)
                result = await db.execute(stmt)
                users = result.scalars().all()

                count = 0
                for user in users:
                    # Marcar que o usuário precisa fazer login novamente
                    # Isso pode ser implementado invalidando tokens ou usando um timestamp
                    # Por simplicidade, vamos usar um campo no banco
                    user.maintenance_logout_at = datetime.utcnow()
                    count += 1

                await db.commit()
                logger.success(f"✓ [MaintenanceHandler] {count} usuários deslogados")

            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao deslogar usuários: {exc}")

    async def _reactivate_strategies(self) -> None:
        """Reativar apenas estratégias que estavam ligadas antes da manutenção"""
        async with get_db_context() as db:
            try:
                from sqlalchemy import select
                
                # Verificar se há estado original salvo
                if not hasattr(self, '_original_strategy_states') or not self._original_strategy_states:
                    logger.warning("[MaintenanceHandler] Nenhum estado original salvo, não reativando estratégias")
                    return
                
                # Buscar todas as configurações de autotrade
                stmt = select(AutoTradeConfig)
                result = await db.execute(stmt)
                configs = result.scalars().all()

                count = 0
                count_already_active = 0
                for config in configs:
                    # Reativar apenas se estava ativa antes da manutenção
                    if config.id in self._original_strategy_states and self._original_strategy_states[config.id]:
                        if not config.is_active:
                            config.is_active = True
                            count += 1
                    else:
                        if config.is_active:
                            count_already_active += 1

                await db.commit()
                logger.success(f"✓ [MaintenanceHandler] {count} estratégias reativadas, {count_already_active} já estavam ativas")

            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reativar estratégias: {exc}")

    async def _clear_consecutive_stop_cooldowns(self) -> None:
        """Limpar cooldowns de stop consecutivo quando a manutenção termina"""
        async with get_db_context() as db:
            try:
                from sqlalchemy import update
                
                # Limpar todos os cooldowns de stop consecutivo
                stmt = update(AutoTradeConfig).values(consecutive_stop_cooldown_until=None)
                await db.execute(stmt)
                await db.commit()
                logger.success("✓ [MaintenanceHandler] Cooldowns de stop consecutivo limpos")
                
                # Invalidar cache de configurações do DataCollector
                if self._data_collector:
                    self._data_collector._autotrade_configs = {}
                    self._data_collector._configs_cache_last_updated = 0
                    logger.info("✓ [MaintenanceHandler] Cache de configs invalidado")

            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao limpar cooldowns: {exc}")

    async def _reconnect_websockets(self) -> None:
        """Reconectar clientes WebSocket"""
        try:
            if not self._data_collector:
                logger.warning("[MaintenanceHandler] DataCollector não disponível para reconectar websockets")
                return

            logger.info("🔄 [MaintenanceHandler] Reconectando websockets...")

            # Reconectar payout
            if self._data_collector.payout_client:
                try:
                    await self._data_collector.payout_client.connect()
                    logger.info("✓ [MaintenanceHandler] Cliente PAYOUT reconectado")
                except Exception as exc:
                    logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reconectar PAYOUT: {exc}")

            # Reconectar clientes de ativos
            for idx, client in enumerate(self._data_collector.ativos_clients):
                try:
                    await client.connect()
                    logger.info(f"✓ [MaintenanceHandler] Cliente ATIVOS #{idx+1} reconectado")
                except Exception as exc:
                    logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reconectar ATIVOS #{idx+1}: {exc}")

            logger.success("✓ [MaintenanceHandler] Todos os websockets reconectados")
            
            # Recarregar dados históricos para evitar lacunas
            logger.info("📊 [MaintenanceHandler] Recarregando dados históricos para evitar lacunas...")
            try:
                await self._reload_historical_data()
            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao recarregar dados históricos: {exc}")

        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao reconectar websockets: {exc}")

    async def _reload_historical_data(self) -> None:
        """Recarregar dados históricos para evitar lacunas após manutenção"""
        if not self._data_collector:
            return
        
        try:
            # Obter o último timestamp salvo para cada ativo
            logger.info("📊 [MaintenanceHandler] Obtendo último timestamp salvo para cada ativo...")
            last_timestamps = self._get_last_saved_timestamps()
            
            # Armazenar os últimos timestamps no DataCollector para uso ao carregar dados
            if hasattr(self._data_collector, '_last_saved_timestamps'):
                self._data_collector._last_saved_timestamps = last_timestamps
            else:
                self._data_collector._last_saved_timestamps = last_timestamps
            
            logger.info(f"📊 [MaintenanceHandler] {len(last_timestamps)} ativos com últimos timestamps salvos")
            
            # Reiniciar monitoramento de ativos para carregar dados incrementais
            logger.info("🔄 [MaintenanceHandler] Recarregando dados incrementais...")
            await self._data_collector._start_ativos_monitoring()
            logger.success("✓ [MaintenanceHandler] Monitoramento de ativos reiniciado")
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao recarregar dados históricos: {exc}")

    def _get_last_saved_timestamps(self) -> dict:
        """Obter o último timestamp salvo para cada ativo"""
        if not self._data_collector:
            return {}
        
        last_timestamps = {}
        try:
            # Obter o último timestamp de cada ativo dos buffers
            if hasattr(self._data_collector, '_candle_buffers'):
                for asset, timeframes in self._data_collector._candle_buffers.items():
                    if '1' in timeframes and timeframes['1']:
                        candles = timeframes['1']
                        if candles:
                            last_timestamp = candles[-1]['close_time']
                            last_timestamps[asset] = last_timestamp
                            logger.debug(f"📊 [{asset}] Último timestamp salvo: {last_timestamp}")
        except Exception as exc:
            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao obter últimos timestamps: {exc}")
        
        return last_timestamps

    async def _notify_maintenance_start(self) -> None:
        """Enviar notificação Telegram quando a manutenção começa"""
        # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
        system_manager = get_system_manager()
        if not system_manager.is_notifications_enabled():
            logger.debug(f"🔕 Notificação de manutenção bloqueada - módulo de notificações desligado")
            return
            
        async with get_db_context() as db:
            try:
                from sqlalchemy import select
                # Buscar todos os usuários
                stmt = select(User)
                result = await db.execute(stmt)
                users = result.scalars().all()

                for user in users:
                    if user.telegram_chat_id:
                        message = (
                            f"[TOOL] <b>SISTEMA EM MANUTENÇÃO!</b>\n\n"
                            f"O sistema entrou em modo de manutenção.\n"
                            f"• Operações foram suspensas\n"
                            f"• Você foi deslogado\n\n"
                            f"Aguardando retorno para retomar operações."
                        )
                        try:
                            await telegram_service.send_message(message, user.telegram_chat_id)
                            logger.info(f"✓ [MaintenanceHandler] Notificação enviada para {user.email}")
                        except Exception as exc:
                            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao enviar notificação para {user.email}: {exc}")
            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao notificar início de manutenção: {exc}")

    async def _notify_maintenance_end(self) -> None:
        """Enviar notificação Telegram quando a manutenção termina"""
        # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
        system_manager = get_system_manager()
        if not system_manager.is_notifications_enabled():
            logger.debug(f"🔕 Notificação de fim de manutenção bloqueada - módulo de notificações desligado")
            return
            
        async with get_db_context() as db:
            try:
                from sqlalchemy import select
                # Buscar todos os usuários
                stmt = select(User)
                result = await db.execute(stmt)
                users = result.scalars().all()

                for user in users:
                    if user.telegram_chat_id:
                        message = (
                            f"[SUCCESS] <b>SISTEMA RETOMADO!</b>\n\n"
                            f"A manutenção foi encerrada.\n"
                            f"• Operações foram reativadas\n"
                            f"• Sistema pronto para operar\n\n"
                            f"Faça login novamente para continuar."
                        )
                        try:
                            await telegram_service.send_message(message, user.telegram_chat_id)
                            logger.info(f"✓ [MaintenanceHandler] Notificação enviada para {user.email}")
                        except Exception as exc:
                            logger.error(f"[ERROR] [MaintenanceHandler] Erro ao enviar notificação para {user.email}: {exc}")
            except Exception as exc:
                logger.error(f"[ERROR] [MaintenanceHandler] Erro ao notificar fim de manutenção: {exc}")


maintenance_handler = MaintenanceHandler()
