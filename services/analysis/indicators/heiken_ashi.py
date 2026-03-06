"""
Heiken Ashi Indicator

Heiken Ashi é um tipo de gráfico que filtra o ruído do mercado e facilita
a identificação de tendências. Usa uma fórmula especial para calcular os candles
que suaviza os movimentos de preço.

Fórmulas:
- HA_Close = (Open + High + Low + Close) / 4
- HA_Open = (HA_Open anterior + HA_Close anterior) / 2
- HA_High = Max(High, HA_Open, HA_Close)
- HA_Low = Min(Low, HA_Open, HA_Close)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class HeikenAshi(TechnicalIndicator):
    """Heiken Ashi indicator"""

    def __init__(self):
        """Initialize Heiken Ashi indicator"""
        super().__init__("HeikenAshi")

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Heiken Ashi parameters"""
        return True  # Não há parâmetros para Heiken Ashi

    @cached_indicator("HeikenAshi")
    @handle_indicator_errors("HeikenAshi", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Heiken Ashi candles (retorna DataFrame com candles)

        Args:
            data: DataFrame with OHLC data (must have 'open', 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Heiken Ashi candles
        """
        # Validate input data
        validate_dataframe(data, ['open', 'high', 'low', 'close'], min_rows=2)

        open_price = data['open']
        high = data['high']
        low = data['low']
        close = data['close']

        # Calcular Heiken Ashi candles
        ha_close = (open_price + high + low + close) / 4

        # HA_Open começa com o primeiro candle normal
        ha_open = pd.Series(index=data.index, dtype=float)
        ha_open.iloc[0] = (open_price.iloc[0] + close.iloc[0]) / 2

        for i in range(1, len(data)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2

        ha_high = pd.concat([high, ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([low, ha_open, ha_close], axis=1).min(axis=1)

        # Criar DataFrame
        result = pd.DataFrame({
            'ha_open': ha_open,
            'ha_high': ha_high,
            'ha_low': ha_low,
            'ha_close': ha_close
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Heiken Ashi calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Heiken Ashi with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Heiken Ashi candles and signals
        """
        result = self.calculate(data)

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (result['ha_close'] > result['ha_open']) & (result['ha_close'].shift(1) <= result['ha_open'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (result['ha_close'] < result['ha_open']) & (result['ha_close'].shift(1) >= result['ha_open'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada em candles consecutivos
        result['confidence'] = 0.5
        for i in range(3, len(data)):
            recent_candles = result.iloc[i-3:i]
            if all(recent_candles['ha_close'] > recent_candles['ha_open']):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8
            elif all(recent_candles['ha_close'] < recent_candles['ha_open']):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8

        logger.debug(f"✓ Heiken Ashi com sinais calculado: {len(result)} candles")

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

        if len(data) < 3:
            return False

        # Verificar se há 3 candles consecutivos na mesma direção
        ha_close = data['ha_close'].iloc[-3:]
        ha_open = data['ha_open'].iloc[-3:]

        if signal == 'buy':
            # Para buy, verificar 3 candles verdes consecutivos
            return all(ha_close > ha_open)
        else:
            # Para sell, verificar 3 candles vermelhos consecutivos
            return all(ha_close < ha_open)

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {}

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {}
