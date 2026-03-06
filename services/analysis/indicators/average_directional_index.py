"""
Average Directional Index (ADX) Indicator

ADX é um indicador de força de tendência que não mostra a direção da tendência,
apenas a força. Valores acima de 25 indicam uma tendência forte, valores abaixo
de 20 indicam uma tendência fraca ou ausência de tendência.

O ADX é calculado usando o DMI (Directional Movement Index), que consiste em:
- +DI (Positive Directional Indicator)
- -DI (Negative Directional Indicator)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class AverageDirectionalIndex(TechnicalIndicator):
    """Average Directional Index indicator"""

    def __init__(self, period: int = 5):
        """
        Initialize ADX indicator

        Args:
            period: Período para cálculo (default: 14)
        """
        super().__init__("AverageDirectionalIndex")
        self.period = period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate ADX parameters"""
        period = kwargs.get('period', self.period)
        return isinstance(period, int) and period > 0

    @cached_indicator("AverageDirectionalIndex")
    @handle_indicator_errors("AverageDirectionalIndex", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate ADX values (retorna DataFrame com componentes)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with ADX, +DI, and -DI values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=self.period * 2)

        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Calcular ATR
        atr = tr.rolling(window=self.period).mean()

        # Calcular Directional Movement
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        # Calcular Smoothed True Range e Directional Movement
        atr_smooth = tr.rolling(window=self.period).mean()
        plus_di = 100 * (plus_dm.rolling(window=self.period).mean() / atr_smooth)
        minus_di = 100 * (minus_dm.rolling(window=self.period).mean() / atr_smooth)

        # Calcular ADX
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.rolling(window=self.period).mean()

        # Criar DataFrame
        result = pd.DataFrame({
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di
        }, index=data.index)

        # Log silenciado para reduzir poluição
        # logger.debug(f"✓ ADX calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate ADX with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with ADX, +DI, -DI values and signals
        """
        result = self.calculate(data)

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (result['plus_di'] > result['minus_di']) & 
            (result['adx'] > 25) & 
            (result['plus_di'].shift(1) <= result['minus_di'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (result['minus_di'] > result['plus_di']) & 
            (result['adx'] > 25) & 
            (result['minus_di'].shift(1) <= result['plus_di'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na força da tendência
        result['confidence'] = 0.5
        result.loc[result['adx'] > 40, 'confidence'] = 0.9
        result.loc[result['adx'] > 30, 'confidence'] = 0.7

        # Log silenciado
        # logger.debug(f"✓ ADX com sinais calculado: {len(result)} candles")

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

        # Verificar força da tendência
        adx = data['adx'].iloc[-1]

        # Apenas sinais com tendência forte
        return adx > 25

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'period': 14
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'period': 'Período para cálculo do ADX. Valores menores tornam o indicador mais sensível, valores maiores mais suave.'
        }
