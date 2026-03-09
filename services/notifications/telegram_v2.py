"""Servico de notificacao via Telegram - Versao Otimizada e Robusta"""
import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import httpx
from loguru import logger
from core.config import settings
from services.notifications.queue_manager import notification_queue_manager, NotificationMessage


class TelegramErrorCode(Enum):
    """Codigos de erro da API do Telegram"""
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    RATE_LIMIT = 429
    BAD_REQUEST = 400
    INTERNAL_ERROR = 500


@dataclass
class TelegramMessage:
    """Representa uma mensagem para envio"""
    text: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_notification: bool = False
    reply_markup: Optional[Dict] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.utcnow)
    priority: int = 1  # 1=alta, 2=media, 3=baixa


@dataclass
class TelegramMetrics:
    """Metricas do servico de notificacao"""
    total_sent: int = 0
    total_failed: int = 0
    total_retries: int = 0
    rate_limit_hits: int = 0
    last_error: Optional[str] = None
    last_success: Optional[datetime] = None
    avg_response_time: float = 0.0
    errors_by_code: Dict[int, int] = field(default_factory=dict)


class TelegramNotificationServiceV2:
    """Servico otimizado para enviar notificacoes via Telegram Bot"""

    # Templates de mensagens sem emojis (usando texto/icones alternativos)
    TEMPLATES = {
        "signal": """[SINAL DETECTADO]

Ativo: {asset}
Direcao: {direction}
Confianca: {confidence:.1%}
Timeframe: {timeframe}s
Conta: {account_name}{account_type}""",
        "trade_result": """[RESULTADO DO TRADE]

Ativo: {asset}
Direcao: {direction}
Resultado: {result}
Lucro: ${profit:.2f}
Conta: {account_name}{account_type}""",
        "stop_loss": """[STOP LOSS ATINGIDO]

Conta: {account_name}{account_type}
Perdas consecutivas: {loss_consecutive}/{stop_loss_level}

Autotrade foi desativado automaticamente.""",
        "stop_gain": """[STOP GAIN ATINGIDO]

Conta: {account_name}{account_type}
Vitorias consecutivas: {win_consecutive}/{stop_gain_level}

Autotrade foi desativado automaticamente.""",
        "stop_amount": """[STOP AMOUNT {stop_type_upper} ATINGIDO]

Conta: {account_name}{account_type}
Saldo atual: ${current_balance:.2f}
Stop Amount {stop_type}: ${stop_amount:.2f}

Autotrade foi desativado automaticamente.""",
        "insufficient_balance": """[SALDO INSUFICIENTE]

Conta: {account_name}{account_type}
Saldo atual: ${current_balance:.2f}
Saldo minimo: ${min_balance:.2f}

Autotrade foi desativado automaticamente.""",
        "error": """[ERRO NO SISTEMA]

Conta: {account_name}{account_type}
Erro: {error_message}

Horario: {timestamp}"""
    }

    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.enabled = settings.TELEGRAM_ENABLED and bool(self.bot_token)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None
        self._pending_chat_ids: Dict[str, str] = {}
        self._pending_chat_ids_lock = asyncio.Lock()
        self._message_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._metrics = TelegramMetrics()
        self._metrics_lock = asyncio.Lock()
        self._session: Optional[httpx.AsyncClient] = None
        self._processing_tasks: List[asyncio.Task] = []  # Worker Pool: múltiplos workers
        self._rate_limit_delay = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._offline_mode = False
        self._offline_chats: set = set()

        # Configuracoes de retry
        self.retry_base_delay = 1.0
        self.retry_max_delay = 30.0
        self.retry_exponential_base = 2.0
        
        # 🔄 Worker Pool: número de workers (configurável)
        self._num_workers = getattr(settings, 'TELEGRAM_WORKERS', 5)
        self._worker_semaphore = asyncio.Semaphore(self._num_workers)
        
        # 📦 Batch Processing: agrupar notificações não-urgentes
        self._batch_enabled = getattr(settings, 'TELEGRAM_BATCH_ENABLED', True)
        self._batch_interval = getattr(settings, 'TELEGRAM_BATCH_INTERVAL', 5)  # segundos
        self._batch_size = getattr(settings, 'TELEGRAM_BATCH_SIZE', 10)
        self._batch_buffer: List[NotificationMessage] = []
        self._batch_lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None

        if self.enabled:
            logger.info(f"[TelegramV2] Servico inicializado | Token: {self.bot_token[:10]}... | Enabled: {self.enabled} | Workers: {self._num_workers}")
        else:
            logger.warning("[TelegramV2] Servico DESABILITADO - token nao configurado")
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"Content-Type": "application/json"}
            )

    async def _get_session(self) -> httpx.AsyncClient:
        """Obtem ou cria sessao HTTP compartilhada"""
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"Content-Type": "application/json"}
            )
        return self._session

    def _start_queue_processor(self):
        """Inicia o pool de workers para processar fila de mensagens"""
        # Parar workers existentes se houver
        self._stop_workers()
        
        # Iniciar múltiplos workers
        for i in range(self._num_workers):
            task = asyncio.create_task(self._worker_loop(f"worker-{i+1}"))
            self._processing_tasks.append(task)
        
        logger.info(f"[TelegramV2] Pool de {self._num_workers} workers iniciado")

    def _stop_workers(self):
        """Para todos os workers"""
        for task in self._processing_tasks:
            if not task.done():
                task.cancel()
        self._processing_tasks.clear()

    async def _worker_loop(self, worker_id: str):
        """Loop de worker individual para processar mensagens"""
        while True:
            try:
                # 🔄 Usar semáforo para controlar concorrência
                async with self._worker_semaphore:
                    # Obter mensagem da fila
                    priority, message = await self._message_queue.get()
                    
                    if message.retry_count >= message.max_retries:
                        logger.error(f"[TelegramV2] [{worker_id}] Max retries atingido para chat {message.chat_id[:8]}...")
                        async with self._metrics_lock:
                            self._metrics.total_failed += 1
                        continue

                    # Verificar rate limit
                    async with self._rate_limit_lock:
                        if self._rate_limit_delay > 0:
                            await asyncio.sleep(self._rate_limit_delay)
                            self._rate_limit_delay = 0

                    # Tentar enviar
                    success = await self._send_message_internal(message)

                    if not success:
                        # Reenfileirar com prioridade mais baixa
                        message.retry_count += 1
                        message.priority += 1
                        await self._message_queue.put((message.priority, message))
                        async with self._metrics_lock:
                            self._metrics.total_retries += 1

            except asyncio.CancelledError:
                logger.info(f"[TelegramV2] [{worker_id}] Worker cancelado")
                break
            except Exception as e:
                logger.error(f"[TelegramV2] [{worker_id}] Erro no worker: {e}")
                await asyncio.sleep(1)

    async def _batch_processor(self):
        """Processa notificações em batch (agrupa mensagens de baixa prioridade)"""
        await asyncio.sleep(self._batch_interval)
        
        async with self._batch_lock:
            if not self._batch_buffer:
                return
            
            # Obter todas as mensagens do buffer
            messages = self._batch_buffer[:self._batch_size]
            self._batch_buffer = self._batch_buffer[self._batch_size:]
        
        # Enfileirar mensagens do batch
        for msg in messages:
            await notification_queue_manager.enqueue(msg)
            await self._message_queue.put((msg.priority, msg))
        
        logger.debug(f"[TelegramV2] Batch de {len(messages)} notificações processado")
        
        # Se ainda houver mensagens no buffer, agendar próximo batch
        if self._batch_buffer:
            self._batch_task = asyncio.create_task(self._batch_processor())

    async def start(self):
        """Inicia o processador de fila (deve ser chamado dentro de um event loop)"""
        if self.enabled and len(self._processing_tasks) == 0:
            # Inicializar queue manager (restaura do Redis se necessário)
            await notification_queue_manager.initialize()
            
            # Iniciar workers
            self._start_queue_processor()
            logger.info("[TelegramV2] Pool de workers iniciado via start()")
            self._start_queue_processor()
            logger.info("[TelegramV2] Pool de workers iniciado via start()")

    async def _process_message_queue(self):
        """DEPRECATED: Mantido para compatibilidade - usar _worker_loop"""
        pass

    async def _process_message_queue(self):
        """Processa mensagens na fila com retry e controle de rate limit"""
        while True:
            try:
                # Verificar rate limit
                async with self._rate_limit_lock:
                    if self._rate_limit_delay > 0:
                        await asyncio.sleep(self._rate_limit_delay)
                        self._rate_limit_delay = 0

                # Obter mensagem da fila
                priority, message = await self._message_queue.get()

                if message.retry_count >= message.max_retries:
                    logger.error(f"[TelegramV2] Max retries atingido para chat {message.chat_id[:8]}... | Msg: {message.text[:50]}...")
                    async with self._metrics_lock:
                        self._metrics.total_failed += 1
                    continue

                # Tentar enviar
                success = await self._send_message_internal(message)

                if not success:
                    # Reenfileirar com prioridade mais baixa
                    message.retry_count += 1
                    message.priority += 1
                    await self._message_queue.put((message.priority, message))
                    async with self._metrics_lock:
                        self._metrics.total_retries += 1

                await asyncio.sleep(0.1)  # Pequeno delay entre mensagens

            except asyncio.CancelledError:
                logger.info("[TelegramV2] Processador de fila cancelado")
                break
            except Exception as e:
                logger.error(f"[TelegramV2] Erro no processador de fila: {e}")
                await asyncio.sleep(1)

    async def _send_message_internal(self, message: TelegramMessage) -> bool:
        """Envia mensagem internamente com tratamento de erros completo"""
        if not self.enabled or not self.base_url:
            return False

        # Verificar se chat esta offline
        if message.chat_id in self._offline_chats:
            logger.debug(f"[TelegramV2] Chat {message.chat_id[:8]}... marcado como offline, pulando")
            return False

        start_time = time.time()

        try:
            session = await self._get_session()
            url = f"{self.base_url}/sendMessage"

            data = {
                "chat_id": message.chat_id,
                "text": message.text,
                "parse_mode": message.parse_mode,
                "disable_notification": message.disable_notification
            }

            if message.reply_markup:
                data["reply_markup"] = json.dumps(message.reply_markup)

            response = await session.post(url, json=data)
            elapsed = time.time() - start_time

            # Atualizar metricas de tempo de resposta
            async with self._metrics_lock:
                if self._metrics.avg_response_time == 0:
                    self._metrics.avg_response_time = elapsed
                else:
                    self._metrics.avg_response_time = (self._metrics.avg_response_time * 0.9) + (elapsed * 0.1)

            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    async with self._metrics_lock:
                        self._metrics.total_sent += 1
                        self._metrics.last_success = datetime.utcnow()
                    logger.success(f"[TelegramV2] Enviado para {message.chat_id[:8]}... | Tempo: {elapsed:.2f}s | Tentativa: {message.retry_count + 1}")
                    return True
                else:
                    error_code = self._extract_error_code(result)
                    await self._handle_telegram_error(error_code, result, message.chat_id)
                    return False

            else:
                await self._handle_http_error(response, message.chat_id)
                return False

        except httpx.TimeoutException:
            logger.error(f"[TelegramV2] Timeout enviando para {message.chat_id[:8]}...")
            return False
        except httpx.HTTPStatusError as e:
            await self._handle_http_error(e.response, message.chat_id)
            return False
        except Exception as e:
            logger.error(f"[TelegramV2] Erro inesperado: {e}")
            return False

    def _extract_error_code(self, result: Dict) -> int:
        """Extrai codigo de erro da resposta da API"""
        error_code = result.get("error_code", 0)
        if error_code == 0:
            # Tentar extrair de descricao
            desc = result.get("description", "").lower()
            if "not found" in desc:
                return 404
            elif "forbidden" in desc or "blocked" in desc:
                return 403
            elif "unauthorized" in desc:
                return 401
        return error_code

    async def _handle_telegram_error(self, error_code: int, result: Dict, chat_id: str):
        """Trata erros especificos da API do Telegram"""
        description = result.get("description", "Erro desconhecido")

        async with self._metrics_lock:
            self._metrics.total_failed += 1
            self._metrics.last_error = description
            self._metrics.errors_by_code[error_code] = self._metrics.errors_by_code.get(error_code, 0) + 1

        if error_code == TelegramErrorCode.NOT_FOUND.value:
            # Chat nao existe ou bot removido - marcar como offline
            logger.warning(f"[TelegramV2] Chat {chat_id[:8]}... nao encontrado (404). Marcando como offline.")
            self._offline_chats.add(chat_id)

        elif error_code == TelegramErrorCode.FORBIDDEN.value:
            # Bot bloqueado pelo usuario
            logger.warning(f"[TelegramV2] Bot bloqueado pelo usuario {chat_id[:8]}... (403). Marcando como offline.")
            self._offline_chats.add(chat_id)

        elif error_code == TelegramErrorCode.UNAUTHORIZED.value:
            # Token invalido - desabilitar servico
            logger.error("[TelegramV2] Token de bot invalido (401). Desabilitando servico.")
            self.enabled = False

        elif error_code == TelegramErrorCode.RATE_LIMIT.value:
            # Rate limit - extrair tempo de espera
            retry_after = result.get("parameters", {}).get("retry_after", 1)
            async with self._rate_limit_lock:
                self._rate_limit_delay = max(self._rate_limit_delay, retry_after)
            async with self._metrics_lock:
                self._metrics.rate_limit_hits += 1
            logger.warning(f"[TelegramV2] Rate limit atingido. Aguardando {retry_after}s")

        elif error_code == TelegramErrorCode.BAD_REQUEST.value:
            # Erro na mensagem (HTML malformado, etc)
            logger.error(f"[TelegramV2] Bad request (400): {description}")

        else:
            logger.error(f"[TelegramV2] Erro {error_code}: {description}")

    async def _handle_http_error(self, response: httpx.Response, chat_id: str):
        """Trata erros HTTP"""
        status = response.status_code
        text = response.text[:200]

        async with self._metrics_lock:
            self._metrics.total_failed += 1
            self._metrics.last_error = f"HTTP {status}: {text}"
            self._metrics.errors_by_code[status] = self._metrics.errors_by_code.get(status, 0) + 1

        if status == 502 or status == 503 or status == 504:
            logger.warning(f"[TelegramV2] Erro de gateway {status}, possivelmente temporario")
        else:
            logger.error(f"[TelegramV2] Erro HTTP {status}: {text}")

    # ============ METODOS PUBLICOS ============

    async def health_check(self) -> Dict[str, Any]:
        """Verifica saude do servico e retorna metricas"""
        async with self._metrics_lock:
            metrics = {
                "enabled": self.enabled,
                "token_configured": bool(self.bot_token),
                "queue_size": self._message_queue.qsize(),
                "offline_chats_count": len(self._offline_chats),
                "total_sent": self._metrics.total_sent,
                "total_failed": self._metrics.total_failed,
                "total_retries": self._metrics.total_retries,
                "rate_limit_hits": self._metrics.rate_limit_hits,
                "success_rate": self._calculate_success_rate(),
                "avg_response_time": round(self._metrics.avg_response_time, 3),
                "last_error": self._metrics.last_error,
                "last_success": self._metrics.last_success.isoformat() if self._metrics.last_success else None,
                "errors_by_code": dict(self._metrics.errors_by_code)
            }

        # Testar conexao se habilitado
        if self.enabled:
            try:
                session = await self._get_session()
                url = f"{self.base_url}/getMe"
                response = await session.get(url, timeout=5.0)
                if response.status_code == 200:
                    result = response.json()
                    metrics["api_connected"] = result.get("ok", False)
                    if result.get("ok"):
                        bot_info = result.get("result", {})
                        metrics["bot_name"] = bot_info.get("first_name", "Unknown")
                        metrics["bot_username"] = bot_info.get("username", "Unknown")
                else:
                    metrics["api_connected"] = False
            except Exception as e:
                metrics["api_connected"] = False
                metrics["connection_error"] = str(e)

        return metrics

    def _calculate_success_rate(self) -> float:
        """Calcula taxa de sucesso"""
        total = self._metrics.total_sent + self._metrics.total_failed
        if total == 0:
            return 0.0
        return round(self._metrics.total_sent / total, 4)

    async def validate_token(self) -> bool:
        """Valida se o token do bot esta funcionando"""
        if not self.enabled or not self.bot_token:
            return False

        try:
            session = await self._get_session()
            url = f"{self.base_url}/getMe"
            response = await session.get(url, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    bot_info = result.get("result", {})
                    logger.success(f"[TelegramV2] Token validado | Bot: {bot_info.get('first_name')} (@{bot_info.get('username')})")
                    return True
            logger.error(f"[TelegramV2] Token invalido ou problema na API: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"[TelegramV2] Erro validando token: {e}")
            return False

    async def get_chat_id_from_username(self, username: str) -> Optional[str]:
        """Busca Chat ID a partir do username usando getUpdates"""
        if not self.enabled:
            logger.debug("[TelegramV2] Servico desabilitado, ignorando get_chat_id")
            return None

        username = username.lstrip('@')

        # Verificar cache
        async with self._pending_chat_ids_lock:
            cached = self._pending_chat_ids.get(username) or self._pending_chat_ids.get(f"@{username}")
            if cached:
                logger.debug(f"[TelegramV2] Chat ID cache hit para @{username}")
                return cached

        # Tentar capturar de mensagens recentes
        captured = await self.capture_chat_id_from_message()
        if username in captured or f"@{username}" in captured:
            chat_id = captured.get(username) or captured.get(f"@{username}")
            logger.info(f"[TelegramV2] Chat ID capturado para @{username}: {chat_id[:8]}...")
            return chat_id

        # Tentar buscar via getChat (pode nao funcionar para usuarios privados)
        try:
            session = await self._get_session()
            url = f"{self.base_url}/getChat"
            params = {"chat_id": f"@{username}"}

            response = await session.get(url, params=params, timeout=10.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    chat_id = str(result["result"].get("id"))
                    async with self._pending_chat_ids_lock:
                        self._pending_chat_ids[username] = chat_id
                        self._pending_chat_ids[f"@{username}"] = chat_id
                    logger.info(f"[TelegramV2] Chat ID encontrado via API para @{username}: {chat_id[:8]}...")
                    return chat_id

            # Se falhou, provavelmente usuario precisa enviar mensagem primeiro
            logger.warning(f"[TelegramV2] Usuario @{username} nao encontrado. Pedir para enviar mensagem ao bot primeiro.")
            return None

        except Exception as e:
            logger.warning(f"[TelegramV2] Erro buscando Chat ID para @{username}: {e}")
            return None

    async def capture_chat_id_from_message(self) -> Dict[str, str]:
        """Captura Chat IDs de usuarios que enviaram mensagens para o bot"""
        if not self.enabled:
            return {}

        try:
            session = await self._get_session()
            url = f"{self.base_url}/getUpdates"
            params = {"limit": 100}

            response = await session.get(url, params=params, timeout=10.0)
            if response.status_code != 200:
                return {}

            result = response.json()
            if not result.get("ok"):
                return {}

            updates = result.get("result", [])
            captured = {}

            for update in updates:
                if "message" in update:
                    msg = update["message"]
                    from_user = msg.get("from", {})
                    chat_id = str(from_user.get("id"))
                    username = from_user.get("username")

                    if chat_id and username:
                        captured[username] = chat_id
                        captured[f"@{username}"] = chat_id
                        async with self._pending_chat_ids_lock:
                            self._pending_chat_ids[username] = chat_id
                            self._pending_chat_ids[f"@{username}"] = chat_id

            if captured:
                logger.info(f"[TelegramV2] {len(captured)//2} Chat IDs capturados de mensagens")

            return captured

        except Exception as e:
            logger.error(f"[TelegramV2] Erro capturando Chat IDs: {e}")
            return {}

    async def send_message(self, message: str, chat_id: str, priority: int = 1, notification_type: str = "general") -> bool:
        """Envia mensagem via fila com persistência Redis (nao-bloqueante)"""
        if not self.enabled:
            return False

        if not chat_id or chat_id in self._offline_chats:
            return False

        # Validar chat_id
        try:
            int(chat_id)
        except (ValueError, TypeError):
            logger.warning(f"[TelegramV2] Chat ID invalido: {chat_id}")
            return False

        # Criar mensagem para fila persistente
        msg = NotificationMessage(
            text=message, 
            chat_id=chat_id, 
            priority=priority,
            notification_type=notification_type
        )
        
        # 📦 Se batch estiver habilitado e for prioridade baixa, adicionar ao buffer
        if self._batch_enabled and priority >= 3:
            async with self._batch_lock:
                self._batch_buffer.append(msg)
                # Iniciar batch processor se não estiver rodando
                if self._batch_task is None or self._batch_task.done():
                    self._batch_task = asyncio.create_task(self._batch_processor())
            return True
        
        # 🚀 Enfileirar imediatamente (persiste em Redis automaticamente)
        success = await notification_queue_manager.enqueue(msg)
        if success:
            # Adicionar à fila local para processamento
            await self._message_queue.put((priority, msg))
        return success

    async def send_message_sync(self, message: str, chat_id: str) -> bool:
        """Envia mensagem de forma sincrona (bloqueante) - para compatibilidade"""
        if not self.enabled:
            return False

        if not chat_id or chat_id in self._offline_chats:
            return False

        try:
            int(chat_id)
        except (ValueError, TypeError):
            logger.warning(f"[TelegramV2] Chat ID invalido: {chat_id}")
            return False

        msg = TelegramMessage(text=message, chat_id=chat_id, max_retries=1)
        return await self._send_message_internal(msg)

    # ============ NOTIFICACOES ESPECIFICAS ============

    async def send_signal(self, asset: str, direction: str, confidence: float,
                          timeframe: int, account_name: str = None, chat_id: str = None,
                          trade_amount: float = None, strategy_name: str = None,
                          account_type: str = None) -> bool:
        """Envia notificacao de sinal"""
        if not chat_id:
            return False

        template = self.TEMPLATES["signal"]
        msg = template.format(
            asset=asset,
            direction=direction.upper(),
            confidence=confidence,
            timeframe=timeframe,
            account_name=account_name or "N/A",
            account_type=self._format_account_type(account_type)
        )

        if strategy_name:
            msg += f"\nEstrategia: {strategy_name}"
        if trade_amount:
            msg += f"\nValor: ${trade_amount:.2f}"

        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=1)

    async def send_trade_result(self, asset: str, direction: str, result: str,
                                profit: float, account_name: str = None,
                                chat_id: str = None, account_type: str = None) -> bool:
        """Envia notificacao de resultado de trade"""
        if not chat_id:
            return False

        template = self.TEMPLATES["trade_result"]
        msg = template.format(
            asset=asset,
            direction=direction.upper(),
            result=result.upper(),
            profit=profit,
            account_name=account_name or "N/A",
            account_type=self._format_account_type(account_type)
        )
        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=1)

    async def send_trade_result_notification(self, asset: str, direction: str, result: str,
                                profit: float, account_name: str = None,
                                chat_id: str = None, account_type: str = None,
                                user_name: str = None) -> bool:
        """Envia notificacao de resultado de trade (alias para compatibilidade)"""
        return await self.send_trade_result(asset, direction, result, profit,
                                           account_name, chat_id, account_type)

    async def send_stop_loss(self, account_name: str, loss_consecutive: int,
                             stop_loss_level: int, chat_id: str = None,
                             account_type: str = None) -> bool:
        """Envia notificacao de stop loss"""
        if not chat_id:
            return False

        template = self.TEMPLATES["stop_loss"]
        msg = template.format(
            account_name=account_name,
            account_type=self._format_account_type(account_type),
            loss_consecutive=loss_consecutive,
            stop_loss_level=stop_loss_level
        )
        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=1)

    async def send_stop_gain(self, account_name: str, win_consecutive: int,
                             stop_gain_level: int, chat_id: str = None,
                             account_type: str = None) -> bool:
        """Envia notificacao de stop gain"""
        if not chat_id:
            return False

        template = self.TEMPLATES["stop_gain"]
        msg = template.format(
            account_name=account_name,
            account_type=self._format_account_type(account_type),
            win_consecutive=win_consecutive,
            stop_gain_level=stop_gain_level
        )
        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=1)

    async def send_stop_amount(self, account_name: str, current_balance: float,
                               stop_amount: float, stop_type: str, chat_id: str = None,
                               account_type: str = None) -> bool:
        """Envia notificacao de stop amount"""
        if not chat_id:
            return False

        stop_type_normalized = stop_type.lower() if stop_type else ""
        stop_type_upper = stop_type_normalized.upper()

        template = self.TEMPLATES["stop_amount"]
        msg = template.format(
            stop_type_upper=stop_type_upper,
            account_name=account_name,
            account_type=self._format_account_type(account_type),
            current_balance=current_balance,
            stop_amount=stop_amount,
            stop_type=stop_type_normalized
        )
        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=1)

    async def send_insufficient_balance(self, account_name: str, current_balance: float,
                                        min_balance: float, chat_id: str = None,
                                        required_amount: float = None,
                                        account_type: str = None) -> bool:
        """Envia notificacao de saldo insuficiente"""
        if not chat_id:
            return False

        template = self.TEMPLATES["insufficient_balance"]
        msg = template.format(
            account_name=account_name,
            account_type=self._format_account_type(account_type),
            current_balance=current_balance,
            min_balance=min_balance
        )
        if required_amount:
            msg += f"\nValor da operacao: ${required_amount:.2f}"
        msg += f"\n\nHorario: {self._format_time()}"
        return await self.send_message(msg, chat_id, priority=2, notification_type="insufficient_balance")

    async def send_error(self, account_name: str, error_message: str,
                         chat_id: str = None, account_type: str = None) -> bool:
        """Envia notificacao de erro do sistema"""
        if not chat_id:
            return False

        template = self.TEMPLATES["error"]
        msg = template.format(
            account_name=account_name,
            account_type=self._format_account_type(account_type),
            error_message=error_message,
            timestamp=self._format_time()
        )
        return await self.send_message(msg, chat_id, priority=3, notification_type="error")

    # ============ METODOS SYNC (para compatibilidade) ============

    def send_signal_sync(self, asset: str, direction: str, confidence: float,
                         timeframe: int, account_name: str = None, chat_id: str = None,
                         trade_amount: float = None, strategy_name: str = None,
                         account_type: str = None) -> bool:
        """Versao sincrona - executa async em thread separada"""
        if not self.enabled or not chat_id:
            return False

        try:
            # Criar novo event loop para esta thread se necessario
            try:
                loop = asyncio.get_running_loop()
                # Ja estamos em um loop async, criar task
                future = asyncio.run_coroutine_threadsafe(
                    self.send_signal(asset, direction, confidence, timeframe,
                                     account_name, chat_id, trade_amount, strategy_name, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                # Nao ha loop rodando, usar run
                return asyncio.run(self.send_signal(asset, direction, confidence, timeframe,
                                                   account_name, chat_id, trade_amount,
                                                   strategy_name, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_signal_sync: {e}")
            return False

    def send_trade_result_sync(self, asset: str, direction: str, result: str,
                               profit: float, account_name: str = None,
                               chat_id: str = None, account_type: str = None) -> bool:
        """Versao sincrona de trade result"""
        if not self.enabled or not chat_id:
            return False

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.send_trade_result(asset, direction, result, profit, account_name, chat_id, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                return asyncio.run(self.send_trade_result(asset, direction, result, profit,
                                                         account_name, chat_id, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_trade_result_sync: {e}")
            return False

    def send_stop_loss_sync(self, account_name: str, loss_consecutive: int,
                            stop_loss_level: int, chat_id: str = None,
                            account_type: str = None) -> bool:
        """Versao sincrona de stop loss"""
        if not self.enabled or not chat_id:
            return False

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.send_stop_loss(account_name, loss_consecutive, stop_loss_level, chat_id, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                return asyncio.run(self.send_stop_loss(account_name, loss_consecutive,
                                                       stop_loss_level, chat_id, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_stop_loss_sync: {e}")
            return False

    def send_stop_gain_sync(self, account_name: str, win_consecutive: int,
                            stop_gain_level: int, chat_id: str = None,
                            account_type: str = None) -> bool:
        """Versao sincrona de stop gain"""
        if not self.enabled or not chat_id:
            return False

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.send_stop_gain(account_name, win_consecutive, stop_gain_level, chat_id, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                return asyncio.run(self.send_stop_gain(account_name, win_consecutive,
                                                       stop_gain_level, chat_id, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_stop_gain_sync: {e}")
            return False

    def send_stop_amount_sync(self, account_name: str, current_balance: float,
                              stop_amount: float, stop_type: str, chat_id: str = None,
                              account_type: str = None) -> bool:
        """Versao sincrona de stop amount"""
        if not self.enabled or not chat_id:
            return False

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.send_stop_amount(account_name, current_balance, stop_amount,
                                        stop_type, chat_id, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                return asyncio.run(self.send_stop_amount(account_name, current_balance,
                                                        stop_amount, stop_type, chat_id, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_stop_amount_sync: {e}")
            return False

    def send_insufficient_balance_sync(self, account_name: str, current_balance: float,
                                       min_balance: float, chat_id: str = None,
                                       required_amount: float = None,
                                       account_type: str = None) -> bool:
        """Versao sincrona de saldo insuficiente"""
        if not self.enabled or not chat_id:
            return False

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.send_insufficient_balance(account_name, current_balance, min_balance,
                                                  chat_id, required_amount, account_type),
                    loop
                )
                return future.result(timeout=15)
            except RuntimeError:
                return asyncio.run(self.send_insufficient_balance(account_name, current_balance,
                                                               min_balance, chat_id, required_amount, account_type))
        except Exception as e:
            logger.error(f"[TelegramV2] Erro send_insufficient_balance_sync: {e}")
            return False

    # ============ UTILITARIOS ============

    def _format_account_type(self, account_type: Optional[str]) -> str:
        """Formata tipo de conta para exibicao"""
        if not account_type:
            return ""
        return f"\nTipo: {account_type.upper()}"

    def _format_time(self) -> str:
        """Formata horario com fuso UTC-3 (Brasil)"""
        return (datetime.utcnow() - timedelta(hours=3)).strftime('%H:%M:%S')

    async def reset_offline_chats(self):
        """Reseta lista de chats offline (para retry manual)"""
        count = len(self._offline_chats)
        self._offline_chats.clear()
        logger.info(f"[TelegramV2] {count} chats removidos da lista offline")

    async def close(self):
        """Fecha recursos do servico"""
        # Parar todos os workers do pool
        self._stop_workers()

        if self._session and not self._session.is_closed:
            await self._session.aclose()
            logger.info("[TelegramV2] Sessao HTTP fechada")


# Instancia global
telegram_service_v2 = TelegramNotificationServiceV2()

# Compatibilidade com codigo antigo
# Mapear metodos do servico antigo para o novo
class TelegramServiceAdapter:
    """Adaptador para compatibilidade com codigo antigo"""

    def __init__(self):
        self._v2 = telegram_service_v2

    def __getattr__(self, name):
        """Redireciona chamadas para o servico v2"""
        if hasattr(self._v2, name):
            return getattr(self._v2, name)
        raise AttributeError(f"Metodo {name} nao encontrado")


# Exportar adaptador como telegram_service para compatibilidade
telegram_service = TelegramServiceAdapter()
