"""WebSocket router for real-time chart data updates"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from typing import Optional
import json
import asyncio
from loguru import logger

from services.data_collector.realtime import data_collector
from core.security.auth import decode_token

router = APIRouter()


class ConnectionManager:
    """Gerenciador production-ready de conexões WebSocket com proteção contra clientes lentos"""
    
    def __init__(self):
        # user_id -> Set de WebSockets (suporta múltiplas abas, com limite)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # symbol -> {connection_id: (websocket, user_id)} para compatibilidade com endpoints existentes
        self._symbol_connections: Dict[str, Dict[str, tuple]] = {}
        self._connection_counter = 0
        self.MAX_CONNECTIONS_PER_USER = 5
        self.SEND_TIMEOUT = 2.0  # segundos
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, symbol: str, user_id: str = None) -> str:
        """
        Aceita nova conexão WebSocket com limite por usuário
        
        Args:
            websocket: Conexão WebSocket
            symbol: Símbolo/canal da conexão
            user_id: ID do usuário (para controle de limite)
            
        Returns:
            connection_id: ID único da conexão
        """
        await websocket.accept()
        
        # Gerar ID único
        connection_id = f"{symbol}_{self._connection_counter}"
        self._connection_counter += 1
        
        # Se não tiver user_id, usa o connection_id como fallback
        effective_user_id = user_id or connection_id
        
        async with self._lock:
            # 1. Verificar limite de conexões por usuário
            if effective_user_id not in self.active_connections:
                self.active_connections[effective_user_id] = set()
            
            if len(self.active_connections[effective_user_id]) >= self.MAX_CONNECTIONS_PER_USER:
                logger.warning(f"User {effective_user_id} excedeu limite de {self.MAX_CONNECTIONS_PER_USER} conexões.")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return None
            
            # Adicionar à estrutura de usuário
            self.active_connections[effective_user_id].add(websocket)
            
            # Adicionar à estrutura de símbolo (para broadcasts por symbol)
            if symbol not in self._symbol_connections:
                self._symbol_connections[symbol] = {}
            self._symbol_connections[symbol][connection_id] = (websocket, effective_user_id)
        
        logger.info(f"WebSocket connected: {connection_id} for {symbol} (user: {effective_user_id})")
        return connection_id
    
    async def disconnect(self, connection_id: str, symbol: str):
        """Remove conexão WebSocket de todas as estruturas"""
        async with self._lock:
            # Remover da estrutura de símbolo
            if symbol in self._symbol_connections and connection_id in self._symbol_connections[symbol]:
                websocket, user_id = self._symbol_connections[symbol][connection_id]
                del self._symbol_connections[symbol][connection_id]
                
                # Remover da estrutura de usuário
                if user_id in self.active_connections:
                    self.active_connections[user_id].discard(websocket)
                    if not self.active_connections[user_id]:
                        del self.active_connections[user_id]
                
                # Limpar símbolo vazio
                if not self._symbol_connections[symbol]:
                    del self._symbol_connections[symbol]
        
        logger.info(f"WebSocket disconnected: {connection_id} from {symbol}")
        
        # Sinalizar evento de desconexão
        self._signal_disconnect(connection_id)
    
    def get_disconnect_event(self, connection_id: str) -> asyncio.Event:
        """Retorna evento de desconexão para uma conexão específica"""
        # Criar evento se não existir
        if not hasattr(self, '_disconnect_events'):
            self._disconnect_events: Dict[str, asyncio.Event] = {}
        
        if connection_id not in self._disconnect_events:
            self._disconnect_events[connection_id] = asyncio.Event()
        
        return self._disconnect_events[connection_id]
    
    def _signal_disconnect(self, connection_id: str):
        """Sinaliza que uma conexão foi desconectada"""
        if hasattr(self, '_disconnect_events') and connection_id in self._disconnect_events:
            self._disconnect_events[connection_id].set()
            del self._disconnect_events[connection_id]
    
    async def _safe_send(self, websocket: WebSocket, message: str, connection_id: str, timeout: float = None):
        """
        Envia mensagem com timeout rigoroso para não travar o worker
        
        Args:
            websocket: Conexão WebSocket
            message: Mensagem em formato string (JSON)
            connection_id: ID da conexão para logging
            timeout: Timeout em segundos (default: self.SEND_TIMEOUT)
        """
        timeout = timeout or self.SEND_TIMEOUT
        try:
            await asyncio.wait_for(websocket.send_text(message), timeout=timeout)
        except (asyncio.TimeoutError, Exception) as e:
            logger.error(f"Falha no envio para {connection_id}: {type(e).__name__}. Desconectando...")
            raise  # Re-raise para tratamento no broadcast
    
    async def broadcast_to_user(self, user_id: str, message: dict):
        """
        Broadcast para todas as abas de um único usuário (paralelo com timeout)
        
        Args:
            user_id: ID do usuário
            message: Mensagem em formato dict (será convertida para JSON)
        """
        async with self._lock:
            if user_id not in self.active_connections:
                return
            
            connections = list(self.active_connections[user_id])
        
        if not connections:
            return
        
        message_str = json.dumps(message)
        
        # 3. Execução Paralela (Garante que um WS lento não atrase os outros)
        tasks = [
            self._safe_send(ws, message_str, f"{user_id}_{i}")
            for i, ws in enumerate(connections)
        ]
        
        # 4. Gather com return_exceptions para evitar crash do loop
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Remover conexões que falharam
        failed_connections = [
            connections[i] for i, result in enumerate(results)
            if isinstance(result, Exception)
        ]
        
        if failed_connections:
            async with self._lock:
                for ws in failed_connections:
                    self.active_connections[user_id].discard(ws)
                    # Fechar websocket se ainda estiver aberto
                    try:
                        await ws.close()
                    except:
                        pass
                
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
    
    async def broadcast_global(self, message: dict):
        """
        Broadcast para TODOS os usuários conectados (ex: Signals, Maintenance)
        Paralelo com isolamento de erros
        """
        async with self._lock:
            all_connections = [
                (user_id, ws)
                for user_id, connections in self.active_connections.items()
                for ws in list(connections)
            ]
        
        if not all_connections:
            return
        
        message_str = json.dumps(message)
        
        # Criar tarefas para todas as conexões
        tasks = [
            self._safe_send(ws, message_str, f"{user_id}_{i}")
            for i, (user_id, ws) in enumerate(all_connections)
        ]
        
        # Executar em paralelo com proteção contra falhas
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def broadcast_tick(self, symbol: str, tick_data: dict):
        """Broadcast de tick para todos os clientes de um símbolo (paralelo com timeout)"""
        async with self._lock:
            if symbol not in self._symbol_connections:
                return
            
            connections = list(self._symbol_connections[symbol].items())
        
        if not connections:
            return
        
        message = json.dumps({
            "type": "tick",
            "symbol": symbol,
            "data": tick_data
        })
        
        # Broadcast paralelo
        tasks = [
            self._safe_send(ws, message, conn_id)
            for conn_id, (ws, _) in connections
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Limpar conexões que falharam
        failed_ids = [
            connections[i][0] for i, result in enumerate(results)
            if isinstance(result, Exception)
        ]
        
        for conn_id in failed_ids:
            await self.disconnect(conn_id, symbol)
    
    async def broadcast_candle(self, symbol: str, candle_data: dict):
        """Broadcast de candle para todos os clientes de um símbolo (paralelo com timeout)"""
        async with self._lock:
            if symbol not in self._symbol_connections:
                return
            
            connections = list(self._symbol_connections[symbol].items())
        
        if not connections:
            return
        
        message = json.dumps({
            "type": "candle",
            "symbol": symbol,
            "data": candle_data
        })
        
        # Broadcast paralelo
        tasks = [
            self._safe_send(ws, message, conn_id)
            for conn_id, (ws, _) in connections
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Limpar conexões que falharam
        failed_ids = [
            connections[i][0] for i, result in enumerate(results)
            if isinstance(result, Exception)
        ]
        
        for conn_id in failed_ids:
            await self.disconnect(conn_id, symbol)
    
    async def broadcast_performance_update(self, user_id: str, strategy_id: str, performance_data: dict):
        """Broadcast de atualização de performance para um usuário específico"""
        message = {
            "type": "performance_update",
            "user_id": user_id,
            "strategy_id": strategy_id,
            "data": performance_data
        }
        await self.broadcast_to_user(user_id, message)
    
    async def broadcast_strategy_status(self, user_id: str, strategy_id: str, is_active: bool, reason: str = None):
        """Broadcast de mudança de status da estratégia para um usuário específico"""
        message = {
            "type": "strategy_status_update",
            "user_id": user_id,
            "strategy_id": strategy_id,
            "is_active": is_active,
            "reason": reason
        }
        await self.broadcast_to_user(user_id, message)
    
    async def broadcast_maintenance_status(self, is_under_maintenance: bool):
        """Broadcast de status de manutenção para TODOS os clientes"""
        message = {
            "type": "maintenance_status",
            "is_under_maintenance": is_under_maintenance
        }
        await self.broadcast_global(message)


# Instância global do gerenciador de conexões
manager = ConnectionManager()


@router.websocket("/ws/ticks")
async def websocket_ticks(
    websocket: WebSocket,
    symbol: str = Query(..., description="Asset symbol (e.g., EUR/USD)")
):
    """
    Endpoint WebSocket para receber atualizações de ticks em tempo real
    
    Args:
        websocket: Conexão WebSocket
        symbol: Símbolo do ativo (ex: EUR/USD)
    
    Mensagens recebidas:
        - {"type": "subscribe", "symbol": "EUR/USD"}
        - {"type": "unsubscribe", "symbol": "EUR/USD"}
    
    Mensagens enviadas:
        - {"type": "tick", "symbol": "EUR/USD", "data": {"price": 1.0850, "timestamp": "2024-01-01T00:00:00Z"}}
    """
    connection_id = await manager.connect(websocket, symbol)
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "symbol": symbol,
            "connection_id": connection_id
        }))
        
        # Loop principal para receber mensagens do cliente
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                # Responder ao ping
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": message.get("timestamp")
                }))
            
            elif message.get("type") == "subscribe":
                # Cliente quer se inscrever em um símbolo (já está inscrito pelo path)
                subscribed_symbol = message.get("symbol", symbol)
                logger.info(f"Client {connection_id} subscribed to {subscribed_symbol}")
            
            elif message.get("type") == "unsubscribe":
                # Cliente quer cancelar a inscrição
                unsubscribed_symbol = message.get("symbol", symbol)
                logger.info(f"Client {connection_id} unsubscribed from {unsubscribed_symbol}")
                break
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, symbol)


@router.websocket("/ws/candles")
async def websocket_candles(
    websocket: WebSocket,
    symbol: str = Query(..., description="Asset symbol (e.g., EUR/USD)"),
    timeframe: str = Query("M1", description="Timeframe: 5s, 30s, M1, M5, M15, M30, H1, H4, D1")
):
    """
    Endpoint WebSocket para receber atualizações de candles em tempo real
    
    Args:
        websocket: Conexão WebSocket
        symbol: Símbolo do ativo (ex: EUR/USD)
        timeframe: Timeframe dos candles
    
    Mensagens enviadas:
        - {"type": "connected", "symbol": "EUR/USD", "timeframe": "M1", "connection_id": "..."}
        - {"type": "candle", "symbol": "EUR/USD", "data": {"timestamp": "...", "open": 1.0850, "high": 1.0860, "low": 1.0845, "close": 1.0855, "volume": 0}}
    """
    connection_id = await manager.connect(websocket, f"{symbol}_{timeframe}")
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "symbol": symbol,
            "timeframe": timeframe,
            "connection_id": connection_id
        }))
        
        # Manter conexão aberta para receber atualizações do backend
        # Aguardar desconexão via evento (sem busy wait)
        disconnect_event = manager.get_disconnect_event(connection_id)
        await disconnect_event.wait()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, f"{symbol}_{timeframe}")


@router.websocket("/ws/maintenance")
async def websocket_maintenance(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication")
):
    """
    Endpoint WebSocket para receber notificações de manutenção em tempo real
    
    Args:
        websocket: Conexão WebSocket
        token: Token JWT para autenticação
    
    Mensagens enviadas:
        - {"type": "connected", "connection_id": "..."}
        - {"type": "maintenance_status", "is_under_maintenance": true/false}
        - {"type": "strategy_status_update", "strategy_id": "...", "is_active": false, "reason": "..."}
    """
    # Extrair user_id do token JWT
    payload = decode_token(token)
    user_id = payload.get("sub") if payload else None
    
    connection_id = await manager.connect(websocket, "maintenance", user_id=user_id)
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "connection_id": connection_id
        }))
        
        # Manter conexão aberta para receber notificações
        # Aguardar desconexão via evento (sem busy wait)
        disconnect_event = manager.get_disconnect_event(connection_id)
        await disconnect_event.wait()
            
    except WebSocketDisconnect:
        logger.info(f"Maintenance WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"Maintenance WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, "maintenance")


@router.websocket("/ws/health")
async def websocket_health(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication")
):
    """
    Endpoint WebSocket para receber notificações de health status em tempo real
    
    Args:
        websocket: Conexão WebSocket
        token: Token JWT para autenticação
    
    Mensagens enviadas:
        - {"type": "connected", "connection_id": "..."}
        - {"type": "health_status", "is_healthy": true/false}
    """
    connection_id = await manager.connect(websocket, "health")
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "connection_id": connection_id
        }))
        
        # Manter conexão aberta para receber notificações
        # Aguardar desconexão via evento (sem busy wait)
        disconnect_event = manager.get_disconnect_event(connection_id)
        await disconnect_event.wait()
    except Exception as e:
        logger.error(f"Health WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, "health")


@router.websocket("/ws/signals")
async def websocket_signals(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication")
):
    """
    Endpoint WebSocket para receber notificações de sinais em tempo real
    
    Args:
        websocket: Conexão WebSocket
        token: Token JWT para autenticação
    
    Mensagens enviadas:
        - {"type": "connected", "connection_id": "..."}
        - {"type": "new_signal", "signal": {...}}
    """
    connection_id = await manager.connect(websocket, "signals")
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "connection_id": connection_id
        }))
        
        # Manter conexão aberta para receber notificações
        # Aguardar desconexão via evento (sem busy wait)
        disconnect_event = manager.get_disconnect_event(connection_id)
        await disconnect_event.wait()
    except Exception as e:
        logger.error(f"Signals WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, "signals")


@router.websocket("/ws/trades")
async def websocket_trades(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication")
):
    """
    Endpoint WebSocket para receber notificações de trades em tempo real
    
    Args:
        websocket: Conexão WebSocket
        token: Token JWT para autenticação
    
    Mensagens enviadas:
        - {"type": "connected", "connection_id": "..."}
        - {"type": "new_trade", "trade": {...}}
        - {"type": "trade_updated", "trade": {...}}
    """
    connection_id = await manager.connect(websocket, "trades")
    
    try:
        # Enviar mensagem de confirmação
        await websocket.send_text(json.dumps({
            "type": "connected",
            "connection_id": connection_id
        }))
        
        # Manter conexão aberta para receber notificações
        # Aguardar desconexão via evento (sem busy wait)
        disconnect_event = manager.get_disconnect_event(connection_id)
        await disconnect_event.wait()
    except Exception as e:
        logger.error(f"Trades WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(connection_id, "trades")


# Funções helper para enviar atualizações do data collector
async def broadcast_tick_update(symbol: str, tick_data: dict):
    """Envia atualização de tick para todos os clientes conectados"""
    await manager.broadcast_tick(symbol, tick_data)


async def broadcast_candle_update(symbol: str, candle_data: dict):
    """Envia atualização de candle para todos os clientes conectados"""
    await manager.broadcast_candle(symbol, candle_data)


async def broadcast_performance_update(user_id: str, strategy_id: str, performance_data: dict):
    """Envia atualização de performance para todos os clientes conectados"""
    await manager.broadcast_performance_update(user_id, strategy_id, performance_data)


async def broadcast_strategy_status_update(user_id: str, strategy_id: str, is_active: bool, reason: str = None):
    """Envia atualização de status da estratégia para o usuário"""
    await manager.broadcast_strategy_status(user_id, strategy_id, is_active, reason)
