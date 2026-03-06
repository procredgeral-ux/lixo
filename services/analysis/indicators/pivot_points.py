"""
Pivot Points Indicator

Pivot Points são níveis de suporte e resistência calculados a partir do preço
de alta, baixa e fechamento do período anterior. São usados para determinar
tendências e prever movimentos de preço.

Fórmulas:
- Pivot Point (PP) = (High + Low + Close) / 3
- Resistance 1 (R1) = (2 * PP) - Low
- Resistance 2 (R2) = PP + (High - Low)
- Support 1 (S1) = (2 * PP) - High
- Support 2 (S2) = PP - (High - Low)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class PivotPoints(TechnicalIndicator):
    """Pivot Points indicator"""

    def __init__(self):
        """Initialize Pivot Points indicator"""
        super().__init__("PivotPoints")

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Pivot Points parameters"""
        return True  # Não há parâmetros para Pivot Points

    @cached_indicator("PivotPoints")
    @handle_indicator_errors("PivotPoints", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Pivot Points (retorna DataFrame com níveis)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Pivot Points values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=2)

        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular Pivot Point
        pp = (high + low + close) / 3

        # Calcular Resistências e Suportes
        r1 = (2 * pp) - low
        r2 = pp + (high - low)
        r3 = high + 2 * (pp - low)

        s1 = (2 * pp) - high
        s2 = pp - (high - low)
        s3 = low - 2 * (high - pp)

        # Criar DataFrame
        result = pd.DataFrame({
            'pp': pp,
            'r1': r1,
            'r2': r2,
            'r3': r3,
            's1': s1,
            's2': s2,
            's3': s3
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Pivot Points calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Pivot Points with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Pivot Points values and signals
        """
        result = self.calculate(data)
        close = data['close']

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (close > result['pp']) & (close <= result['r1']) & (close.shift(1) <= result['pp'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (close < result['pp']) & (close >= result['s1']) & (close.shift(1) >= result['pp'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na posição do preço
        result['confidence'] = 0.5
        result.loc[(close > result['r2']) | (close < result['s2']), 'confidence'] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Pivot Points com sinais calculado: {len(result)} candles")

        return result

    def filter_signals(
        self,
        data: pd.DataFrame,
        signal: str
    ) -> bool:
        """
        Filtrar sinais baseado em critérios adicionais

        Args:
            data: DataFrame com dados de preços (deve ter 'close', 'pp', 'r1', 's1')
            signal: Sinal a ser filtrado ('buy', 'sell')

        Returns:
            bool: True se o sinal deve ser mantido
        """
        if signal not in ['buy', 'sell']:
            return False

        if len(data) < 2:
            return False

        # Verificar se as colunas necessárias existem
        if 'close' not in data.columns or 'pp' not in data.columns:
            return False

        # Verificar se preço está próximo ao Pivot Point
        close = data['close'].iloc[-1]
        pp = data['pp'].iloc[-1]
        r1 = data['r1'].iloc[-1]
        s1 = data['s1'].iloc[-1]

        if signal == 'buy':
            # Para buy, preço deve estar entre PP e R1
            return pp < close < r1
        else:
            # Para sell, preço deve estar entre S1 e PP
            return s1 < close < pp

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {}

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {}
