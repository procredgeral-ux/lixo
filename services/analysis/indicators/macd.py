"""MACD (Moving Average Convergence Divergence) indicator"""
import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict, Any
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class MACD(TechnicalIndicator):
    """MACD indicator"""

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ):
        """
        Initialize MACD indicator

        Args:
            fast_period: Fast EMA period (default: 12)
            slow_period: Slow EMA period (default: 26)
            signal_period: Signal line period (default: 9)
        """
        super().__init__("MACD")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate MACD parameters"""
        fast = kwargs.get('fast_period', self.fast_period)
        slow = kwargs.get('slow_period', self.slow_period)
        signal = kwargs.get('signal_period', self.signal_period)

        return (
            isinstance(fast, int) and fast > 0 and
            isinstance(slow, int) and slow > 0 and
            isinstance(signal, int) and signal > 0 and
            fast < slow
        )

    @cached_indicator("MACD")
    @handle_indicator_errors("MACD", fallback_value=(None, None, None))
    def calculate(self, data: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD values

        Args:
            data: DataFrame with OHLC data (must have 'close' column)

        Returns:
            Tuple: (macd_line, signal_line, histogram)
        """
        # Validate input data
        validate_dataframe(data, ['close'], min_rows=self.slow_period)

        if 'close' not in data.columns:
            raise ValueError("DataFrame must have 'close' column")

        close = data['close']

        # Validate data integrity
        if (close < 0).any():
            logger.warning("MACD: Detected negative price values, applying correction")
            close = close.clip(lower=0)

        # Check for extreme values
        max_price = close.max()
        if max_price > 1e10 or np.isinf(max_price) or np.isnan(max_price):
            logger.warning(f"MACD: Detected extreme price values (max: {max_price})")
            return (
                pd.Series([np.nan] * len(data), index=data.index),
                pd.Series([np.nan] * len(data), index=data.index),
                pd.Series([np.nan] * len(data), index=data.index)
            )

        # Calculate EMAs
        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()

        # Calculate MACD line
        macd_line = ema_fast - ema_slow

        # Calculate signal line
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()

        # Calculate histogram
        histogram = macd_line - signal_line

        # Clip extreme values to prevent overflow
        macd_line = macd_line.clip(-1e10, 1e10)
        signal_line = signal_line.clip(-1e10, 1e10)
        histogram = histogram.clip(-1e10, 1e10)

        return macd_line, signal_line, histogram

    def get_signal(
        self,
        data: pd.DataFrame
    ) -> Optional[str]:
        """
        Get trading signal based on MACD crossover

        Args:
            data: DataFrame with OHLC data

        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if len(data) < self.slow_period:
            return None

        macd_line, signal_line, histogram = self.calculate(data)

        # Check for crossover
        if len(histogram) >= 2:
            # Bullish crossover (histogram crosses from negative to positive)
            if histogram.iloc[-2] <= 0 and histogram.iloc[-1] > 0:
                return 'buy'
            # Bearish crossover (histogram crosses from positive to negative)
            elif histogram.iloc[-2] >= 0 and histogram.iloc[-1] < 0:
                return 'sell'

        return None

    def detect_crossover_advanced(
        self,
        macd_line: pd.Series,
        signal_line: pd.Series,
        histogram: pd.Series,
        data: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Detecção avançada de crossover

        Args:
            macd_line: Linha MACD
            signal_line: Linha de sinal
            histogram: Histograma
            data: DataFrame com OHLC

        Returns:
            Dict com tipo, força, confirmação
        """
        try:
            # Detectar crossover MACD line vs signal line
            macd_crossover = self._detect_line_crossover(macd_line, signal_line)

            # Detectar crossover histogram
            histogram_crossover = self._detect_histogram_crossover(histogram)

            # Calcular força do crossover
            strength = self._calculate_crossover_strength(macd_line, signal_line)

            # Validar com volume
            volume_confirmation = self._confirm_with_volume(data)

            result = {
                'macd_crossover': macd_crossover,
                'histogram_crossover': histogram_crossover,
                'strength': strength,
                'volume_confirmation': volume_confirmation
            }

            logger.info(
                f"✓ Crossover MACD: {macd_crossover} | Histogram: {histogram_crossover} | "
                f"Força: {strength:.2f} | Volume: {'✓' if volume_confirmation else '✗'}"
            )

            return result

        except Exception as e:
            logger.error(f"Erro ao detectar crossover avançado: {e}", exc_info=True)
            return {
                'macd_crossover': 'none',
                'histogram_crossover': 'none',
                'strength': 0,
                'volume_confirmation': False
            }

    def _detect_line_crossover(
        self,
        macd_line: pd.Series,
        signal_line: pd.Series
    ) -> str:
        """
        Detecta crossover entre MACD line e signal line

        Returns:
            'bullish', 'bearish', ou 'none'
        """
        if len(macd_line) < 2 or len(signal_line) < 2:
            return 'none'

        # Bullish crossover: MACD cruza de baixo para cima da signal line
        if (macd_line.iloc[-2] < signal_line.iloc[-2] and
            macd_line.iloc[-1] > signal_line.iloc[-1]):
            return 'bullish'

        # Bearish crossover: MACD cruza de cima para baixo da signal line
        if (macd_line.iloc[-2] > signal_line.iloc[-2] and
            macd_line.iloc[-1] < signal_line.iloc[-1]):
            return 'bearish'

        return 'none'

    def _detect_histogram_crossover(self, histogram: pd.Series) -> str:
        """
        Detecta crossover do histogram

        Returns:
            'bullish', 'bearish', ou 'none'
        """
        if len(histogram) < 2:
            return 'none'

        # Bullish crossover: histogram cruza de negativo para positivo
        if histogram.iloc[-2] <= 0 and histogram.iloc[-1] > 0:
            return 'bullish'

        # Bearish crossover: histogram cruza de positivo para negativo
        if histogram.iloc[-2] >= 0 and histogram.iloc[-1] < 0:
            return 'bearish'

        return 'none'

    def _calculate_crossover_strength(
        self,
        macd_line: pd.Series,
        signal_line: pd.Series
    ) -> float:
        """
        Calcula força do crossover (0.0 a 1.0)

        Returns:
            float: Força do crossover
        """
        if len(macd_line) == 0 or len(signal_line) == 0:
            return 0.0

        diff = abs(macd_line.iloc[-1] - signal_line.iloc[-1])
        max_diff = macd_line.abs().max()

        if max_diff == 0:
            return 0.0

        return min(1.0, diff / max_diff)

    def _confirm_with_volume(
        self,
        data: pd.DataFrame,
        lookback: int = 5
    ) -> bool:
        """
        Confirma sinal com volume

        Args:
            data: DataFrame com OHLC
            lookback: Período para análise

        Returns:
            bool: True se confirmado
        """
        if 'volume' not in data.columns:
            return False

        try:
            current_volume = data['volume'].iloc[-1]
            avg_volume = data['volume'].iloc[-lookback:-1].mean()

            # Ajustado threshold para 1.05 (5% acima da média) para volume sintético
            return current_volume > avg_volume * 1.05

        except Exception as e:
            logger.error(f"Erro ao confirmar com volume: {e}", exc_info=True)
            return False

    def filter_signals(
        self,
        data: pd.DataFrame,
        signal: str
    ) -> bool:
        """
        Filtra sinais baseado em condições de mercado

        Args:
            data: DataFrame com OHLC
            signal: Sinal ('buy' ou 'sell')

        Returns:
            bool: True se sinal deve ser mantido
        """
        try:
            # Detectar mercado lateral
            is_ranging = self._is_ranging_market(data)

            # Detectar baixa volatilidade
            is_low_volatility = self._is_low_volatility(data)

            # Filtrar se mercado lateral ou baixa volatilidade
            if is_ranging or is_low_volatility:
                logger.debug(f"❌ Sinal {signal} filtrado: mercado lateral ou baixa volatilidade")
                return False

            return True

        except Exception as e:
            logger.error(f"Erro ao filtrar sinais: {e}", exc_info=True)
            return True

    def _is_ranging_market(
        self,
        data: pd.DataFrame,
        lookback: int = 20
    ) -> bool:
        """
        Detecta se o mercado está lateral

        Args:
            data: DataFrame com OHLC
            lookback: Período para análise

        Returns:
            bool: True se mercado lateral
        """
        try:
            close = data['close'].iloc[-lookback:]

            # Calcular range
            high = close.max()
            low = close.min()
            range_pct = (high - low) / low

            # Se range < 2%, mercado lateral
            return range_pct < 0.02

        except Exception as e:
            logger.error(f"Erro ao detectar mercado lateral: {e}", exc_info=True)
            return False

    def _is_low_volatility(
        self,
        data: pd.DataFrame,
        lookback: int = 20
    ) -> bool:
        """
        Detecta se há baixa volatilidade

        Args:
            data: DataFrame com OHLC
            lookback: Período para análise

        Returns:
            bool: True se baixa volatilidade
        """
        try:
            close = data['close'].iloc[-lookback:]

            # Calcular volatilidade (desvio padrão)
            volatility = close.pct_change().std()

            # Se volatilidade < 1%, baixa volatilidade
            return volatility < 0.01

        except Exception as e:
            logger.error(f"Erro ao detectar baixa volatilidade: {e}", exc_info=True)
            return False

    def detect_divergence(
        self,
        data: pd.DataFrame,
        macd_line: pd.Series,
        lookback: int = 14
    ) -> Dict[str, Any]:
        """
        Detecta divergência entre preço e MACD

        Args:
            data: DataFrame com OHLC
            macd_line: Linha MACD
            lookback: Período para análise

        Returns:
            Dict com tipo de divergência e força
        """
        try:
            close = data['close']
            current_close = close.iloc[-1]
            current_macd = macd_line.iloc[-1]

            # Obter valores históricos
            past_close_high = close.iloc[-lookback:-1].max()
            past_close_low = close.iloc[-lookback:-1].min()
            past_macd_high = macd_line.iloc[-lookback:-1].max()
            past_macd_low = macd_line.iloc[-lookback:-1].min()

            # Detectar divergência
            divergence = 'none'

            if current_close < past_close_low and current_macd > past_macd_low:
                divergence = 'bullish'
            elif current_close > past_close_high and current_macd < past_macd_high:
                divergence = 'bearish'

            # Calcular força da divergência
            strength = 0
            if divergence != 'none':
                strength = self._calculate_divergence_strength(
                    data, macd_line, divergence, lookback
                )

            result = {
                'divergence': divergence,
                'strength': strength
            }

            if divergence != 'none':
                logger.info(f"✓ Divergência {divergence} detectada | Força: {strength}/10")

            return result

        except Exception as e:
            logger.error(f"Erro ao detectar divergência: {e}", exc_info=True)
            return {'divergence': 'none', 'strength': 0}

    def _calculate_divergence_strength(
        self,
        data: pd.DataFrame,
        macd_line: pd.Series,
        divergence: str,
        lookback: int = 14
    ) -> int:
        """
        Calcula força da divergência (1-10)

        Args:
            data: DataFrame com OHLC
            macd_line: Linha MACD
            divergence: Tipo de divergência
            lookback: Período para análise

        Returns:
            int: Força da divergência (1-10)
        """
        try:
            strength = 5  # Base strength

            # Calcular diferença de preço
            close = data['close']

            if divergence == 'bullish':
                price_diff = close.iloc[-lookback:-1].min() - close.iloc[-1]
                macd_diff = macd_line.iloc[-1] - macd_line.iloc[-lookback:-1].min()
            else:  # bearish
                price_diff = close.iloc[-1] - close.iloc[-lookback:-1].max()
                macd_diff = macd_line.iloc[-lookback:-1].max() - macd_line.iloc[-1]

            # Aumentar força se as diferenças forem grandes
            if price_diff > 0:
                strength += min(2, int(price_diff / close.iloc[-1] * 100))

            if macd_diff > 0:
                strength += min(2, int(macd_diff / 10))

            # Limitar a 10
            return min(10, strength)

        except Exception as e:
            logger.error(f"Erro ao calcular força da divergência: {e}", exc_info=True)
            return 0

    def calculate_signal_strength(
        self,
        macd_line: pd.Series,
        signal_line: pd.Series
    ) -> float:
        """
        Calcula força do sinal (0.0 a 1.0)

        Args:
            macd_line: Linha MACD
            signal_line: Linha de sinal

        Returns:
            float: Força do sinal
        """
        if len(macd_line) == 0 or len(signal_line) == 0:
            return 0.0

        diff = abs(macd_line.iloc[-1] - signal_line.iloc[-1])
        max_diff = macd_line.abs().max()

        if max_diff == 0:
            return 0.0

        return min(1.0, diff / max_diff)
