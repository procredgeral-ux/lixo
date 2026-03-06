"""
Donchian Channels Indicator

Donchian Channels são um indicador de tendência que mostra os preços máximos
e mínimos de um período específico. É usado para identificar tendências e
gerar sinais de entrada e saída.

O indicador consiste de:
- Upper Channel: Máximo dos últimos N períodos
- Lower Channel: Mínimo dos últimos N períodos
- Middle Channel: Média entre Upper e Lower
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class DonchianChannels(TechnicalIndicator):
    """Donchian Channels indicator"""

    def __init__(self, period: int = 5):
        """
        Initialize Donchian Channels indicator

        Args:
            period: Período para cálculo dos canais (default: 20)
        """
        super().__init__("DonchianChannels")
        self.period = period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Donchian Channels parameters"""
        period = kwargs.get('period', self.period)
        return isinstance(period, int) and period > 0

    @cached_indicator("DonchianChannels")
    @handle_indicator_errors("DonchianChannels", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Donchian Channels values (retorna DataFrame com canais)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low' columns)

        Returns:
            pd.DataFrame: DataFrame with Donchian Channels values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low'], min_rows=self.period)

        high = data['high']
        low = data['low']

        # Calcular Upper e Lower Channels
        upper_channel = high.rolling(window=self.period).max()
        lower_channel = low.rolling(window=self.period).min()

        # Calcular Middle Channel
        middle_channel = (upper_channel + lower_channel) / 2

        # Criar DataFrame
        result = pd.DataFrame({
            'upper_channel': upper_channel,
            'middle_channel': middle_channel,
            'lower_channel': lower_channel
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Donchian Channels calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Donchian Channels with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Donchian Channels values and signals
        """
        result = self.calculate(data)
        close = data['close']

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (close > result['upper_channel']) & (close.shift(1) <= result['upper_channel'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (close < result['lower_channel']) & (close.shift(1) >= result['lower_channel'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na força do rompimento
        result['confidence'] = 0.5
        result.loc[result['signal'] == 'buy', 'confidence'] = 0.7
        result.loc[result['signal'] == 'sell', 'confidence'] = 0.7

        # Log silenciado
        # logger.debug(f"✓ Donchian Channels com sinais calculado: {len(result)} candles")

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

        if len(data) < self.period:
            return False

        # Verificar se o rompimento é significativo
        close = data['close'].iloc[-1]
        upper_channel = data['upper_channel'].iloc[-1]
        lower_channel = data['lower_channel'].iloc[-1]

        if signal == 'buy':
            # Para buy, preço deve estar significativamente acima do canal superior
            return close > upper_channel * 1.002
        else:
            # Para sell, preço deve estar significativamente abaixo do canal inferior
            return close < lower_channel * 0.998

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'period': 20
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'period': 'Período para cálculo dos canais. Valores menores tornam os canais mais sensíveis, valores maiores mais suaves.'
        }
