"""
Keltner Channels Indicator

Keltner Channels são um indicador de volatilidade baseado em bandas que
envolvem o preço. Similar às Bollinger Bands, mas usam ATR (Average True Range)
em vez de desvio padrão para determinar a largura das bandas.

O indicador consiste de:
- Upper Band: EMA + (ATR * Multiplicador)
- Middle Band: EMA
- Lower Band: EMA - (ATR * Multiplicador)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class KeltnerChannels(TechnicalIndicator):
    """Keltner Channels indicator"""

    def __init__(
        self,
        ema_period: int = 5,
        atr_period: int = 5,
        multiplier: float = 2.0
    ):
        """
        Initialize Keltner Channels indicator

        Args:
            ema_period: Período para a EMA (default: 20)
            atr_period: Período para o ATR (default: 20)
            multiplier: Multiplicador do ATR (default: 2.0)
        """
        super().__init__("KeltnerChannels")
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.multiplier = multiplier

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Keltner Channels parameters"""
        ema_period = kwargs.get('ema_period', self.ema_period)
        atr_period = kwargs.get('atr_period', self.atr_period)
        multiplier = kwargs.get('multiplier', self.multiplier)

        return (
            isinstance(ema_period, int) and ema_period > 0 and
            isinstance(atr_period, int) and atr_period > 0 and
            isinstance(multiplier, (int, float)) and multiplier > 0
        )

    @cached_indicator("KeltnerChannels")
    @handle_indicator_errors("KeltnerChannels", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Keltner Channels values (retorna DataFrame com bandas)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Keltner Channels values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=max(self.ema_period, self.atr_period))

        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular EMA (Middle Band)
        middle_band = close.ewm(span=self.ema_period, adjust=False).mean()

        # Calcular True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Calcular ATR
        atr = tr.rolling(window=self.atr_period).mean()

        # Calcular Upper e Lower Bands
        upper_band = middle_band + (atr * self.multiplier)
        lower_band = middle_band - (atr * self.multiplier)

        # Criar DataFrame
        result = pd.DataFrame({
            'upper_band': upper_band,
            'middle_band': middle_band,
            'lower_band': lower_band
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Keltner Channels calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Keltner Channels with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Keltner Channels values and signals
        """
        result = self.calculate(data)
        close = data['close']

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (close < result['lower_band']) & (close.shift(1) >= result['lower_band'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (close > result['upper_band']) & (close.shift(1) <= result['upper_band'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na força do movimento
        result['confidence'] = 0.5
        band_width = result['upper_band'] - result['lower_band']
        result.loc[band_width > band_width.rolling(window=20).mean() * 1.5, 'confidence'] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Keltner Channels com sinais calculado: {len(result)} candles")

        return result

    def filter_signals(
        self,
        data: pd.DataFrame,
        signal: str
    ) -> bool:
        """
        Filtrar sinais baseado em critérios adicionais

        Args:
            data: DataFrame com dados de preços (deve ter 'close', 'upper_band', 'middle_band', 'lower_band')
            signal: Sinal a ser filtrado ('buy', 'sell')

        Returns:
            bool: True se o sinal deve ser mantido
        """
        if signal not in ['buy', 'sell']:
            return False

        if len(data) < self.ema_period:
            return False

        # Verificar se as colunas necessárias existem
        if 'close' not in data.columns or 'middle_band' not in data.columns:
            return False

        # Verificar se preço está retornando para a banda média
        close = data['close'].iloc[-1]
        middle_band = data['middle_band'].iloc[-1]
        upper_band = data['upper_band'].iloc[-1]
        lower_band = data['lower_band'].iloc[-1]

        if signal == 'buy':
            # Para buy, preço deve estar saindo da banda inferior
            return close > lower_band and close < middle_band
        else:
            # Para sell, preço deve estar saindo da banda superior
            return close < upper_band and close > middle_band

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'ema_period': 20,
            'atr_period': 20,
            'multiplier': 2.0
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'ema_period': 'Período para a EMA (banda média). Determina a suavização do indicador.',
            'atr_period': 'Período para o ATR. Determina a sensibilidade à volatilidade.',
            'multiplier': 'Multiplicador do ATR. Valores maiores alargam as bandas, valores menores as estreitam.'
        }
