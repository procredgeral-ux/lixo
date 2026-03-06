"""
Ichimoku Cloud Indicator

Ichimoku Kinko Hyo (Nuvem de Equilíbrio) é um indicador técnico japonês
que fornece uma visão completa do mercado, incluindo tendência, suporte,
resistência e momentum.

O indicador consiste de 5 componentes:
1. Tenkan-sen (Linha de Conversão)
2. Kijun-sen (Linha Base)
3. Senkou Span A (Linha Principal A)
4. Senkou Span B (Linha Principal B)
5. Chikou Span (Linha de Atraso)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class IchimokuCloud(TechnicalIndicator):
    """Ichimoku Cloud indicator"""

    def __init__(
        self,
        tenkan_period: int = 3,
        kijun_period: int = 7,
        senkou_span_b_period: int = 14,
        chikou_shift: int = 26
    ):
        """
        Initialize Ichimoku Cloud indicator

        Args:
            tenkan_period: Período para Tenkan-sen (default: 9)
            kijun_period: Período para Kijun-sen (default: 26)
            senkou_span_b_period: Período para Senkou Span B (default: 35, reduzido de 52)
            chikou_shift: Deslocamento para Chikou Span (default: 26)
        """
        super().__init__("IchimokuCloud")
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_span_b_period = senkou_span_b_period
        self.chikou_shift = chikou_shift

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Ichimoku Cloud parameters"""
        tenkan_period = kwargs.get('tenkan_period', self.tenkan_period)
        kijun_period = kwargs.get('kijun_period', self.kijun_period)
        senkou_span_b_period = kwargs.get('senkou_span_b_period', self.senkou_span_b_period)
        chikou_shift = kwargs.get('chikou_shift', self.chikou_shift)

        return (
            isinstance(tenkan_period, int) and tenkan_period > 0 and
            isinstance(kijun_period, int) and kijun_period > 0 and
            isinstance(senkou_span_b_period, int) and senkou_span_b_period > 0 and
            isinstance(chikou_shift, int) and chikou_shift > 0
        )

    @cached_indicator("IchimokuCloud")
    @handle_indicator_errors("IchimokuCloud", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Ichimoku Cloud values (retorna DataFrame com componentes)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.DataFrame: DataFrame with Ichimoku Cloud components
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=self.senkou_span_b_period)

        high = data['high']
        low = data['low']
        close = data['close']

        # Tenkan-sen (Linha de Conversão): (Máximo + Mínimo) / 2 do período
        tenkan_high = high.rolling(window=self.tenkan_period).max()
        tenkan_low = low.rolling(window=self.tenkan_period).min()
        tenkan_sen = (tenkan_high + tenkan_low) / 2

        # Kijun-sen (Linha Base): (Máximo + Mínimo) / 2 do período
        kijun_high = high.rolling(window=self.kijun_period).max()
        kijun_low = low.rolling(window=self.kijun_period).min()
        kijun_sen = (kijun_high + kijun_low) / 2

        # Senkou Span A (Linha Principal A): (Tenkan-sen + Kijun-sen) / 2, deslocado para frente
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(self.kijun_period)

        # Senkou Span B (Linha Principal B): (Máximo + Mínimo) / 2 do período, deslocado para frente
        span_b_high = high.rolling(window=self.senkou_span_b_period).max()
        span_b_low = low.rolling(window=self.senkou_span_b_period).min()
        senkou_span_b = ((span_b_high + span_b_low) / 2).shift(self.kijun_period)

        # Chikou Span (Linha de Atraso): Preço de fechamento atual, deslocado para trás
        chikou_span = close.shift(-self.chikou_shift)

        # Criar DataFrame
        result = pd.DataFrame({
            'tenkan_sen': tenkan_sen,
            'kijun_sen': kijun_sen,
            'senkou_span_a': senkou_span_a,
            'senkou_span_b': senkou_span_b,
            'chikou_span': chikou_span
        }, index=data.index)

        # Log silenciado
        # logger.debug(f"✓ Ichimoku Cloud calculado: {len(result)} candles")

        return result

    def calculate_with_signals(
        self,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate Ichimoku Cloud with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data

        Returns:
            pd.DataFrame: DataFrame with Ichimoku Cloud components and signals
        """
        result = self.calculate(data)
        close = data['close']

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[
            (result['tenkan_sen'] > result['kijun_sen']) & 
            (result['tenkan_sen'].shift(1) <= result['kijun_sen'].shift(1)),
            'signal'
        ] = 'buy'
        result.loc[
            (result['tenkan_sen'] < result['kijun_sen']) & 
            (result['tenkan_sen'].shift(1) >= result['kijun_sen'].shift(1)),
            'signal'
        ] = 'sell'

        # Calcular confiança baseada na posição do preço em relação à nuvem
        result['confidence'] = 0.5
        cloud_top = result[['senkou_span_a', 'senkou_span_b']].max(axis=1)
        cloud_bottom = result[['senkou_span_a', 'senkou_span_b']].min(axis=1)

        # Preço acima da nuvem = tendência de alta
        result.loc[close > cloud_top, 'confidence'] = 0.8
        # Preço abaixo da nuvem = tendência de baixa
        result.loc[close < cloud_bottom, 'confidence'] = 0.8

        logger.debug(f"✓ Ichimoku Cloud com sinais calculado: {len(result)} candles")

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

        if len(data) < self.kijun_period:
            return False

        # Verificar se preço está acima/abaixo da nuvem
        close = data['close'].iloc[-1]
        senkou_a = data['senkou_span_a'].iloc[-1]
        senkou_b = data['senkou_span_b'].iloc[-1]

        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        if signal == 'buy':
            # Para buy, preço deve estar acima da nuvem
            return close > cloud_top
        else:
            # Para sell, preço deve estar abaixo da nuvem
            return close < cloud_bottom

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'tenkan_period': 9,
            'kijun_period': 26,
            'senkou_span_b_period': 35,  # Reduzido de 52 para 35
            'chikou_shift': 26
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'tenkan_period': 'Período para a linha de conversão. Determina a sensibilidade a mudanças de curto prazo.',
            'kijun_period': 'Período para a linha base. Determina a tendência de médio prazo.',
            'senkou_span_b_period': 'Período para a linha principal B. Determina a tendência de longo prazo.',
            'chikou_shift': 'Deslocamento para a linha de atraso. Permite ver o preço atual em relação ao passado.'
        }
