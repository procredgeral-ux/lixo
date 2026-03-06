"""
Money Flow Index (MFI) Indicator

Money Flow Index (MFI) é um indicador de momentum que usa preço e volume
para identificar overbought e oversold. É similar ao RSI, mas incorpora volume.

O MFI é calculado usando a fórmula:
MFI = 100 - (100 / (1 + Money Flow Ratio))

Onde Money Flow Ratio = Positive Money Flow / Negative Money Flow
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class MoneyFlowIndex(TechnicalIndicator):
    """Money Flow Index indicator"""

    def __init__(self, period: int = 5):
        """
        Initialize Money Flow Index indicator

        Args:
            period: Período para cálculo (default: 14)
        """
        super().__init__("MoneyFlowIndex")
        self.period = period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate MFI parameters"""
        period = kwargs.get('period', self.period)
        return isinstance(period, int) and period > 0

    @cached_indicator("MoneyFlowIndex")
    @handle_indicator_errors("MoneyFlowIndex", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Money Flow Index values (retorna apenas Series)

        Args:
            data: DataFrame with OHLCV data (must have 'high', 'low', 'close', 'volume' columns)

        Returns:
            pd.Series: MFI values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close', 'volume'], min_rows=self.period + 1)

        # Calcular Typical Price
        typical_price = (data['high'] + data['low'] + data['close']) / 3

        # Calcular Money Flow
        money_flow = typical_price * data['volume']

        # Calcular Money Flow Ratio
        positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0)

        # Calcular médias de Money Flow
        positive_mf = positive_flow.rolling(window=self.period).sum()
        negative_mf = negative_flow.rolling(window=self.period).sum()

        # Evitar divisão por zero
        money_flow_ratio = positive_mf / negative_mf.replace(0, np.nan)

        # Calcular MFI
        mfi = 100 - (100 / (1 + money_flow_ratio))

        # Log silenciado
        # logger.debug(f"✓ Money Flow Index calculado: {len(mfi)} candles")

        return mfi

    def calculate_with_signals(
        self,
        data: pd.DataFrame,
        oversold: float = 20.0,
        overbought: float = 80.0
    ) -> pd.DataFrame:
        """
        Calculate Money Flow Index with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLCV data
            oversold: Oversold threshold (default: 20)
            overbought: Overbought threshold (default: 80)

        Returns:
            pd.DataFrame: DataFrame with MFI values and signals
        """
        mfi = self.calculate(data)

        # Criar DataFrame
        result = pd.DataFrame({
            'mfi': mfi
        }, index=data.index)

        # Gerar sinais
        result['signal'] = 'neutral'
        result.loc[(mfi < oversold) & (mfi.shift(1) >= oversold), 'signal'] = 'buy'
        result.loc[(mfi > overbought) & (mfi.shift(1) <= overbought), 'signal'] = 'sell'

        # Calcular confiança baseada na força do movimento
        result['confidence'] = 0.5
        result.loc[mfi < oversold, 'confidence'] = 0.8
        result.loc[mfi > overbought, 'confidence'] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Money Flow Index com sinais calculado: {len(result)} candles")

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

        # Verificar divergência entre preço e MFI
        mfi = data['mfi'].iloc[-1]
        mfi_prev = data['mfi'].iloc[-2]
        close = data['close'].iloc[-1]
        close_prev = data['close'].iloc[-2]

        if signal == 'buy':
            # Para buy, verificar divergência bullish
            return (close < close_prev) and (mfi > mfi_prev)
        else:
            # Para sell, verificar divergência bearish
            return (close > close_prev) and (mfi < mfi_prev)

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'period': 14
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'period': 'Período para cálculo do MFI. Valores menores tornam o indicador mais sensível, valores maiores mais suave.'
        }
