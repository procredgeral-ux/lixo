"""
AsyncAssetProcessor V2 - Integrado com CircuitBreaker e HFTExecutionBridge

Versão completa do processador de ativos HFT com:
- Indicadores incrementais (RSI, EMA, ATR, MACD)
- CircuitBreaker para proteção em mercados laterais
- HFTExecutionBridge para execução desacoplada de ordens
- Persistência Redis completa

Fluxo:
1. Tick recebido → Atualiza indicadores
2. Verifica CircuitBreaker (ATR)
3. Calcula confluência categorizada
4. Se sinal válido → Enfileira no HFTExecutionBridge
5. Bridge executa ordem com retry e idempotência
"""

import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from .persistent_rsi import PersistentRSI
from .persistent_ema import PersistentEMA
from .persistent_atr import PersistentATR
from .persistent_macd import PersistentMACD
from .circuit_breaker import CircuitBreaker
from .hft_execution_bridge import HFTExecutionBridge, ExecutionSignal
from .confluence_categorized import (
    ConfluenceCalculatorCategorized,
    IndicatorSignal,
    SignalDirection,
    IndicatorCategory
)
from core.system_manager import get_system_manager


@dataclass
class Signal:
    """Sinal de trading emitido"""
    symbol: str
    direction: str
    price: float
    score: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    breakdown: Dict = field(default_factory=dict)
    indicators_used: List[str] = field(default_factory=list)
    circuit_breaker_blocked: bool = False
    atr_value: Optional[float] = None


class AsyncAssetProcessorV2:
    """
    Processador de ativos HFT v2 - Integração completa.
    
    Args:
        symbol: Par de trading (ex: EURUSD_otc)
        redis_client: Cliente Redis para persistência
        execution_bridge: Ponte de execução para ordens (opcional)
        threshold: Score mínimo para gerar sinal
        indicators_config: Configuração dos indicadores
        circuit_breaker_config: Config do circuit breaker (None = desativado)
    """
    
    def __init__(
        self,
        symbol: str,
        redis_client=None,
        execution_bridge: Optional[HFTExecutionBridge] = None,
        threshold: float = 0.65,
        indicators_config: Optional[Dict] = None,
        circuit_breaker_config: Optional[Dict] = None
    ):
        self.symbol = symbol.upper()
        self.redis = redis_client
        self.execution_bridge = execution_bridge
        self.threshold = threshold
        
        # Configurações
        config = indicators_config or {
            'rsi': {'period': 14, 'enabled': True},
            'ema': {'period': 20, 'enabled': True},
            'atr': {'period': 14, 'enabled': True},
            'macd': {'fast': 12, 'slow': 26, 'signal': 9, 'enabled': True}
        }
        
        # Indicadores
        self.indicators: Dict[str, Any] = {}
        self.indicator_config = config
        
        if config.get('rsi', {}).get('enabled', True):
            self.indicators['rsi'] = PersistentRSI(
                symbol=self.symbol,
                period=config['rsi'].get('period', 14),
                redis_client=redis_client
            )
        
        if config.get('ema', {}).get('enabled', True):
            self.indicators['ema'] = PersistentEMA(
                symbol=self.symbol,
                period=config['ema'].get('period', 20),
                redis_client=redis_client
            )
        
        if config.get('atr', {}).get('enabled', True):
            self.indicators['atr'] = PersistentATR(
                symbol=self.symbol,
                period=config['atr'].get('period', 14),
                redis_client=redis_client
            )
        
        if config.get('macd', {}).get('enabled', True):
            macd_cfg = config['macd']
            self.indicators['macd'] = PersistentMACD(
                symbol=self.symbol,
                fast_period=macd_cfg.get('fast', 12),
                slow_period=macd_cfg.get('slow', 26),
                signal_period=macd_cfg.get('signal', 9),
                redis_client=redis_client
            )
        
        # Circuit Breaker
        self.circuit_breaker: Optional[CircuitBreaker] = None
        if circuit_breaker_config:
            self.circuit_breaker = CircuitBreaker(
                symbol=self.symbol,
                atr_threshold=circuit_breaker_config.get('atr_threshold', 0.0005),
                min_ticks=circuit_breaker_config.get('min_ticks', 5),
                redis_client=redis_client
            )
        
        # Confluência
        self.confluence = ConfluenceCalculatorCategorized(
            min_confluence=threshold,
            require_trend_confirmation=False
        )
        
        # Métricas
        self.ticks_processed = 0
        self.signals_generated = 0
        self.signals_blocked_by_cb = 0
        self.orders_enqueued = 0
        
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Inicializar carregando estados persistidos."""
        load_tasks = [
            ind.load_state()
            for ind in self.indicators.values()
        ]
        
        if self.circuit_breaker:
            load_tasks.append(self.circuit_breaker.load_state())
        
        await asyncio.gather(*load_tasks, return_exceptions=True)
        
        print(f"[AsyncAssetProcessorV2] {self.symbol} inicializado com "
              f"{len(self.indicators)} indicadores" +
              (" + CircuitBreaker" if self.circuit_breaker else ""))
    
    async def process_tick(self, price: float) -> Optional[Signal]:
        """
        Processar um tick completo (indicadores → CB → confluência → execução).
        
        Args:
            price: Preço atual
            
        Returns:
            Signal se gerado (None se filtrado)
        """
        # 🚨 VERIFICAÇÃO DO SISTEMA: Verificar se geração de sinais está habilitada
        system_manager = get_system_manager()
        if not system_manager.can_generate_signal():
            # Sistema desligado - não gerar novos sinais
            return None
        
        async with self._lock:
            self.ticks_processed += 1
        
        # 1. Atualizar indicadores
        atr_value = None
        indicator_tasks = []
        
        for name, indicator in self.indicators.items():
            indicator_tasks.append(self._update_indicator(name, indicator, price))
        
        results = await asyncio.gather(*indicator_tasks, return_exceptions=True)
        
        signals: List[IndicatorSignal] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            if result is not None:
                signals.append(result)
                # Capturar ATR se disponível
                if result.name == 'atr':
                    atr_value = result.value
        
        if not signals:
            return None
        
        # 2. Verificar Circuit Breaker (proteção contra ranging)
        cb_blocked = False
        if self.circuit_breaker and atr_value is not None:
            cb_allows = await self.circuit_breaker.check(atr_value)
            if not cb_allows:
                cb_blocked = True
                async with self._lock:
                    self.signals_blocked_by_cb += 1
                
                # Log periódico de bloqueio
                if self.signals_blocked_by_cb % 50 == 0:
                    print(f"[AsyncAssetProcessorV2] 🚫 {self.symbol}: "
                          f"{self.signals_blocked_by_cb} sinais bloqueados por CB "
                          f"(ATR: {atr_value:.6f})")
        
        # 3. Calcular confluência
        confluence_result = self.confluence.calculate_confluence(signals)
        
        # Se CB bloqueou, zerar score
        if cb_blocked:
            confluence_result = self.confluence.calculate_confluence_with_circuit_breaker(
                signals,
                circuit_breaker_active=True,
                atr_value=atr_value
            )
        
        if not confluence_result.should_trade:
            return None
        
        # 4. Criar sinal
        direction_str = 'buy' if confluence_result.direction == SignalDirection.BUY else 'sell'
        
        signal = Signal(
            symbol=self.symbol,
            direction=direction_str,
            price=price,
            score=confluence_result.final_score,
            breakdown=confluence_result.breakdown,
            indicators_used=[s.name for s in signals],
            circuit_breaker_blocked=cb_blocked,
            atr_value=atr_value
        )
        
        async with self._lock:
            self.signals_generated += 1
        
        # 5. Enviar para execução (se bridge configurado e não bloqueado)
        if self.execution_bridge and not cb_blocked:
            exec_signal = ExecutionSignal(
                symbol=self.symbol,
                direction=direction_str,
                price=price,
                score=confluence_result.final_score,
                amount=1.0,  # Configurável
                strategy_id='hft_v2',
                metadata={
                    'atr': atr_value,
                    'indicators': [s.name for s in signals],
                    'confluence_breakdown': confluence_result.breakdown
                }
            )
            
            enqueued = await self.execution_bridge.enqueue_signal(exec_signal)
            if enqueued:
                async with self._lock:
                    self.orders_enqueued += 1
        
        return signal
    
    async def _update_indicator(
        self,
        name: str,
        indicator: Any,
        price: float
    ) -> Optional[IndicatorSignal]:
        """Atualizar um indicador e retornar sinal formatado."""
        try:
            if name == 'rsi':
                rsi_value, confidence = await indicator.update(price)
                if rsi_value is None:
                    return None
                
                direction = SignalDirection.HOLD
                if rsi_value < 30:
                    direction = SignalDirection.BUY
                elif rsi_value > 70:
                    direction = SignalDirection.SELL
                
                return IndicatorSignal(
                    name='rsi',
                    category=IndicatorCategory.MOMENTUM,
                    direction=direction,
                    confidence=confidence,
                    value=rsi_value
                )
            
            elif name == 'ema':
                ema_value, confidence = await indicator.update(price)
                if ema_value is None:
                    return None
                
                direction_str = indicator.get_signal_direction(price)
                direction = SignalDirection.HOLD
                if direction_str == 'buy':
                    direction = SignalDirection.BUY
                elif direction_str == 'sell':
                    direction = SignalDirection.SELL
                
                return IndicatorSignal(
                    name='ema',
                    category=IndicatorCategory.TREND,
                    direction=direction,
                    confidence=confidence,
                    value=ema_value
                )
            
            elif name == 'atr':
                atr_value, confidence = await indicator.update(price)
                if atr_value is None:
                    return None
                
                vol_signal = indicator.get_volatility_signal()
                if vol_signal == 'high':
                    confidence *= 0.7
                
                return IndicatorSignal(
                    name='atr',
                    category=IndicatorCategory.VOLATILITY,
                    direction=SignalDirection.HOLD,
                    confidence=confidence,
                    value=atr_value
                )
            
            elif name == 'macd':
                macd_data, confidence = await indicator.update(price)
                if macd_data is None:
                    return None
                
                direction_str = indicator.get_signal_direction()
                direction = SignalDirection.HOLD
                if direction_str == 'buy':
                    direction = SignalDirection.BUY
                elif direction_str == 'sell':
                    direction = SignalDirection.SELL
                
                return IndicatorSignal(
                    name='macd',
                    category=IndicatorCategory.TREND,
                    direction=direction,
                    confidence=confidence,
                    value=macd_data.get('histogram') if macd_data else None
                )
            
            return None
            
        except Exception as e:
            print(f"[AsyncAssetProcessorV2] Erro em {name} para {self.symbol}: {e}")
            return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """Obter estatísticas do processador."""
        cb_stats = {}
        if self.circuit_breaker:
            cb_stats = await self.circuit_breaker.get_stats()
        
        async with self._lock:
            return {
                'symbol': self.symbol,
                'ticks_processed': self.ticks_processed,
                'signals_generated': self.signals_generated,
                'signals_blocked_by_cb': self.signals_blocked_by_cb,
                'orders_enqueued': self.orders_enqueued,
                'circuit_breaker': cb_stats,
                'indicators': list(self.indicators.keys())
            }
    
    async def reset(self):
        """Resetar estado completo."""
        async with self._lock:
            reset_tasks = [ind.reset() for ind in self.indicators.values()]
            
            if self.circuit_breaker:
                reset_tasks.append(self.circuit_breaker.reset())
            
            await asyncio.gather(*reset_tasks, return_exceptions=True)
            
            self.ticks_processed = 0
            self.signals_generated = 0
            self.signals_blocked_by_cb = 0
            self.orders_enqueued = 0
            
            print(f"[AsyncAssetProcessorV2] {self.symbol} resetado")
