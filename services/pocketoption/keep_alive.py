"""
Enhanced Keep-Alive Connection Manager for PocketOption Async API
"""

import asyncio
from typing import Optional, List, Callable, Dict, Any
from datetime import datetime, timedelta
from loguru import logger
from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import connect, WebSocketClientProtocol

from .models import ConnectionInfo, ConnectionStatus
from .constants import REGIONS
from services.ws_connection_logger import get_connection_logger, remove_connection_logger


class ConnectionKeepAlive:
    """Advanced connection keep-alive manager"""

    def __init__(self, ssid: str, is_demo: bool = True, user_name: str = None, account_id: str = None):
        self.ssid = ssid
        self.is_demo = is_demo
        self.user_name = user_name or "Unknown User"
        self.account_id = account_id  # ID da conta para verificar status do autotrade

        # Connection state
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.connection_info: Optional[ConnectionInfo] = None
        self.is_connected = False
        self.should_reconnect = True
        self._is_handshaking = False  # Flag para evitar conflito de recv() durante handshake

        # Background tasks
        self._ping_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._message_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._reconnection_id: Optional[str] = None
        self._ws_logger = None
        self._connection_logger_id: Optional[str] = None

        # Keep-alive settings
        self.ping_interval = 20  # seconds
        self.reconnect_delay = 5  # seconds (initial delay)
        self.max_reconnect_attempts = 10
        self.current_reconnect_attempts = 0
        self.max_reconnect_delay = 60  # maximum delay for exponential backoff

        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Connection pool with multiple regions
        self.available_urls = (
            REGIONS.get_demo_regions() if is_demo else REGIONS.get_all()
        )
        self.current_url_index = 0

        # Statistics
        self.connection_stats = {
            "total_connections": 0,
            "successful_connections": 0,
            "total_reconnects": 0,
            "last_ping_time": None,
            "last_pong_time": None,
            "total_messages_sent": 0,
            "total_messages_received": 0,
        }

        logger.debug(
            f"Initialized keep-alive manager with {len(self.available_urls)} available regions"
        )

    async def start_persistent_connection(self) -> bool:
        """Start a persistent connection with automatic keep-alive"""
        logger.debug("Starting persistent connection with keep-alive...")

        try:
            if await self._establish_connection():
                await self._start_background_tasks()
                return True
            else:
                logger.error("Failed to establish initial connection")
                return False

        except ConnectionError as e:
            logger.error(f"Connection error starting persistent connection: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error starting persistent connection: {e}", exc_info=True)
            return False

    async def stop_persistent_connection(self):
        """Stop the persistent connection and all background tasks"""
        logger.info("Stopping persistent connection...", extra={
            "user_name": self.user_name,
            "account_id": "",
            "account_type": "demo" if self.is_demo else "real"
        })

        self.should_reconnect = False

        # Unregister from unified reconnection manager to avoid reconnect conflicts
        if self._reconnection_id:
            try:
                from services.data_collector.reconnection_manager import (
                    get_reconnection_manager,
                )

                reconnection_manager = get_reconnection_manager()
                reconnection_manager.unregister_connection(self._reconnection_id)
            except Exception as e:
                logger.debug(
                    f"Erro ao remover conexão do gerenciador unificado: {e}"
                )
            finally:
                self._reconnection_id = None

        # Cancel all background tasks safely
        tasks = [
            self._ping_task,
            self._reconnect_task,
            self._message_task,
            self._health_task,
        ]

        # Cancel tasks without waiting to avoid RecursionError
        for task in tasks:
            if task and not task.done():
                try:
                    task.cancel()
                except Exception as e:
                    logger.debug(f"Erro ao cancelar tarefa: {e}")

        # Wait for tasks to complete with timeout, but don't gather cancelled tasks
        # to avoid RecursionError from nested cancellation
        if tasks:
            try:
                # Use shield to prevent cancellation of the wait operation itself
                async def wait_for_tasks():
                    for task in tasks:
                        if task and not task.done():
                            try:
                                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                            except (asyncio.CancelledError, asyncio.TimeoutError):
                                pass
                            except Exception:
                                pass

                await asyncio.wait_for(wait_for_tasks(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout ao aguardar finalização das tasks canceladas")
            except Exception as e:
                logger.debug(f"Erro ao aguardar finalização das tasks: {e}")

        # Close connection
        if self.websocket:
            try:
                await self.websocket.close()
                if hasattr(self.websocket, "wait_closed"):
                    await self.websocket.wait_closed()
            except Exception as e:
                logger.debug(f"Erro ao fechar websocket: {e}")
            self.websocket = None

        self.is_connected = False
        logger.info("Persistent connection stopped", extra={
            "user_name": self.user_name,
            "account_id": "",
            "account_type": "demo" if self.is_demo else "real"
        })
        
        # Fechar logger da conexão
        if self._ws_logger and self._connection_logger_id:
            try:
                await self._ws_logger.close()
                remove_connection_logger(self._connection_logger_id)
                self._ws_logger = None
                self._connection_logger_id = None
            except Exception as e:
                logger.debug(f"Erro ao fechar logger de conexão: {e}")

    async def _establish_connection(self) -> bool:
        """Establish connection with fallback URLs"""
        last_error = None
        
        # Criar logger para esta tentativa de conexão (usar identificador estável)
        # Usar user_name + is_demo como base para ID estável (não muda entre reconexões)
        import hashlib
        stable_id_base = f"{self.user_name}_{self.is_demo}"
        stable_id = hashlib.md5(stable_id_base.encode()).hexdigest()[:12]
        self._connection_logger_id = f"keep_alive_{stable_id}"
        
        # Se já existe um logger para esta conexão, reutilizar
        if self._ws_logger is None:
            self._ws_logger = get_connection_logger(
                self._connection_logger_id, 
                connection_type="keep_alive",
                rotation_lines=10000,  # Rotacionar após 10.000 linhas
                user_name=self.user_name
            )
        
        await self._ws_logger.log_event("INIT", f"Iniciando estabelecimento de conexão", {
            "ssid_preview": self.ssid[:30] if self.ssid else None,
            "is_demo": self.is_demo,
            "user_name": self.user_name,
            "urls_available": len(self.available_urls)
        })

        for attempt, url in enumerate(self.available_urls):
            try:
                logger.info(
                    f"[CONNECT] Connecting: Attempting connection to {url} (attempt {attempt + 1}/{len(self.available_urls)})",
                    extra={
                        "user_name": self.user_name,
                        "account_id": "",
                        "account_type": "demo" if self.is_demo else "real"
                    }
                )

                # SSL context
                import ssl

                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                # Connect with headers
                self.websocket = await asyncio.wait_for(
                    connect(
                        url,
                        ssl=ssl_context,
                        extra_headers={
                            "Origin": "https://pocketoption.com",
                            "Cache-Control": "no-cache",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 OPR/125.)",
                        },
                        ping_interval=None,
                        ping_timeout=None,
                        close_timeout=10,
                    ),
                    timeout=15.0,
                )

                # Update connection info
                region = self._extract_region_from_url(url)
                self.connection_info = ConnectionInfo(
                    url=url,
                    region=region,
                    status=ConnectionStatus.CONNECTED,
                    connected_at=datetime.now(),
                    reconnect_attempts=self.current_reconnect_attempts,
                )

                self.is_connected = True
                self.current_reconnect_attempts = 0
                self.connection_stats["total_connections"] += 1
                self.connection_stats["successful_connections"] += 1
                
                # Logar sucesso
                try:
                    await self._ws_logger.log_connected(url, region)
                except:
                    pass

                logger.success(f"[SUCCESS] Connected to {url} (region: {region})", extra={
                    "user_name": self.user_name,
                    "account_id": "",
                    "account_type": "demo" if self.is_demo else "real"
                })

                # Send initial handshake
                await self._send_handshake()

                await self._emit_event("connected", {"url": url, "region": region})

                return True

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(f"[TIMEOUT] Timeout connecting to {url}: {e}")
                try:
                    await self._ws_logger.log_error(e, f"Timeout connecting to {url}")
                except:
                    pass
            except ConnectionRefusedError as e:
                last_error = e
                logger.warning(f"[BLOCKED] Connection refused to {url}: {e}")
                try:
                    await self._ws_logger.log_error(e, f"Connection refused to {url}")
                except:
                    pass
            except OSError as e:
                last_error = e
                # Handle DNS errors specifically
                if hasattr(e, 'errno') and e.errno == 11001:  # getaddrinfo failed
                    logger.error(f"[DNS] DNS resolution failed for {url}: {e}")
                    logger.warning("[INFO] This might be a network issue. Will try next URL...")
                else:
                    logger.warning(f"[CONNECT] Network error connecting to {url}: {e}")
                try:
                    await self._ws_logger.log_error(e, f"Network error connecting to {url}")
                except:
                    pass
            except ConnectionError as e:
                last_error = e
                logger.warning(f"[WARNING] Connection error to {url}: {type(e).__name__}: {e}")
                try:
                    await self._ws_logger.log_error(e, f"Connection error to {url}")
                except:
                    pass
            except Exception as e:
                last_error = e
                logger.warning(f"[WARNING] Failed to connect to {url}: {type(e).__name__}: {e}", exc_info=False)
                try:
                    await self._ws_logger.log_error(e, f"Failed to connect to {url}")
                except:
                    pass

            # Clean up current connection
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None

            # Pequeno delay antes de tentar próxima URL
            if attempt < len(self.available_urls) - 1:
                await asyncio.sleep(1)

        # Se chegou aqui, todas as URLs falharam
        logger.error(f"❌ Failed to connect to all {len(self.available_urls)} available URLs")
        if last_error:
            logger.error(f"Last error: {type(last_error).__name__}: {last_error}")
            try:
                await self._ws_logger.log_error(last_error, "All connection attempts failed")
            except:
                pass
        return False

    async def _send_handshake(self):
        """Send initial handshake sequence"""
        self._is_handshaking = True
        try:
            if not self.websocket:
                raise RuntimeError("Handshake called with no websocket connection.")

            # Wait for initial connection message
            initial_message = await asyncio.wait_for(
                self.websocket.recv(), timeout=10.0
            )
            logger.debug(f"Received initial: {initial_message}")

            # Send handshake sequence
            await self.websocket.send("40")
            await asyncio.sleep(0.1)

            # Wait for connection establishment
            conn_message = await asyncio.wait_for(
                self.websocket.recv(), timeout=10.0
            )
            logger.debug(f"Received connection: {conn_message}")

            # Send SSID authentication - use the complete SSID with PHP data
            await self.websocket.send(self.ssid)
            logger.debug("Handshake completed")
            
            # Logar autenticação
            if self._ws_logger:
                try:
                    await self._ws_logger.log_authenticated({
                        "ssid_preview": self.ssid[:30] if self.ssid else None,
                        "user_name": self.user_name,
                        "is_demo": self.is_demo
                    })
                except:
                    pass

            # Solicitar trades fechados para corrigir trades incompletos no banco de dados
            try:
                await asyncio.sleep(0.5)  # Esperar um pouco para a conexão estar pronta
                await self.websocket.send('42["getClosedDeals"]')
                logger.info("Solicitando trades fechados (getClosedDeals)")
            except Exception as e:
                logger.warning(f"Erro ao solicitar trades fechados: {e}")

            self.connection_stats["total_messages_sent"] += 2

        except ConnectionError as e:
            logger.error(f"Connection error during handshake: {e}", exc_info=True)
            raise
        except asyncio.TimeoutError as e:
            logger.error(f"Handshake timeout: {e}")
            raise
        except Exception as e:
            logger.error(f"Handshake failed: {e}", exc_info=True)
            raise
        finally:
            self._is_handshaking = False

    async def _start_background_tasks(self):
        """Start all background tasks"""
        # Ping task (every 20 seconds)
        self._ping_task = asyncio.create_task(self._ping_loop())

        # Message receiving task
        self._message_task = asyncio.create_task(self._message_loop())

        # Health monitor task (every 30 seconds)
        self._health_task = asyncio.create_task(self._health_monitor_loop())

        # Reconnection monitoring task (every 5 seconds)
        self._reconnect_task = asyncio.create_task(self._reconnection_monitor())

    async def _ping_loop(self):
        """Continuous ping loop"""
        while self.should_reconnect:
            try:
                if self.is_connected and self.websocket:
                    # Send ping message
                    await self.websocket.send('42["ps"]')
                    self.connection_stats["last_ping_time"] = datetime.now()
                    self.connection_stats["total_messages_sent"] += 1
                    
                    # Log ping
                    if self._ws_logger:
                        try:
                            await self._ws_logger.log_ping()
                        except:
                            pass

                await asyncio.sleep(self.ping_interval)

            except ConnectionClosed:
                logger.warning("✗ Connection closed during ping")
                self.is_connected = False
                break
            except OSError as e:
                # Handle Windows-specific socket errors (WinError 121)
                if hasattr(e, 'winerror') and e.winerror == 121:
                    logger.warning(f"✗ Windows socket timeout (WinError 121) during ping: {e}")
                else:
                    logger.error(f"✗ OSError during ping: {e}")
                self.is_connected = False
                break
            except ConnectionError as e:
                logger.error(f"✗ Connection error during ping: {e}")
                self.is_connected = False
                break
            except Exception as e:
                logger.error(f"✗ Ping failed: {e}", exc_info=False)
                self.is_connected = False
                break

    async def _message_loop(self):
        """Continuous message receiving loop"""
        while self.should_reconnect:
            try:
                # Se handshake está em andamento, aguardar para evitar conflito de recv()
                if self._is_handshaking:
                    await asyncio.sleep(0.1)
                    continue

                if self.is_connected and self.websocket:
                    try:
                        # Receive message with timeout
                        message = await asyncio.wait_for(
                            self.websocket.recv(), timeout=30.0
                        )

                        self.connection_stats["total_messages_received"] += 1
                        
                        # Log mensagem recebida (para debugging)
                        if self._ws_logger:
                            try:
                                msg_str = message.decode('utf-8', errors='ignore') if isinstance(message, bytes) else str(message)
                                # Não logar pings/pongs para não poluir
                                if msg_str not in ["2", "3"] and not msg_str.startswith("42[\"ps\"]"):
                                    await self._ws_logger.log_message_received(msg_str, preview=True)
                            except:
                                pass

                        await self._process_message(message)

                    except asyncio.TimeoutError:
                        continue
                else:
                    await asyncio.sleep(1)

            except ConnectionClosed:
                logger.warning("✗ Connection closed during message receive")
                self.is_connected = False
                if self._ws_logger:
                    try:
                        await self._ws_logger.log_disconnect("ConnectionClosed in message loop")
                    except:
                        pass
                break
            except OSError as e:
                # Handle Windows-specific socket errors (WinError 121)
                if hasattr(e, 'winerror') and e.winerror == 121:
                    logger.warning(f"✗ Windows socket timeout (WinError 121) during message receive: {e}")
                else:
                    logger.error(f"✗ OSError during message receive: {e}")
                self.is_connected = False
                if self._ws_logger:
                    try:
                        await self._ws_logger.log_error(e, "Socket error in message loop")
                    except:
                        pass
                break
            except ConnectionError as e:
                logger.error(f"✗ Connection error during message receive: {e}")
                self.is_connected = False
                if self._ws_logger:
                    try:
                        await self._ws_logger.log_error(e, "Connection error in message loop")
                    except:
                        pass
                break
            except asyncio.TimeoutError as e:
                logger.warning(f"✗ Timeout during message receive: {e}")
                self.is_connected = False
                break
            except Exception as e:
                logger.error(f"✗ Message loop error: {e}", exc_info=False)
                self.is_connected = False
                break

    async def _health_monitor_loop(self):
        """Monitor connection health and trigger reconnects if needed"""
        while self.should_reconnect:
            try:
                await asyncio.sleep(30)

                if not self.is_connected:
                    logger.warning("✗ Health check: Connection lost")
                    continue

                # Check if we received a pong recently
                if self.connection_stats["last_ping_time"]:
                    time_since_ping = (
                        datetime.now() - self.connection_stats["last_ping_time"]
                    )
                    if time_since_ping > timedelta(seconds=60):
                        logger.warning(
                            "✗ Health check: No ping response, connection may be dead"
                        )
                        self.is_connected = False

                # Check WebSocket state
                if self.websocket and self.websocket.closed:
                    logger.warning("✗ Health check: WebSocket is closed")
                    self.is_connected = False

            except Exception as e:
                logger.error(f"✗ Health monitor error: {e}", exc_info=False)

    def _should_reconnect_with_autotrade_check(self) -> bool:
        """Verificar se deve reconectar, incluindo checagem do status do autotrade no banco"""
        # Se should_reconnect está desativado localmente, não reconectar
        if not self.should_reconnect:
            return False
        
        # Se não temos account_id, não podemos verificar o status do autotrade
        # Então permitimos reconexão (comportamento padrão)
        if not self.account_id:
            return True
        
        # Verificar se o autotrade ainda está ativo no banco de dados
        try:
            import asyncio
            # Usar asyncio.create_task para não bloquear, mas retornar True por enquanto
            # A verificação real será feita no reconnection_manager
            return True
        except Exception:
            return True

    async def _check_autotrade_active(self) -> bool:
        """Verificar no banco de dados se o autotrade está ativo para esta conta"""
        logger.info(
            f"[AUTOTRADE CHECK] Verificando status para account_id={self.account_id}, user={self.user_name}"
        )
        
        if not self.account_id:
            logger.warning(f"[AUTOTRADE CHECK] Sem account_id, permitindo reconexão por padrão")
            return True  # Se não temos account_id, assumir que está ativo
        
        try:
            from core.database import get_db_context
            from sqlalchemy import text
            
            async with get_db_context() as db:
                # Verificar se existe alguma config ativa para esta conta
                result = await db.execute(
                    text("""
                        SELECT EXISTS(
                            SELECT 1 FROM autotrade_configs 
                            WHERE account_id = :account_id 
                            AND is_active = TRUE
                        ) as has_active_autotrade
                    """),
                    {"account_id": self.account_id}
                )
                row = result.fetchone()
                is_active = bool(row[0]) if row else False
                
                logger.info(
                    f"[AUTOTRADE CHECK] Resultado para account_id={self.account_id}: "
                    f"is_active={is_active}, raw_value={row[0] if row else None}"
                )
                
                if not is_active:
                    logger.warning(
                        f"[RECONNECTION BLOCKED] [{self.account_id}] Autotrade INATIVO no banco de dados. "
                        f"Reconexão será impedida para {self.user_name}",
                        extra={
                            "user_name": self.user_name,
                            "account_id": self.account_id[:8] if self.account_id else "",
                            "account_type": "demo" if self.is_demo else "real"
                        }
                    )
                else:
                    logger.info(
                        f"[AUTOTRADE CHECK] [{self.account_id}] Autotrade ATIVO - permitindo reconexão"
                    )
                
                return is_active
        except Exception as e:
            logger.error(
                f"[ERROR] [{self.account_id}] Erro ao verificar status do autotrade: {e}. "
                f"Permitindo reconexão por segurança.",
                extra={
                    "user_name": self.user_name,
                    "account_id": self.account_id[:8] if self.account_id else "",
                    "account_type": "demo" if self.is_demo else "real"
                }
            )
            return True  # Em caso de erro, permitir reconexão

    async def _reconnection_monitor(self):
        """Monitor for disconnections and automatically reconnect"""
        logger.info("[REBALANCE] Reconnection monitor started")

        # Usar gerenciador unificado de reconexão
        try:
            from services.data_collector.reconnection_manager import get_reconnection_manager
        except ImportError:
            logger.warning("Could not import reconnection_manager, using local monitor")
            return

        reconnection_manager = get_reconnection_manager()

        # Registrar esta conexão no gerenciador unificado
        connection_id = f"keep_alive_{id(self)}"
        self._reconnection_id = connection_id  # CRITICAL: Armazenar para poder fazer unregister depois
        
        # Criar callback de verificação de autotrade - sempre verifica no banco
        async def should_reconnect_with_check():
            """Verificar no banco se autotrade está ativo para esta conta"""
            logger.info(f"[RECONNECTION CHECK] Verificando se deve reconectar para {self.user_name} (account_id={self.account_id})")
            result = await self._check_autotrade_active()
            logger.info(f"[RECONNECTION CHECK] Resultado para {self.user_name}: should_reconnect={result}")
            return result
        
        reconnection_manager.register_connection(
            connection_id=connection_id,
            client=self,
            connect_fn=self._establish_connection,
            disconnect_fn=self._disconnect_current,
            check_connected_fn=lambda c: c.is_connected,
            config={
                'max_retries': self.max_reconnect_attempts,
                'initial_delay': self.reconnect_delay,
                'max_delay': self.max_reconnect_delay,
                'backoff_multiplier': 2,
                'should_reconnect': should_reconnect_with_check
            },
            connection_type="monitoring_payout",
            description=f"[SISTEMA] Monitoramento Payout - SSID: {self.ssid[:25]}... (demo)"
        )

        logger.info(f"[OK] Conexão '{connection_id}' registrada no gerenciador unificado")

        # Não executar loop local - usar gerenciador unificado
        logger.info("[REBALANCE] Usando gerenciador unificado de reconexão")

    async def _disconnect_current(self):
        """Desconectar conexão atual"""
        if self.websocket:
            try:
                await self.websocket.close()
                logger.debug("� Conexão atual fechada")
            except Exception as e:
                logger.debug(f"Erro ao fechar conexão: {e}")
            self.websocket = None

    async def _process_message(self, message):
        """Process incoming messages"""
        try:
            # Registrar mensagem recebida no performance monitor
            try:
                from services.performance_monitor import record_ws_message_global
                record_ws_message_global(sent=False)
            except Exception:
                pass
            
            # Normalize memoryview to bytes
            if isinstance(message, memoryview):
                message = message.tobytes()

            # Handle bytes messages first (like websocket.py does)
            if isinstance(message, bytes):
                try:
                    decoded_message = message.decode("utf-8", errors="ignore")
                    
                    # Try to parse as JSON
                    import json
                    json_data = json.loads(decoded_message)
                    
                    # Check if this is history data (waiting for history data)
                    if hasattr(self, '_waiting_for_history_data') and self._waiting_for_history_data:
                        self._waiting_for_history_data = False
                        # Emit as candles_received event
                        await self._emit_event("candles_received", json_data)
                        asset = json_data.get("asset") if isinstance(json_data, dict) else None
                        history_len = 0
                        if isinstance(json_data, dict):
                            history_len = len(json_data.get("history", []) or json_data.get("candles", []))
                        logger.debug(
                            f"[OK] History data received (bytes) - asset={asset}, candles={history_len}"
                        )
                        return
                    
                    # Check if this is assets data (waiting for assets data)
                    if hasattr(self, '_waiting_for_assets_data') and self._waiting_for_assets_data:
                        self._waiting_for_assets_data = False
                        # Emit as assets_update event
                        await self._emit_event("assets_update", json_data)
                        assets_count = len(json_data) if isinstance(json_data, list) else 0
                        logger.info(f"[OK] Assets data received (bytes) - {assets_count} assets")
                        return
                    
                    # Check if this is stream data (waiting for stream data)
                    if hasattr(self, '_waiting_for_stream_data') and self._waiting_for_stream_data:
                        self._waiting_for_stream_data = False
                        # Emit as stream_update event
                        await self._emit_event("stream_update", json_data)
                        return
                    
                    # Check if this is balance data (waiting for balance data)
                    if hasattr(self, '_waiting_for_balance_data') and self._waiting_for_balance_data:
                        self._waiting_for_balance_data = False
                        # Emit as balance_data event
                        if isinstance(json_data, dict) and "balance" in json_data:
                            balance_type = "demo" if json_data.get('isDemo') else "real"
                            balance_amount = json_data.get('balance', 'N/A')
                            logger.info(f"*** Balance data received [{self.user_name}] ({balance_type}): ${balance_amount}")
                            await self._emit_event("balance_data", json_data)
                            return

                    # Process balance data even if not waiting for it (initial connection balance)
                    if isinstance(json_data, dict) and "balance" in json_data:
                        balance_type = "demo" if json_data.get('isDemo') else "real"
                        balance_amount = json_data.get('balance', 'N/A')
                        logger.info(f"*** Balance data received [{self.user_name}] ({balance_type}): ${balance_amount}")
                        await self._emit_event("balance_data", json_data)
                        return
                    
                    # Emit as json_data event
                    await self._emit_event("json_data", json_data)
                    return
                    
                except json.JSONDecodeError as e:
                    # Not JSON – continue processing as text so candle/stream handlers can try to parse
                    message = decoded_message
                except Exception as e:
                    logger.error(f"Error processing binary message: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return

            # Convert bytes to string if needed
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="ignore")

            # Handle ping-pong (only log on error)
            if message == "2":
                if self.websocket:
                    await self.websocket.send("3")
                    self.connection_stats["last_pong_time"] = datetime.now()
                return

            # Handle authentication success
            if "successauth" in message:
                await self._emit_event("authenticated", {})
                return

            # Handle Socket.IO messages (format: 42["event",data] or 451-["event",data])
            if message.startswith("42["):
                try:
                    import json
                    # Extract JSON from Socket.IO message
                    json_str = message[3:]  # Remove "42[" prefix
                    
                    # Handle JSON with extra data (multiple JSON objects concatenated)
                    try:
                        json_data = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        if "Extra data" in str(e):
                            # Use raw_decode to parse only the first JSON object
                            decoder = json.JSONDecoder()
                            json_data, idx = decoder.raw_decode(json_str)
                        else:
                            raise

                    # Handle successauth event
                    if isinstance(json_data, list) and len(json_data) > 0:
                        event_type = json_data[0]

                        if event_type == "successauth":
                            await self._emit_event("authenticated", json_data[1] if len(json_data) > 1 else {})
                            return

                        if event_type == "successupdateBalance":
                            # Emit balance_updated event
                            balance_data = json_data[1] if len(json_data) > 1 else {}
                            logger.info(f"Balance update received (42): {balance_data}")
                            await self._emit_event("balance_updated", balance_data)
                            return

                        if event_type == "updateHistoryNewFast":
                            # Control message, next message contains history data
                            self._waiting_for_history_data = True
                            logger.debug("⏳ updateHistoryNewFast received (42) - awaiting history data")
                            return

                        if event_type == "updateStream":
                            # The data format from updateStream is: {"asset":"EURUSD_otc","period":60,"data":[...]}
                            stream_data = json_data[1] if len(json_data) > 1 else {}
                            # Emit as stream_update event
                            await self._emit_event("stream_update", stream_data)
                            return

                    # Emit as json_data event
                    await self._emit_event("json_data", json_data)
                    return
                except Exception as e:
                    logger.error(f"Error processing Socket.IO message: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return

            # Handle Socket.IO binary messages (format: 451-["event",data])
            if message.startswith("451-["):
                try:
                    import json
                    # Extract JSON from Socket.IO binary message
                    # Remove "451-" prefix, the rest should be valid JSON starting with "["
                    if len(message) <= 4:
                        logger.warning(f"Invalid Socket.IO binary message: too short")
                        return
                    json_str = message[4:]  # Remove "451-" prefix
                    json_data = json.loads(json_str)

                    # Handle events
                    if isinstance(json_data, list) and len(json_data) > 0:
                        event_type = json_data[0]

                        if event_type == "successupdateBalance":
                            # Check if this is a placeholder (data comes in next binary message)
                            event_data = json_data[1] if len(json_data) > 1 else {}
                            if isinstance(event_data, dict) and event_data.get('_placeholder'):
                                # Set flag to wait for next binary message with balance data
                                self._waiting_for_balance_data = True
                                logger.debug("⏳ successupdateBalance received (451) - awaiting balance data")
                                return
                            else:
                                # Emit balance_updated event directly
                                logger.info(f"Balance update received (451): {json_data}")
                                await self._emit_event("balance_updated", event_data)
                                return

                        if event_type == "updateHistoryNewFast":
                            # This is a control message, the actual data comes in the next binary message
                            self._waiting_for_history_data = True
                            logger.debug("⏳ updateHistoryNewFast received (451) - awaiting history data")
                            return

                        if event_type == "updateStream":
                            # This is a control message, the actual data comes in the next binary message
                            self._waiting_for_stream_data = True
                            return

                        if event_type == "updateAssets":
                            # This is a control message, the actual data comes in the next binary message
                            self._waiting_for_assets_data = True
                            logger.debug("⏳ updateAssets received (451) - awaiting assets data")
                            return

                        if event_type == "updateClosedDeals":
                            # Emit update_closed_deals event
                            event_data = json_data[1] if len(json_data) > 1 else []
                            await self._emit_event("update_closed_deals", event_data)
                            logger.debug(f"updateClosedDeals received (451): {len(event_data) if isinstance(event_data, list) else 'N/A'} deals")
                            return

                    # Emit as json_data event
                    await self._emit_event("json_data", json_data)
                    return
                except Exception as e:
                    logger.error(f"Error processing Socket.IO binary message: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return

            # Check if we're waiting for history data and it arrived as string
            if hasattr(self, '_waiting_for_history_data') and self._waiting_for_history_data:
                import json
                try:
                    json_data = json.loads(message)
                    self._waiting_for_history_data = False
                    await self._emit_event("candles_received", json_data)
                    asset = json_data.get("asset") if isinstance(json_data, dict) else None
                    history_len = 0
                    if isinstance(json_data, dict):
                        history_len = len(json_data.get("history", []) or json_data.get("candles", []))
                    logger.debug(
                        f"[OK] History data received (text) - asset={asset}, candles={history_len}"
                    )
                    return
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Error parsing history data as text: {e}")
                    self._waiting_for_history_data = False

            # Handle assets update (payout data)
            if "updateAssets" in message:
                # This is a control message, the actual data comes in the next message
                # We'll store this and wait for the next message with the actual data
                self._waiting_for_assets_data = True
                return
            
            # Check if we're waiting for assets data
            if hasattr(self, '_waiting_for_assets_data') and self._waiting_for_assets_data:
                # This should be the actual assets data
                import json
                try:
                    # The message format is: [[5,"#AAPL","Apple","stock",2,50,60,30,3,0,170,0,[],1768408500,false,[{"time":60},{"time":120},...]]
                    if isinstance(message, str) and message.startswith("[["):
                        assets_data = json.loads(message)
                        await self._emit_event("assets_update", assets_data)
                        logger.info(f"[OK] Assets updated: {len(assets_data)} assets")
                    elif isinstance(message, list):
                        await self._emit_event("assets_update", message)
                        logger.info(f"[OK] Assets updated: {len(message)} assets")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"Could not parse assets data: {e}")
                finally:
                    self._waiting_for_assets_data = False
                return
            
            # Check if we're waiting for candles data
            if hasattr(self, '_waiting_for_candles_data') and self._waiting_for_candles_data:
                # This should be the actual candles data
                import json
                try:
                    # Try to parse as JSON
                    if isinstance(message, str):
                        candles_data = json.loads(message)
                        await self._emit_event("candles_received", candles_data)
                        await self._emit_event("stream_update", candles_data)
                    elif isinstance(message, list):
                        await self._emit_event("candles_received", {"history": message})
                        await self._emit_event("stream_update", {"history": message})
                    elif isinstance(message, dict):
                        await self._emit_event("candles_received", message)
                        await self._emit_event("stream_update", message)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Could not parse candles data: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                finally:
                    self._waiting_for_candles_data = False
                return

            # Handle other message types - only log errors
            # await self._emit_event("message_received", {"message": message})

        except Exception as e:
            logger.error(f"✗ Error processing message: {e}")

    async def send_message(self, message: str) -> bool:
        """Send message with connection check"""
        try:
            if self.is_connected and self.websocket:
                await self.websocket.send(message)
                self.connection_stats["total_messages_sent"] += 1
                
                # Registrar no performance monitor
                try:
                    from services.performance_monitor import record_ws_message_global
                    record_ws_message_global(sent=True)
                except Exception:
                    pass
                
                return True
            else:
                logger.warning("Cannot send message: not connected")
                return False
        except Exception as e:
            logger.error(f"Failed to send message: {e}", extra={
                "user_name": self.user_name,
                "account_id": "",
                "account_type": "demo" if self.is_demo else "real"
            })
            self.is_connected = False
            return False

    def add_event_handler(self, event: str, handler: Callable):
        """Add event handler"""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    async def _emit_event(self, event: str, data: Any):
        """Emit event to handlers"""
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    elif callable(handler):
                        handler(data)
                except Exception as e:
                    logger.error(f"Error in event handler for {event}: {e}")

    def _extract_region_from_url(self, url: str) -> str:
        """Extract region name from URL"""
        try:
            if "//" not in url:
                return "UNKNOWN"
            parts = url.split("//")[1].split(".")[0]
            if "api-" in parts:
                return parts.replace("api-", "").upper()
            elif "demo" in parts:
                return "DEMO"
            else:
                return "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get detailed connection statistics"""
        return {
            **self.connection_stats,
            "is_connected": self.is_connected,
            "current_url": self.connection_info.url if self.connection_info else None,
            "current_region": self.connection_info.region
            if self.connection_info
            else None,
            "reconnect_attempts": self.current_reconnect_attempts,
            "uptime": (
                datetime.now() - self.connection_info.connected_at
                if self.connection_info and self.connection_info.connected_at
                else timedelta()
            ),
            "available_regions": len(self.available_urls),
        }

    async def connect_with_keep_alive(
        self, regions: Optional[List[str]] = None
    ) -> bool:
        """Establish a persistent connection with keep-alive"""
        if regions:
            self.available_urls = regions
            self.current_url_index = 0
        return await self.start_persistent_connection()

    async def disconnect(self) -> None:
        """Disconnect and clean up persistent connection"""
        await self.stop_persistent_connection()

    def get_stats(self) -> Dict[str, Any]:
        """Return connection statistics (alias for get_connection_stats)"""
        return self.get_connection_stats()
