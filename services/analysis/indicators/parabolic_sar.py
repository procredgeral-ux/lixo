"""
Parabolic SAR Indicator

Parabolic Stop and Reverse (SAR) é um indicador de reversão de tendência
que ajuda a identificar pontos de entrada e saída. É especialmente útil
em mercados com tendências claras.

O indicador usa um ponto de partida e um fator de aceleração que aumenta
à medida que a tendência se fortalece.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class ParabolicSAR(TechnicalIndicator):
    """Parabolic Stop and Reverse indicator"""

    def __init__(
        self,
        initial_af: float = 0.02,
        max_af: float = 0.2,
        step_af: float = 0.02
    ):
        """
        Initialize Parabolic SAR indicator

        Args:
            initial_af: Fator de aceleração inicial (default: 0.02)
            max_af: Fator de aceleração máximo (default: 0.2)
            step_af: Incremento do fator de aceleração (default: 0.02)
        """
        super().__init__("ParabolicSAR")
        self.initial_af = initial_af
        self.max_af = max_af
        self.step_af = step_af

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Parabolic SAR parameters"""
        initial_af = kwargs.get('initial_af', self.initial_af)
        max_af = kwargs.get('max_af', self.max_af)
        step_af = kwargs.get('step_af', self.step_af)

        return (
            isinstance(initial_af, (int, float)) and 0 < initial_af <= 1 and
            isinstance(max_af, (int, float)) and 0 < max_af <= 1 and
            isinstance(step_af, (int, float)) and 0 < step_af <= 1 and
            initial_af <= max_af
        )

    @cached_indicator("ParabolicSAR")
    @handle_indicator_errors("ParabolicSAR", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Parabolic SAR values (retorna apenas Series)

        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)

        Returns:
            pd.Series: SAR values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=2)

        high = data['high']
        low = data['low']
        close = data['close']

        n = len(data)

        # Initialize Series
        sar = pd.Series(0.0, index=data.index)
        ep = pd.Series(0.0, index=data.index)
        af = pd.Series(0.0, index=data.index)
        trend = pd.Series(0, index=data.index)  # 1 for uptrend, -1 for downtrend

        # Start with uptrend
        trend.iloc[0] = 1
        sar.iloc[0] = low.iloc[0]
        ep.iloc[0] = high.iloc[0]
        af.iloc[0] = self.initial_af

        for i in range(1, n):
            # Update SAR
            if trend.iloc[i-1] == 1:
                # Uptrend
                sar.iloc[i] = sar.iloc[i-1] + af.iloc[i-1] * (ep.iloc[i-1] - sar.iloc[i-1])

                # Ensure SAR is below low
                if sar.iloc[i] > low.iloc[i-1]:
                    sar.iloc[i] = low.iloc[i-1]
                if sar.iloc[i] > low.iloc[i]:
                    sar.iloc[i] = low.iloc[i]

                # Check for reversal
                if low.iloc[i] < sar.iloc[i]:
                    trend.iloc[i] = -1
                    sar.iloc[i] = ep.iloc[i-1]
                    ep.iloc[i] = low.iloc[i]
                    af.iloc[i] = self.initial_af
                else:
                    trend.iloc[i] = 1
                    # Update extreme point
                    if high.iloc[i] > ep.iloc[i-1]:
                        ep.iloc[i] = high.iloc[i]
                        af.iloc[i] = min(af.iloc[i-1] + self.step_af, self.max_af)
                    else:
                        ep.iloc[i] = ep.iloc[i-1]
                        af.iloc[i] = af.iloc[i-1]
            else:
                # Downtrend
                sar.iloc[i] = sar.iloc[i-1] + af.iloc[i-1] * (ep.iloc[i-1] - sar.iloc[i-1])

                # Ensure SAR is above high
                if sar.iloc[i] < high.iloc[i-1]:
                    sar.iloc[i] = high.iloc[i-1]
                if sar.iloc[i] < high.iloc[i]:
                    sar.iloc[i] = high.iloc[i]

                # Check for reversal
                if high.iloc[i] > sar.iloc[i]:
                    trend.iloc[i] = 1
                    sar.iloc[i] = ep.iloc[i-1]
                    ep.iloc[i] = high.iloc[i]
                    af.iloc[i] = self.initial_af
                else:
                    trend.iloc[i] = -1
                    # Update extreme point
                    if low.iloc[i] < ep.iloc[i-1]:
                        ep.iloc[i] = low.iloc[i]
                        af.iloc[i] = min(af.iloc[i-1] + self.step_af, self.max_af)
                    else:
                        ep.iloc[i] = ep.iloc[i-1]
                        af.iloc[i] = af.iloc[i-1]

        # Log silenciado
        # logger.debug(f"✓ Parabolic SAR calculado: {len(sar)} candles")

        return sar

    def calculate_with_signals(
        self,
        data: pd.DataFrame,
        lookback: int = 10
    ) -> pd.DataFrame:
        """
        Calculate Parabolic SAR with signals (retorna DataFrame completo)

        Args:
            data: DataFrame with OHLC data
            lookback: Período para análise de tendência

        Returns:
            pd.DataFrame: DataFrame with SAR, trend, signals
        """
        sar = self.calculate(data)
        close = data['close']

        # Calcular trend
        trend = pd.Series(0, index=data.index)
        for i in range(1, len(data)):
            if close.iloc[i] > sar.iloc[i]:
                trend.iloc[i] = 1
            else:
                trend.iloc[i] = -1

        # Gerar sinais
        result = pd.DataFrame({
            'sar': sar,
            'trend': trend
        }, index=data.index)

        result['signal'] = 'neutral'
        result.loc[(trend == 1) & (trend.shift(1) == -1), 'signal'] = 'buy'
        result.loc[(trend == -1) & (trend.shift(1) == 1), 'signal'] = 'sell'

        # Calcular confiança baseada na força da tendência
        result['confidence'] = 0.5
        for i in range(lookback, len(data)):
            recent_trend = trend.iloc[i-lookback:i]
            if all(recent_trend == 1):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8
            elif all(recent_trend == -1):
                result.iloc[i, result.columns.get_loc('confidence')] = 0.8

        # Log silenciado
        # logger.debug(f"✓ Parabolic SAR com sinais calculado: {len(result)} candles")

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

        # Verificar se há tendência forte
        if len(data) < 10:
            return False

        recent_sar = data['sar'].iloc[-5:].values
        recent_close = data['close'].iloc[-5:].values

        # Verificar se SAR está se afastando do preço (tendência forte)
        if signal == 'buy':
            # Para buy, SAR deve estar abaixo do preço e se afastando
            return all(recent_sar < recent_close) and (recent_close[-1] - recent_sar[-1]) > (recent_close[-5] - recent_sar[-5])
        else:
            # Para sell, SAR deve estar acima do preço e se afastando
            return all(recent_sar > recent_close) and (recent_sar[-1] - recent_close[-1]) > (recent_sar[-5] - recent_close[-5])

    def get_default_parameters(self) -> Dict[str, Any]:
        """Obter parâmetros padrão para o indicador"""
        return {
            'initial_af': 0.02,
            'max_af': 0.2,
            'step_af': 0.02
        }

    def get_parameter_explanations(self) -> Dict[str, str]:
        """Obter explicações dos parâmetros"""
        return {
            'initial_af': 'Fator de aceleração inicial. Valores menores tornam o indicador mais lento, valores maiores mais rápido.',
            'max_af': 'Fator de aceleração máximo. Limita o quão rápido o indicador pode acelerar.',
            'step_af': 'Incremento do fator de aceleração. Determina o quanto o acelerador aumenta a cada novo extremo.'
        }
