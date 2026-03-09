"""Serviço de notificação via Telegram"""
import asyncio
import httpx
from datetime import datetime, timedelta
from loguru import logger
from core.config import settings
from core.system_manager import get_system_manager


class TelegramNotificationService:
    """Serviço para enviar notificações via Telegram Bot"""
    
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.enabled = settings.TELEGRAM_ENABLED
        self._pending_chat_ids: dict[str, str] = {}  # username -> chat_id
        self._pending_chat_ids_lock = asyncio.Lock()

    def _format_account_type(self, account_type: str | None) -> str:
        if not account_type:
            return ""
        return f"\n🏷️ Tipo: {account_type.upper()}"
    
    def _format_time(self) -> str:
        """Formatar horário com fuso horário UTC-03:00 (Brasil)"""
        return (datetime.utcnow() - timedelta(hours=3)).strftime('%H:%M:%S')
    
    async def get_chat_id_from_username(self, username: str) -> str | None:
        """Buscar Chat ID do Telegram a partir do username usando getUpdates"""
        if not self.enabled or not self.bot_token:
            logger.warning("Telegram não configurado")
            return None

        # Remover @ do username se presente
        username = username.lstrip('@')

        # Verificar se já temos o Chat ID em cache (PRIMEIRO)
        async with self._pending_chat_ids_lock:
            cached_chat_id = self._pending_chat_ids.get(username)
        if cached_chat_id:
            logger.success(f"✅ Chat ID encontrado em cache para @{username}: {cached_chat_id}")
            return cached_chat_id

        # Capturar Chat IDs de mensagens recentes
        captured = await self.capture_chat_id_from_message()
        if username in captured:
            logger.success(f"✅ Chat ID capturado para @{username}: {captured[username]}")
            return captured[username]

        # Tentar buscar Chat ID usando getChat (pode não funcionar para usuários privados)
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getChat"
            params = {"chat_id": f"@{username}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=10.0)
                response.raise_for_status()

                data = response.json()

                if data.get("ok") and "result" in data:
                    chat_info = data["result"]
                    chat_id = chat_info.get("id")

                    if chat_id:
                        logger.success(f"✅ Chat ID encontrado para @{username}: {chat_id}")
                        async with self._pending_chat_ids_lock:
                            self._pending_chat_ids[username] = str(chat_id)
                        return str(chat_id)
                    else:
                        logger.warning(f"⚠️ Chat ID não encontrado para @{username}")
                        return None
                else:
                    logger.warning(f"⚠️ Usuário @{username} não encontrado. Peça ao usuário para enviar uma mensagem para o bot primeiro.")
                    return None

        except Exception as e:
            logger.warning(f"⚠️ Erro ao buscar Chat ID para @{username}: {e}")
            return None
    
    async def get_updates(self, offset: int = 0, limit: int = 100) -> dict:
        """Buscar atualizações do bot (mensagens recebidas)"""
        if not self.enabled or not self.bot_token:
            logger.warning("Telegram não configurado")
            return {}
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {"offset": offset, "limit": limit}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=10.0)
                response.raise_for_status()
                
                data = response.json()
                
                if data.get("ok"):
                    return data.get("result", [])
                else:
                    logger.warning(f"⚠️ Erro ao buscar atualizações: {data.get('description', 'Erro desconhecido')}")
                    return []
                
        except Exception as e:
            logger.error(f"❌ Erro ao buscar atualizações: {e}")
            return []
    
    async def capture_chat_id_from_message(self) -> dict[str, str]:
        """Capturar Chat IDs de usuários que enviaram mensagens para o bot"""
        updates = await self.get_updates()
        username_to_chat_id = {}
        
        for update in updates:
            if "message" in update:
                message = update["message"]
                chat = message.get("chat", {})
                from_user = message.get("from", {})
                
                # Usar from_user.id (chat_id pessoal) em vez de chat.id (que pode ser do grupo)
                chat_id = str(from_user.get("id"))
                username = from_user.get("username")
                
                if chat_id and username:
                    # Armazenar com e sem @ para consistência
                    username_key = f"@{username}"
                    username_to_chat_id[username_key] = chat_id
                    async with self._pending_chat_ids_lock:
                        self._pending_chat_ids[username_key] = chat_id
                        self._pending_chat_ids[username] = chat_id  # Também sem @
                    logger.success(f"✅ Chat ID pessoal capturado para @{username}: {chat_id}")
        
        return username_to_chat_id
    
    async def send_message(self, message: str, chat_id: str = None, user_name: str = None, account_id: str = None, account_type: str = None) -> bool:
        """Enviar mensagem via Telegram para um chat_id específico"""
        # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
        system_manager = get_system_manager()
        if not system_manager.is_notifications_enabled():
            logger.debug(f"🔕 Notificação bloqueada - módulo de notificações desligado")
            return False
        
        if not self.enabled or not self.bot_token:
            logger.warning("Telegram não configurado, notificação não enviada", extra={
                "user_name": user_name or "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": account_type or ""
            })
            return False

        if not chat_id:
            logger.warning("Chat ID não fornecido, notificação não enviada", extra={
                "user_name": user_name or "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": account_type or ""
            })
            return False

        # Validar que chat_id é um número válido
        try:
            int(chat_id)
        except (ValueError, TypeError):
            logger.warning(f"Chat ID inválido: {chat_id}, notificação não enviada", extra={
                "user_name": user_name or "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": account_type or ""
            })
            return False

        target_chat_id = chat_id

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": target_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data, timeout=10.0)
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.success(f"✅ Notificação Telegram enviada para chat {target_chat_id[:8]}...: {message[:50]}...", extra={
                        "user_name": user_name or "",
                        "account_id": account_id[:8] if account_id else "",
                        "account_type": account_type or ""
                    })
                    return True
                else:
                    error_desc = result.get("description", "Erro desconhecido")
                    logger.error(f"❌ Erro ao enviar notificação Telegram: {error_desc}", extra={
                        "user_name": user_name or "",
                        "account_id": account_id[:8] if account_id else "",
                        "account_type": account_type or ""
                    })
                    return False

        except httpx.HTTPStatusError as e:
            # Verificar se é erro 429 (too many requests)
            if e.response.status_code == 429:
                try:
                    error_data = e.response.json()
                    retry_after = error_data.get("parameters", {}).get("retry_after", 0)
                    logger.error(f"❌ [TELEGRAM RATE LIMIT] Erro 429: Too Many Requests. Retry after: {retry_after} segundos. Chat ID: {target_chat_id[:8]}...", extra={
                        "user_name": user_name or "",
                        "account_id": account_id[:8] if account_id else "",
                        "account_type": account_type or ""
                    })
                except:
                    logger.error(f"❌ [TELEGRAM RATE LIMIT] Erro 429: Too Many Requests. Chat ID: {target_chat_id[:8]}...", extra={
                        "user_name": user_name or "",
                        "account_id": account_id[:8] if account_id else "",
                        "account_type": account_type or ""
                    })
            else:
                logger.error(f"❌ Erro HTTP ao enviar notificação Telegram: {e.response.status_code} - {e.response.text}", extra={
                    "user_name": user_name or "",
                    "account_id": account_id[:8] if account_id else "",
                    "account_type": account_type or ""
                })
            return False
        except httpx.TimeoutException:
            logger.error("❌ Timeout ao enviar notificação Telegram", extra={
                "user_name": user_name or "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": account_type or ""
            })
            return False
        except Exception as e:
            logger.error(f"❌ Erro ao enviar notificação Telegram: {e}", extra={
                "user_name": user_name or "",
                "account_id": account_id[:8] if account_id else "",
                "account_type": account_type or ""
            })
            return False
    
    async def send_stop_loss_notification(self, account_name: str, loss_consecutive: int, stop2: int, chat_id: str = None, account_type: str | None = None, no_hibernate: bool = False):
        """Enviar notificação de stop loss atingido"""
        if no_hibernate:
            status_msg = "🔄 Estratégia permanece ATIVA (Não Hibernar ligado)"
            action_msg = "⏳ Cooldown aplicado - aguardando próximo ciclo"
        else:
            status_msg = "⚠️ Autotrade foi desativado automaticamente"
            action_msg = "🛑 Estratégia desligada"
        
        message = f"""
🛑 <b>STOP LOSS ATINGIDO!</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
📊 Perdas consecutivas: {loss_consecutive}/{stop2}

{status_msg}
{action_msg}

⏰ {self._format_time()}
"""
        return await self.send_message(message, chat_id, user_name=account_name, account_id=None, account_type=account_type)

    async def send_stop_amount_notification(
        self,
        account_name: str,
        current_balance: float,
        stop_amount: float,
        stop_type: str,
        chat_id: str = None,
        account_type: str | None = None
    ):
        """Enviar notificação de stop amount atingido"""
        stop_type_normalized = (stop_type or "").lower()
        if stop_type_normalized == "loss":
            title = "STOP AMOUNT LOSS ATINGIDO!"
            emoji = "🛑"
            label = "Stop Amount Loss"
        else:
            title = "STOP AMOUNT WIN ATINGIDO!"
            emoji = "🎯"
            label = "Stop Amount Win"

        message = f"""
{emoji} <b>{title}</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
💰 Saldo atual: ${current_balance:.2f}
🎯 {label}: ${stop_amount:.2f}

⚠️ Autotrade foi desativado automaticamente.

⏰ {self._format_time()}
"""
        return await self.send_message(message, chat_id, user_name=account_name, account_id=None, account_type=account_type)

    async def send_insufficient_balance_notification(
        self,
        account_name: str,
        current_balance: float,
        min_balance: float,
        chat_id: str = None,
        *,
        required_amount: float | None = None,
        account_type: str | None = None
    ):
        """Enviar notificação de saldo insuficiente"""
        message = f"""
🛑 <b>SALDO INSUFICIENTE!</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
💰 Saldo atual: ${current_balance:.2f}
🚫 Saldo mínimo: ${min_balance:.2f}
"""
        if required_amount is not None:
            message += f"\n💸 Valor da operação: ${required_amount:.2f}"
        message += f"""

⚠️ Autotrade foi desativado automaticamente.

⏰ {self._format_time()}
"""
        return await self.send_message(message, chat_id, user_name=account_name, account_id=None, account_type=account_type)
    
    async def send_stop_gain_notification(self, account_name: str, win_consecutive: int, stop1: int, chat_id: str = None, account_type: str | None = None, no_hibernate: bool = False):
        """Enviar notificação de stop gain atingido"""
        if no_hibernate:
            status_msg = "🔄 Estratégia permanece ATIVA (Não Hibernar ligado)"
            action_msg = "⏳ Cooldown aplicado - aguardando próximo ciclo"
        else:
            status_msg = "✅ Autotrade foi desativado automaticamente"
            action_msg = "🎯 Stop gain realizado com sucesso"
        
        message = f"""
🎯 <b>STOP GAIN ATINGIDO!</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
📊 Vitórias consecutivas: {win_consecutive}/{stop1}

{status_msg}
{action_msg}

⏰ {self._format_time()}
"""
        return await self.send_message(message, chat_id, user_name=account_name, account_id=None, account_type=account_type)

    async def send_signal_notification(
        self,
        asset: str,
        direction: str,
        confidence: float,
        timeframe: int,
        account_name: str = None,
        chat_id: str = None,
        *,
        trade_amount: float | None = None,
        martingale_level: int | None = None,
        soros_level: int | None = None,
        strategy_name: str | None = None,
        account_type: str | None = None,
        user_name: str | None = None,
    ):
        """Enviar notificação de trade executado"""
        try:
            if not self.enabled or not self.bot_token:
                return False
            if not chat_id:
                return False

            direction_emoji = "🟢" if direction.upper() == "BUY" else "🔴"
            
            # Cabeçalho compacto
            lines = [
                f"🚀 <b>TRADE EXECUTADO</b>",
                f"",
                f"{direction_emoji} {asset} | {direction.upper()} | {timeframe}s",
            ]
            
            # Detalhes em linha única
            details = []
            if trade_amount is not None:
                details.append(f"💰 ${trade_amount:.2f}")
            if strategy_name:
                details.append(f"📋 {strategy_name}")
            if martingale_level and martingale_level > 0:
                details.append(f"🔄 M{martingale_level}")
            elif soros_level and soros_level > 0:
                details.append(f"📈 S{soros_level}")
            
            if details:
                lines.append(f"{' | '.join(details)}")
            
            # Conta e hora
            lines.extend([
                f"👤 {account_name or 'N/A'}{self._format_account_type(account_type)}",
                f"⏰ {self._format_time()}",
            ])
            
            message = "\n".join(lines)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data, timeout=10.0)
                response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")
            return False

    async def send_trade_result_notification(
        self,
        asset: str,
        direction: str,
        result: str,
        profit: float,
        account_name: str = None,
        chat_id: str = None,
        account_type: str | None = None,
        user_name: str | None = None,
        balance_before: float | None = None,
        balance_after: float | None = None
    ):
        """Enviar notificação de resultado do trade"""
        try:
            if not self.enabled or not self.bot_token:
                return False
            if not chat_id:
                return False

            # Determinar emoji e cor baseado no resultado
            result_upper = result.upper()
            if result_upper == "WIN":
                result_emoji = "✅"
                status = "WIN"
            elif result_upper == "LOSS":
                result_emoji = "❌"
                status = "LOSS"
            elif result_upper == "DRAW":
                result_emoji = "🤝"
                status = "EMPATE"
            else:
                result_emoji = "⚪"
                status = result_upper
            
            # Linha de saldo
            balance_line = ""
            if balance_before is not None and balance_after is not None:
                balance_line = f"💰 ${balance_before:.2f} → ${balance_after:.2f}"
            elif balance_after is not None:
                balance_line = f"💰 Saldo: ${balance_after:.2f}"
            
            # Formato compacto
            lines = [
                f"{result_emoji} <b>RESULTADO: {status}</b>",
                f"",
                f"📊 {asset} | {direction.upper()} | {status}",
            ]
            
            # Lucro/perda
            if profit > 0:
                lines.append(f"🟢 +${profit:.2f}")
            elif profit < 0:
                lines.append(f"🔴 ${profit:.2f}")
            
            # Saldo se disponível
            if balance_line:
                lines.append(balance_line)
            
            # Conta e hora
            lines.extend([
                f"👤 {account_name or 'N/A'}{self._format_account_type(account_type)}",
                f"⏰ {self._format_time()}",
            ])
            
            message = "\n".join(lines)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data, timeout=10.0)
                response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de resultado: {e}")
            return False

    def send_signal_notification_sync(self, asset: str, direction: str, confidence: float, timeframe: int, account_name: str = None, chat_id: str = None, trade_amount: float = None, martingale_level: int = None, soros_level: int = None, strategy_name: str = None, account_type: str | None = None, user_name: str | None = None):
        """Enviar notificação de trade executado (versão síncrona)"""
        # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se notificações estão habilitadas
        system_manager = get_system_manager()
        if not system_manager.is_notifications_enabled():
            return False
        
        try:
            if not self.enabled or not self.bot_token:
                return False
            if not chat_id:
                return False

            direction_emoji = "🟢" if direction.upper() == "BUY" else "🔴"
            
            # Formato compacto igual à versão async
            lines = [
                f"🚀 <b>TRADE EXECUTADO</b>",
                f"",
                f"{direction_emoji} {asset} | {direction.upper()} | {timeframe}s",
            ]
            
            # Detalhes em linha única
            details = []
            if trade_amount is not None:
                details.append(f"💰 ${trade_amount:.2f}")
            if strategy_name:
                details.append(f"📋 {strategy_name}")
            if martingale_level and martingale_level > 0:
                details.append(f"🔄 M{martingale_level}")
            elif soros_level and soros_level > 0:
                details.append(f"� S{soros_level}")
            
            if details:
                lines.append(f"{' | '.join(details)}")
            
            lines.extend([
                f"👤 {account_name or 'N/A'}{self._format_account_type(account_type)}",
                f"⏰ {self._format_time()}",
            ])
            
            message = "\n".join(lines)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = httpx.post(url, json=data, timeout=10.0)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar notificação sync: {e}")
            return False

    def send_trade_result_notification_sync(self, asset: str, direction: str, result: str, profit: float, account_name: str = None, chat_id: str = None, account_type: str | None = None, user_name: str | None = None, balance_before: float | None = None, balance_after: float | None = None):
        """Enviar notificação de resultado do trade (versão síncrona)"""
        try:
            if not self.enabled or not self.bot_token:
                return False
            if not chat_id:
                return False

            # Determinar emoji e status
            result_upper = result.upper()
            if result_upper == "WIN":
                result_emoji = "✅"
                status = "WIN"
            elif result_upper == "LOSS":
                result_emoji = "❌"
                status = "LOSS"
            elif result_upper == "DRAW":
                result_emoji = "🤝"
                status = "EMPATE"
            else:
                result_emoji = "⚪"
                status = result_upper
            
            # Linha de saldo
            balance_line = ""
            if balance_before is not None and balance_after is not None:
                balance_line = f"💰 ${balance_before:.2f} → ${balance_after:.2f}"
            elif balance_after is not None:
                balance_line = f"💰 Saldo: ${balance_after:.2f}"
            
            # Formato compacto igual à versão async
            lines = [
                f"{result_emoji} <b>RESULTADO: {status}</b>",
                f"",
                f"📊 {asset} | {direction.upper()} | {status}",
            ]
            
            # Lucro/perda
            if profit > 0:
                lines.append(f"🟢 +${profit:.2f}")
            elif profit < 0:
                lines.append(f"🔴 ${profit:.2f}")
            
            # Saldo se disponível
            if balance_line:
                lines.append(balance_line)
            
            lines.extend([
                f"👤 {account_name or 'N/A'}{self._format_account_type(account_type)}",
                f"⏰ {self._format_time()}",
            ])
            
            message = "\n".join(lines)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = httpx.post(url, json=data, timeout=10.0)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de resultado sync: {e}")
            return False

    def send_stop_loss_notification_sync(self, account_name: str, loss_consecutive: int, stop2: int, chat_id: str = None, account_type: str | None = None, no_hibernate: bool = False):
        """Enviar notificação de stop loss (versão síncrona usando httpx síncrono)"""
        try:
            if not self.enabled or not self.bot_token:
                logger.warning("Telegram não configurado", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            if not chat_id:
                logger.warning("Chat ID não fornecido, notificação não enviada", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            # Validar que chat_id é um número válido
            try:
                int(chat_id)
            except (ValueError, TypeError):
                logger.warning(f"Chat ID inválido: {chat_id}, notificação não enviada", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            if no_hibernate:
                status_msg = "🔄 Estratégia permanece ATIVA (Não Hibernar ligado)"
                action_msg = "⏳ Cooldown aplicado - aguardando próximo ciclo"
            else:
                status_msg = "⚠️ Autotrade foi desativado automaticamente"
                action_msg = "🛑 Estratégia desligada"

            message = f"""
🛑 <b>STOP LOSS ATINGIDO!</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
📊 Perdas consecutivas: {loss_consecutive}/{stop2}

{status_msg}
{action_msg}

⏰ {self._format_time()}
"""

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = httpx.post(url, json=data, timeout=10.0)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erro HTTP ao enviar notificação de stop loss (sync): {e.response.status_code}", extra={
                "user_name": account_name or "",
                "account_id": "",
                "account_type": account_type or ""
            })
            return False
        except httpx.TimeoutException:
            logger.error("❌ Timeout ao enviar notificação de stop loss (sync)", extra={
                "user_name": account_name or "",
                "account_id": "",
                "account_type": account_type or ""
            })
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de stop loss (sync): {e}", extra={
                "user_name": account_name or "",
                "account_id": "",
                "account_type": account_type or ""
            })
            return False

    def send_stop_gain_notification_sync(self, account_name: str, win_consecutive: int, stop1: int, chat_id: str = None, account_type: str | None = None, no_hibernate: bool = False):
        """Enviar notificação de stop gain (versão síncrona usando httpx síncrono)"""
        try:
            if not self.enabled or not self.bot_token:
                logger.warning("Telegram não configurado", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            if not chat_id:
                logger.warning("Chat ID não fornecido, notificação não enviada", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            # Validar que chat_id é um número válido
            try:
                int(chat_id)
            except (ValueError, TypeError):
                logger.warning(f"Chat ID inválido: {chat_id}, notificação não enviada", extra={
                    "user_name": account_name or "",
                    "account_id": "",
                    "account_type": account_type or ""
                })
                return False

            if no_hibernate:
                status_msg = "🔄 Estratégia permanece ATIVA (Não Hibernar ligado)"
                action_msg = "⏳ Cooldown aplicado - aguardando próximo ciclo"
            else:
                status_msg = "✅ Autotrade foi desativado automaticamente"
                action_msg = "🎯 Stop gain realizado com sucesso"

            message = f"""
🎯 <b>STOP GAIN ATINGIDO!</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
📊 Vitórias consecutivas: {win_consecutive}/{stop1}

{status_msg}
{action_msg}

⏰ {self._format_time()}
"""

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = httpx.post(url, json=data, timeout=10.0)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erro HTTP ao enviar notificação de stop gain (sync): {e.response.status_code}")
            return False
        except httpx.TimeoutException:
            logger.error("❌ Timeout ao enviar notificação de stop gain (sync)")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de stop gain (sync): {e}")
            return False

    def send_stop_amount_notification_sync(
        self,
        account_name: str,
        current_balance: float,
        stop_amount: float,
        stop_type: str,
        chat_id: str = None,
        account_type: str | None = None
    ):
        """Enviar notificação de stop amount (versão síncrona usando httpx síncrono)"""
        try:
            if not self.enabled or not self.bot_token:
                return False

            if not chat_id:
                logger.warning("Chat ID não fornecido, notificação não enviada")
                return False

            # Validar que chat_id é um número válido
            try:
                int(chat_id)
            except (ValueError, TypeError):
                logger.warning(f"Chat ID inválido: {chat_id}, notificação não enviada")
                return False

            stop_type_normalized = (stop_type or "").lower()
            if stop_type_normalized == "loss":
                title = "STOP AMOUNT LOSS ATINGIDO!"
                emoji = "🛑"
                label = "Stop Amount Loss"
            else:
                title = "STOP AMOUNT WIN ATINGIDO!"
                emoji = "🎯"
                label = "Stop Amount Win"

            message = f"""
{emoji} <b>{title}</b>

👤 Conta: {account_name}{self._format_account_type(account_type)}
💰 Saldo atual: ${current_balance:.2f}
🎯 {label}: ${stop_amount:.2f}

⚠️ Autotrade foi desativado automaticamente.

⏰ {self._format_time()}
"""

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = httpx.post(url, json=data, timeout=10.0)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erro HTTP ao enviar notificação de stop amount (sync): {e.response.status_code}")
            return False
        except httpx.TimeoutException:
            logger.error("❌ Timeout ao enviar notificação de stop amount (sync)")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de stop amount (sync): {e}")
            return False


# Instância global do serviço
telegram_service = TelegramNotificationService()
