"""
Supertrend Indicator

Supertrend é um indicador de tendência que usa ATR (Average True Range) para
determinar a direção da tendência e gerar sinais de compra e venda.

O indicador consiste de:
- Basic Upper Band = (High + Low) / 2 + (Multiplier * ATR)
- Basic Lower Band = (High + Low) / 2 - (Multiplier * ATR)
- Final Upper Band = Se Close > Final Upper Band anterior, usar Basic Upper Band, senão usar Final Upper Band anterior
- Final Lower Band = Se Close < Final Lower Band anterior, usar Basic Lower Band, senão usar Final Lower Band anterior
- Supertrend = Se Close > Final Upper Band anterior, usar Final Lower Band, senão usar Final Upper Band
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class Supertrend(TechnicalIndicator):
    """Supertrend indicator"""

    def __init__(
        self,
        atr_period: int = 5,
        multiplier: float = 3.0
    ):
        """
        Initialize Supertrend indicator

        Args:
            atr_period: Período para o ATR (default: 10)
            multiplier: Multiplicador do ATR (default: 3.0)
        """
        super().__init__("Supertrend")
        self.atr_period = atr_period
        self.multiplier = multiplier

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Supertrend parameters"""
        atr_period = kwargs.get('atr_period', self.atr_period)
        multiplier = kwargs.get('multiplier', self.multiplier)

        return (
            isinstance(atr_period, int) and atr_period > 0 and
            isinstance(multiplier, (int, float)) and multiplier > 0
        )

    @cached_indicator("Supertrend")
    @handle_indicator_errors("Supertrend", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Supertrend values (retorna DataFrame com componentes)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Supertrend values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=self.atr_period + 1)

        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Calcular ATR
        atr = tr.rolling(window=self.atr_period).mean()

        # Calcular Basic Upper e Lower Bands
        hl2 = (high + low) / 2
        basic_upper_band = hl2 + (self.multiplier * atr)
        basic_lower_band = hl2 - (self.multiplier * atr)

        # Calcular Final Upper e Lower Bands
        final_upper_band = basic_upper_band.copy()
        final_lower_band = basic_lower_band.copy()

        for i in range(1, len(data)):
            # Verificar se há NaN
            if pd.isna(basic_upper_band.iloc[i]) or pd.isna(basic_lower_band.iloc[i]):
                continue

            if close.iloc[i] > final_upper_band.iloc[i-1]:
                final_upper_band.iloc[i] = basic_upper_band.iloc[i]
            else:
                final_upper_band.iloc[i] = final_upper_band.iloc[i-1]

            if close.iloc[i] < final_lower_band.iloc[i-1]:
                final_lower_band.iloc[i] = basic_lower_band.iloc[i]
            else:
                final_lower_band.iloc[i] = final_lower_band.iloc[i-1]

        # Calcular Supertrend
        supertrend = pd.Series(index=data.index, dtype=float)
        trend = pd.Series(index=data.index, dtype=int)

        # Inicializar com primeiro valor não-NaN
        first_valid_idx = basic_upper_band.first_valid_index()
        if first_valid_idx is not None:
            supertrend.loc[first_valid_idx] = basic_upper_band.loc[first_valid_idx]
            trend.loc[first_valid_idx] = 1

        for i in range(1, len(data)):
            idx = data.index[i]
            prev_idx = data.index[i-1]

            # Verificar se há valores válidos
            if pd.isna(supertrend.iloc[i-1]) or pd.isna(final_upper_band.iloc[i]) or pd.isna(final_lower_band.iloc[i]):
                continue

            if close.iloc[i-1] <= supertrend.iloc[i-1]:
                supertrend.iloc[i] = final_upper_band.iloc[i]
                trend.iloc[i] = -1
            else:
                supertrend.iloc[i] = final_lower_band.iloc[i]
                trend.iloc[i] = 1

        # Criar DataFrame
        result = pd.DataFrame({
            'supertrend': supertrend,
            'trend': trend
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Supertrend calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Supertrend with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Supertrend values and signals
        """
        result = self.calculate(data)

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (result['trend'] == 1) & (result['trend'].shift(1) == -1),
            'signal'
        ] = 'buy'
        result.loc[
            (result['trend'] == -1) & (result['trend'].shift(1) == 1),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na força da tendência
        result['confidence'] = 0.5
        for i in range(10, len(data)):
            recent_trend = result['trend'].iloc[i-10:i]
            if all(recent_trend == 1):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8
            elif all(recent_trend == -1):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Supertrend com sinais calculado: {len(result)} candles")

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

        if len(data) < self.atr_period:
            return False

        # Verificar se há confirmação da tendência
        trend = data['trend'].iloc[-3:]

        if signal == 'buy':
            # Para buy, verificar se a tendência é bullish
            return all(trend == 1)
        else:
            # Para sell, verificar se a tendência é bearish
            return all(trend == -1)

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'atr_period': 10,
            'multiplier': 3.0
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'atr_period': 'Período para o ATR. Determina a sensibilidade à volatilidade.',
            'multiplier': 'Multiplicador do ATR. Valores maiores tornam o indicador mais lento, valores menores mais rápido.'
        }
