"""
Fibonacci Retracement Indicator

Fibonacci Retracement é um indicador que usa níveis de suporte e resistência
baseados na sequência de Fibonacci para identificar possíveis reversões de tendência.

Níveis principais:
- 0% (High)
- 23.6%
- 38.2%
- 50%
- 61.8%
- 78.6%
- 100% (Low)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class FibonacciRetracement(TechnicalIndicator):
    """Fibonacci Retracement indicator"""

    def __init__(self, lookback: int = 35):
        """
        Initialize Fibonacci Retracement indicator

        Args:
            lookback: Período para calcular o High e Low (default: 35, reduzido de 50)
        """
        super().__init__("FibonacciRetracement")
        self.lookback = lookback

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Fibonacci Retracement parameters"""
        lookback = kwargs.get('lookback', self.lookback)
        return isinstance(lookback, int) and lookback > 0

    @cached_indicator("FibonacciRetracement")
    @handle_indicator_errors("FibonacciRetracement", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Fibonacci Retracement levels (retorna DataFrame com níveis)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Fibonacci levels
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=self.lookback)

        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular High e Low do período
        period_high = high.rolling(window=self.lookback).max()
        period_low = low.rolling(window=self.lookback).min()

        # Calcular range
        range_val = period_high - period_low

        # Calcular níveis de Fibonacci
        fib_0 = period_high
        fib_236 = period_high - (range_val * 0.236)
        fib_382 = period_high - (range_val * 0.382)
        fib_50 = period_high - (range_val * 0.5)
        fib_618 = period_high - (range_val * 0.618)
        fib_786 = period_high - (range_val * 0.786)
        fib_100 = period_low

        # Criar DataFrame
        result = pd.DataFrame({
            'fib_0': fib_0,
            'fib_236': fib_236,
            'fib_382': fib_382,
            'fib_50': fib_50,
            'fib_618': fib_618,
            'fib_786': fib_786,
            'fib_100': fib_100
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Fibonacci Retracement calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Fibonacci Retracement with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Fibonacci levels and signals
        """
        result = self.calculate(data)
        close = data['close']

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (close > result['fib_618']) & (close.shift(1) <= result['fib_618'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (close < result['fib_382']) & (close.shift(1) >= result['fib_382'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na posição do preço
        result['confidence'] = 0.5
        result.loc[(close > result['fib_50']) & (close < result['fib_236']), 'confidence'] = 0.8
        result.loc[(close < result['fib_50']) & (close > result['fib_786']), 'confidence'] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Fibonacci Retracement com sinais calculado: {len(result)} candles")

        return result

    def filter_signals(
        self,
        data: pd.DataFrame,
        signal: str
    ) -> bool:
        """
        Filtrar sinais baseado em critérios adicionais

        Args:
            data: DataFrame com dados de preços
            signal: Sinal a ser filtrado ('buy', 'sell')

        Returns:
            bool: True se o sinal deve ser mantido
        """
        if signal not in ['buy', 'sell']:
            return False

        if len(data) < self.lookback:
            return False

        # Verificar se preço está em um nível de Fibonacci importante
        close = data['close'].iloc[-1]
        fib_618 = data['fib_618'].iloc[-1]
        fib_382 = data['fib_382'].iloc[-1]
        fib_50 = data['fib_50'].iloc[-1]

        if signal == 'buy':
            # Para buy, preço deve estar acima de 61.8%
            return close > fib_618
        else:
            # Para sell, preço deve estar abaixo de 38.2%
            return close < fib_382

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'lookback': 35  # Reduzido de 50 para 35
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'lookback': 'Período para calcular o High e Low. Determina o range para os níveis de Fibonacci.'
        }
