"""Confluence system for combining multiple indicator signals"""
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from loguru import logger
import numpy as np
import pandas as pd


class SignalDirection(Enum):
    """Signal direction"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class IndicatorWeight(Enum):
    """Base weights for different indicator types"""
    # Trend indicators (high reliability)
    RSI = 1.0
    MACD = 1.0
    SMA = 0.9
    EMA = 0.9
    
    # Momentum indicators (medium reliability)
    STOCHASTIC = 0.85
    WILLIAMS_R = 0.85
    ROC = 0.8
    
    # Volatility indicators (medium reliability)
    BOLLINGER = 0.85
    ATR = 0.7
    
    # Support/Resistance (high reliability)
    ZONAS = 1.0
    
    # Oscillators (medium reliability)
    CCI = 0.8


class ConfluenceCalculator:
    """Calculate confluence between multiple indicator signals"""
    
    def __init__(self, min_confluence: float = 0.6, require_trend_confirmation: bool = False):
        """
        Initialize confluence calculator
        
        Args:
            min_confluence: Minimum confluence threshold (0.0 to 1.0)
            require_trend_confirmation: Whether to require trend confirmation before generating signals
        """
        self.min_confluence = min_confluence
        self.require_trend_confirmation = require_trend_confirmation
        self.indicator_weights = {
            'rsi': IndicatorWeight.RSI.value,
            'macd': IndicatorWeight.MACD.value,
            'sma': IndicatorWeight.SMA.value,
            'ema': IndicatorWeight.EMA.value,
            'stochastic': IndicatorWeight.STOCHASTIC.value,
            'williams_r': IndicatorWeight.WILLIAMS_R.value,
            'roc': IndicatorWeight.ROC.value,
            'bollinger_bands': IndicatorWeight.BOLLINGER.value,
            'atr': IndicatorWeight.ATR.value,
            'zonas': IndicatorWeight.ZONAS.value,
            'cci': IndicatorWeight.CCI.value,
        }
        # Track performance history for dynamic weight adjustment
        self.indicator_performance = {
            'rsi': {'hits': 0, 'misses': 0},
            'macd': {'hits': 0, 'misses': 0},
            'sma': {'hits': 0, 'misses': 0},
            'ema': {'hits': 0, 'misses': 0},
            'stochastic': {'hits': 0, 'misses': 0},
            'williams_r': {'hits': 0, 'misses': 0},
            'roc': {'hits': 0, 'misses': 0},
            'bollinger_bands': {'hits': 0, 'misses': 0},
            'atr': {'hits': 0, 'misses': 0},
            'zonas': {'hits': 0, 'misses': 0},
            'cci': {'hits': 0, 'misses': 0},
        }
    
    def detect_trend(self, data: pd.DataFrame, period: int = 20) -> str:
        """
        Detect overall market trend using moving averages

        Args:
            data: DataFrame with OHLC data
            period: Period for moving average

        Returns:
            str: 'uptrend', 'downtrend', or 'sideways'
        """
        if len(data) < period:
            return 'sideways'

        close = data['close']

        # Calculate moving averages
        sma_short = close.rolling(window=period // 2).mean()
        sma_long = close.rolling(window=period).mean()

        # Get latest values
        current_price = close.iloc[-1]
        current_sma_short = sma_short.iloc[-1]
        current_sma_long = sma_long.iloc[-1]

        # Determine trend
        if current_price > current_sma_short > current_sma_long:
            return 'uptrend'
        elif current_price < current_sma_short < current_sma_long:
            return 'downtrend'
        else:
            return 'sideways'

    def calculate_volatility(self, data: pd.DataFrame, period: int = 20) -> float:
        """
        Calculate market volatility using standard deviation of returns

        Args:
            data: DataFrame with OHLC data
            period: Period for volatility calculation

        Returns:
            float: Volatility score (0.0 to 1.0, higher = more volatile)
        """
        if len(data) < period:
            return 0.5  # Default medium volatility

        close = data['close']

        # Calculate returns
        returns = close.pct_change().dropna()

        # Calculate standard deviation of returns
        volatility = returns.rolling(window=period).std().iloc[-1]

        # Normalize to 0-1 range (typical range is 0.001 to 0.01)
        # Use log scale for better distribution
        normalized_volatility = min(max((np.log10(volatility * 1000) + 3) / 6, 0.0), 1.0)

        return normalized_volatility

    def get_volatility_adjustment(self, volatility: float) -> float:
        """
        Get confidence adjustment based on market volatility

        Args:
            volatility: Volatility score (0.0 to 1.0)

        Returns:
            float: Adjustment factor (0.0 to 1.0, lower = reduce confidence)
        """
        # High volatility (>0.7): Reduce confidence by 20%
        if volatility > 0.7:
            return 0.8
        # Medium volatility (0.4-0.7): Reduce confidence by 10%
        elif volatility > 0.4:
            return 0.9
        # Low volatility (<0.4): No reduction
        else:
            return 1.0
    
    def should_generate_signal(self, confluence_result: Dict[str, Any], data: pd.DataFrame = None) -> bool:
        """
        Determine if signal should be generated based on confluence
        
        Args:
            confluence_result: Result from calculate_confluence
            data: DataFrame with OHLC data for trend confirmation (optional)
        
        Returns:
            bool: True if signal should be generated
        """
        direction = confluence_result.get('direction')
        confluence_score = confluence_result.get('confluence_score', 0.0)
        weighted_score = confluence_result.get('weighted_score', 0.0)
        
        # Check minimum confluence
        if confluence_score < self.min_confluence:
            return False
        
        # Check minimum weighted score
        if weighted_score < 0.4:
            return False
        
        # Check direction
        if direction == SignalDirection.HOLD:
            logger.warning(f"🚫 [CONFLUENCE] should_generate_signal: REJEITADO (direction=HOLD)")
            return False
        
        # Check trend confirmation if required
        if self.require_trend_confirmation and data is not None:
            trend = self.detect_trend(data)
            
            # For BUY signals, require uptrend
            if direction == SignalDirection.BUY and trend != 'uptrend':
                logger.info(f"📉 BUY signal rejected: trend is {trend}")
                return False
            
            # For SELL signals, require downtrend
            if direction == SignalDirection.SELL and trend != 'downtrend':
                logger.info(f"📈 SELL signal rejected: trend is {trend}")
                return False
        
        return True
    
    def update_indicator_performance(self, indicator_type: str, hit: bool):
        """
        Update performance history for an indicator
        
        Args:
            indicator_type: Type of indicator
            hit: True if signal was correct, False otherwise
        """
        indicator_type = indicator_type.lower()
        if indicator_type in self.indicator_performance:
            if hit:
                self.indicator_performance[indicator_type]['hits'] += 1
            else:
                self.indicator_performance[indicator_type]['misses'] += 1
    
    def get_dynamic_weight(self, indicator_type: str) -> float:
        """
        Get dynamic weight based on performance history

        Args:
            indicator_type: Type of indicator

        Returns:
            float: Adjusted weight
        """
        indicator_type = indicator_type.lower()
        base_weight = self.indicator_weights.get(indicator_type, 0.8)

        # Get performance data
        perf = self.indicator_performance.get(indicator_type, {'hits': 0, 'misses': 0})
        total = perf['hits'] + perf['misses']

        if total < 30:  # Aumentado de 10 para 30 para mais dados antes de ajustar pesos
            return base_weight

        # Calculate success rate
        success_rate = perf['hits'] / total if total > 0 else 0.5

        # Adjust weight based on performance
        # Success rate > 0.6: increase weight by up to 20%
        # Success rate < 0.4: decrease weight by up to 20%
        if success_rate > 0.6:
            adjustment = (success_rate - 0.6) * 0.5  # Max 20% increase
            return min(base_weight * (1 + adjustment), 1.2)
        elif success_rate < 0.4:
            adjustment = (0.4 - success_rate) * 0.5  # Max 20% decrease
            return max(base_weight * (1 - adjustment), 0.6)

        return base_weight
    
    def calculate_confluence(
        self,
        signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate confluence score and direction

        Args:
            signals: List of signal dictionaries with keys:
                - direction: SignalDirection (BUY/SELL/HOLD)
                - confidence: float (0.0 to 1.0)
                - indicator_type: str (rsi, macd, etc.)
                - divergence: str (bullish/bearish/none, optional)

        Returns:
            Dict with confluence information
        """
        if not signals:
            return {
                'direction': SignalDirection.HOLD,
                'confluence_score': 0.0,
                'weighted_score': 0.0,
                'buy_signals': 0,
                'sell_signals': 0,
                'total_signals': 0,
                'details': []
            }

        # Filter out HOLD signals
        active_signals = [s for s in signals if s.get('direction') != SignalDirection.HOLD]

        if not active_signals:
            return {
                'direction': SignalDirection.HOLD,
                'confluence_score': 0.0,
                'weighted_score': 0.0,
                'buy_signals': 0,
                'sell_signals': 0,
                'total_signals': 0,
                'details': []
            }

        # Penalização para sinais isolados (1-2 sinais) - aumentada de 0.15 para 0.30
        isolation_penalty = 0.0
        if len(active_signals) <= 2:
            isolation_penalty = 0.30  # Aumenta 30% da confiança para sinais isolados

        # Validar diversidade de indicadores
        indicator_types = set()
        for signal in active_signals:
            indicator_type = signal.get('indicator_type', '').lower()
            # Agrupar indicadores por categoria
            if indicator_type in ['rsi', 'stochastic', 'williams_r', 'cci']:
                indicator_types.add('oscillator')
            elif indicator_type in ['macd', 'roc']:
                indicator_types.add('momentum')
            elif indicator_type in ['sma', 'ema']:
                indicator_types.add('trend')
            elif indicator_type in ['bollinger_bands', 'atr']:
                indicator_types.add('volatility')
            elif indicator_type in ['zonas']:
                indicator_types.add('support_resistance')
            else:
                indicator_types.add(indicator_type)

        # Penalização se não houver diversidade (todos do mesmo tipo) - aumentada de 0.1 para 0.20
        diversity_penalty = 0.0
        if len(indicator_types) < 2 and len(active_signals) >= 2:
            diversity_penalty = 0.20  # Reduz 20% se todos os sinais forem do mesmo tipo

        # Count signals by direction
        buy_signals = [s for s in active_signals if s.get('direction') == SignalDirection.BUY]
        sell_signals = [s for s in active_signals if s.get('direction') == SignalDirection.SELL]

        # Check for contradictory signals
        if buy_signals and sell_signals:
            return self._handle_contradictory_signals(
                buy_signals, sell_signals, 
                isolation_penalty=isolation_penalty, 
                diversity_penalty=diversity_penalty,
                signals=active_signals
            )

        # Calculate weighted score
        weighted_buy_score = self._calculate_weighted_score(buy_signals)
        weighted_sell_score = self._calculate_weighted_score(sell_signals)

        # Determine direction
        if weighted_buy_score > weighted_sell_score:
            direction = SignalDirection.BUY
            buy_count = len(buy_signals)
            sell_count = 0
        elif weighted_sell_score > weighted_buy_score:
            direction = SignalDirection.SELL
            buy_count = 0
            sell_count = len(sell_signals)
        else:
            direction = SignalDirection.HOLD
            buy_count = len(buy_signals)
            sell_count = len(sell_signals)

        # Calculate confluence score
        total_active = len(active_signals)
        confluence_score = max(buy_count, sell_count) / total_active if total_active > 0 else 0.0

        # Calculate weighted confluence
        weighted_score = max(weighted_buy_score, weighted_sell_score)

        # Apply penalties
        total_penalty = isolation_penalty + diversity_penalty
        if total_penalty > 0:
            weighted_score = max(weighted_score * (1 - total_penalty), 0.3)  # Mínimo de 0.3

        # Apply divergence bonus
        divergence_bonus = self._calculate_divergence_bonus(active_signals)
        weighted_score = min(weighted_score + divergence_bonus, 1.0)

        # Penalização para confluência muito alta (>90%) - evitar overconfidence
        if confluence_score > 0.90:
            high_confluence_penalty = 0.10  # Reduz 10% da confiança
            weighted_score = max(weighted_score * (1 - high_confluence_penalty), 0.4)

        # Confidence decay for very high scores (>95%) - aumentada de 5% para 10%
        if weighted_score > 0.95:
            # Reduz confiança muito alta para evitar overconfidence
            weighted_score = weighted_score * 0.90  # Reduz para 90% do valor original

        # Create details
        details = self._create_signal_details(active_signals)

        return {
            'direction': direction,
            'confluence_score': confluence_score,
            'weighted_score': weighted_score,
            'buy_signals': buy_count,
            'sell_signals': sell_count,
            'total_signals': total_active,
            'details': details,
            'divergence_bonus': divergence_bonus,
            'isolation_penalty': isolation_penalty,
            'diversity_penalty': diversity_penalty
        }
    
    def _calculate_weighted_score(self, signals: List[Dict[str, Any]]) -> float:
        """Calculate weighted score for a list of signals"""
        if not signals:
            return 0.0
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for signal in signals:
            indicator_type = signal.get('indicator_type', '').lower()
            confidence = signal.get('confidence', 0.0)
            
            # Use EQUAL weight for all indicators to ensure buy/sell balance
            # This prevents high-weight indicators from dominating the decision
            weight = 1.0
            
            # Apply confidence to weight
            adjusted_weight = weight * confidence
            weighted_sum += adjusted_weight
            total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
    
    def _handle_contradictory_signals(
        self,
        buy_signals: List[Dict[str, Any]],
        sell_signals: List[Dict[str, Any]],
        isolation_penalty: float = 0.0,
        diversity_penalty: float = 0.0,
        signals: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle contradictory signals by comparing weighted scores
        
        Args:
            buy_signals: List of buy signals
            sell_signals: List of sell signals
            isolation_penalty: Penalty for isolated signals (1-2 signals)
            diversity_penalty: Penalty for lack of indicator diversity
            signals: Full list of active signals for divergence calculation
        
        Returns:
            Dict with confluence information
        """
        weighted_buy_score = self._calculate_weighted_score(buy_signals)
        weighted_sell_score = self._calculate_weighted_score(sell_signals)
        
        # DEBUG: Log dos scores antes das penalidades - SILENCIADO
        # logger.debug(f"📊 [CONFLUENCE] Scores: BUY={weighted_buy_score:.3f}, SELL={weighted_sell_score:.3f} | Buy={len(buy_signals)} Sell={len(sell_signals)}")
        
        # Log detalhado dos sinais - SILENCIADO no console
        # (Comentado para reduzir flood - ative se precisar debugar)
        # for s in buy_signals:
        #     logger.debug(f"   🟢 BUY: {s.get('indicator_type', 'unknown')}")
        # for s in sell_signals:
        #     logger.debug(f"   🔴 SELL: {s.get('indicator_type', 'unknown')}")
        
        # Apply penalties before comparison
        total_penalty = isolation_penalty + diversity_penalty
        if total_penalty > 0:
            weighted_buy_score = max(weighted_buy_score * (1 - total_penalty), 0.3)
            weighted_sell_score = max(weighted_sell_score * (1 - total_penalty), 0.3)
        
        # Apply divergence bonus if signals provided
        if signals:
            divergence_bonus = self._calculate_divergence_bonus(signals)
            weighted_buy_score = min(weighted_buy_score + divergence_bonus, 1.0)
            weighted_sell_score = min(weighted_sell_score + divergence_bonus, 1.0)
        
        # DEBUG: Log dos scores finais - SILENCIADO
        # logger.debug(f"📊 [CONFLUENCE] Scores finais: BUY={weighted_buy_score:.3f}, SELL={weighted_sell_score:.3f}")
        
        # Calculate difference
        score_diff = abs(weighted_buy_score - weighted_sell_score)
        
        # If difference is too small, use signal count as tiebreaker for balance
        if score_diff < 0.15:
            # When scores are close, prefer the side with MORE signals (democracy over weighted)
            if len(buy_signals) > len(sell_signals):
                direction = SignalDirection.BUY
                buy_count = len(buy_signals)
                sell_count = 0
                weighted_score = weighted_buy_score
                # Log silenciado
                # logger.debug(f"📊 [CONFLUENCE] BUY vence por quantidade ({len(buy_signals)} > {len(sell_signals)})")
            elif len(sell_signals) > len(buy_signals):
                direction = SignalDirection.SELL
                buy_count = 0
                sell_count = len(sell_signals)
                weighted_score = weighted_sell_score
                # Log silenciado
                # logger.debug(f"📊 [CONFLUENCE] SELL vence por quantidade ({len(sell_signals)} > {len(buy_signals)})")
            else:
                # Equal scores and equal count - return HOLD
                # Log silenciado
                # logger.debug(f"📊 [CONFLUENCE] Diferença muito pequena ({score_diff:.3f}) e quantidade igual, retornando HOLD")
                return {
                    'direction': SignalDirection.HOLD,
                    'confluence_score': 0.0,
                    'weighted_score': 0.0,
                    'buy_signals': len(buy_signals),
                    'sell_signals': len(sell_signals),
                    'total_signals': len(buy_signals) + len(sell_signals),
                    'details': self._create_signal_details(buy_signals + sell_signals),
                    'contradictory': True
                }
            
            total_active = len(buy_signals) + len(sell_signals)
            confluence_score = max(buy_count, sell_count) / total_active if total_active > 0 else 0.0
            
            return {
                'direction': direction,
                'confluence_score': confluence_score,
                'weighted_score': weighted_score,
                'buy_signals': buy_count,
                'sell_signals': sell_count,
                'total_signals': total_active,
                'details': self._create_signal_details(buy_signals + sell_signals),
                'contradictory': True
            }
        
        # If difference is significant, return the stronger signal
        
        # Return the stronger signal
        if weighted_buy_score > weighted_sell_score:
            direction = SignalDirection.BUY
            buy_count = len(buy_signals)
            sell_count = 0
            weighted_score = weighted_buy_score
            logger.debug(f"📊 [CONFLUENCE] Resultado: BUY vence ({weighted_buy_score:.3f} > {weighted_sell_score:.3f})")
        else:
            direction = SignalDirection.SELL
            buy_count = 0
            sell_count = len(sell_signals)
            weighted_score = weighted_sell_score
            logger.debug(f"📊 [CONFLUENCE] Resultado: SELL vence ({weighted_sell_score:.3f} > {weighted_buy_score:.3f})")
        
        total_active = len(buy_signals) + len(sell_signals)
        confluence_score = max(buy_count, sell_count) / total_active if total_active > 0 else 0.0
        
        return {
            'direction': direction,
            'confluence_score': confluence_score,
            'weighted_score': weighted_score,
            'buy_signals': buy_count,
            'sell_signals': sell_count,
            'total_signals': total_active,
            'details': self._create_signal_details(buy_signals + sell_signals),
            'contradictory': True
        }
    
    def _calculate_divergence_bonus(self, signals: List[Dict[str, Any]]) -> float:
        """
        Calculate bonus for divergence presence
        
        Args:
            signals: List of signals
        
        Returns:
            float: Bonus score (0.0 to 0.1)
        """
        bonus = 0.0
        divergence_count = 0
        
        for signal in signals:
            divergence = signal.get('divergence', 'none')
            if divergence in ['bullish', 'bearish']:
                divergence_count += 1
        
        # Bonus increases with more divergences
        if divergence_count >= 1:
            bonus = min(divergence_count * 0.05, 0.1)
        
        return bonus
    
    def _create_signal_details(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create detailed information about each signal"""
        details = []
        
        for signal in signals:
            indicator_type = signal.get('indicator_type', 'unknown')
            confidence = signal.get('confidence', 0.0)
            direction = signal.get('direction', SignalDirection.HOLD)
            divergence = signal.get('divergence', 'none')
            
            weight = self.indicator_weights.get(indicator_type.lower(), 0.8)
            weighted_confidence = confidence * weight
            
            details.append({
                'indicator_type': indicator_type,
                'direction': direction,
                'confidence': confidence,
                'weight': weight,
                'weighted_confidence': weighted_confidence,
                'divergence': divergence
            })
        
        return details
    
    
