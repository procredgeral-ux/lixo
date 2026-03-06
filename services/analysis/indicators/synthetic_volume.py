"""
Sistema de Volume Sintético Baseado na Força de Movimento do Preço

Este módulo implementa um sistema de volume sintético que calcula um valor de volume
baseado na força do movimento do preço, volatilidade e outras métricas de mercado.
Isso permite que indicadores que dependem de volume funcionem corretamente mesmo quando
o volume real não está disponível nos dados de preços.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SyntheticVolumeCalculator:
    """Calcula volume sintético baseado na força de movimento do preço"""

    def __init__(self, lookback: int = 14):
        """
        Inicializa o calculador de volume sintético

        Args:
            lookback: Período para cálculos de média e volatilidade
        """
        self.lookback = lookback

    def calculate(
        self,
        data: pd.DataFrame,
        price_column: str = 'close'
    ) -> pd.Series:
        """
        Calcula volume sintético baseado na força de movimento do preço

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            Series com valores de volume sintético
        """
        if price_column not in data.columns:
            logger.error(f"Coluna {price_column} não encontrada no DataFrame")
            return pd.Series(0, index=data.index)

        try:
            # Calcular componentes do volume sintético
            price_change = self._calculate_price_change(data, price_column)
            volatility = self._calculate_volatility(data, price_column)
            momentum = self._calculate_momentum(data, price_column)
            range_component = self._calculate_range_component(data, price_column)

            # Combinar componentes com pesos ajustados para gerar mais variação
            synthetic_volume = (
                price_change * 0.4 +
                volatility * 0.3 +
                momentum * 0.2 +
                range_component * 0.1
            )

            # Adicionar ruído aleatório para gerar mais variação
            import random
            random.seed(int(hash(str(data[price_column].iloc[-1])) % 1000000))
            noise = pd.Series([random.uniform(0.8, 1.2) for _ in range(len(data))], index=data.index)
            synthetic_volume = synthetic_volume * noise

            # Normalizar para valores entre 1 e 1000
            synthetic_volume = self._normalize_volume(synthetic_volume)

            # Log silenciado
            # logger.debug(f"✓ Volume sintético calculado: média={synthetic_volume.mean():.2f}")

            return synthetic_volume

        except Exception as e:
            logger.error(f"Erro ao calcular volume sintético: {e}", exc_info=True)
            return pd.Series(0, index=data.index)

    def _calculate_price_change(
        self,
        data: pd.DataFrame,
        price_column: str
    ) -> pd.Series:
        """
        Calcula componente baseado na mudança de preço

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            Series com componente de mudança de preço
        """
        # Calcular mudança percentual de preço
        price_change = data[price_column].pct_change().abs()

        # Multiplicar por 100 para escala
        price_change = price_change * 100

        # Preencher NaN com 0
        price_change = price_change.fillna(0)

        return price_change

    def _calculate_volatility(
        self,
        data: pd.DataFrame,
        price_column: str
    ) -> pd.Series:
        """
        Calcula componente baseado na volatilidade

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            Series com componente de volatilidade
        """
        # Calcular volatilidade rolling
        volatility = data[price_column].rolling(window=self.lookback).std()

        # Normalizar pela média
        volatility_mean = volatility.rolling(window=self.lookback).mean()
        volatility = volatility / volatility_mean

        # Multiplicar por 100 para escala
        volatility = volatility * 100

        # Preencher NaN com 1 (valor médio)
        volatility = volatility.fillna(1)

        return volatility

    def _calculate_momentum(
        self,
        data: pd.DataFrame,
        price_column: str
    ) -> pd.Series:
        """
        Calcula componente baseado no momentum

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            Series com componente de momentum
        """
        # Calcular momentum (diferença entre preço atual e preço anterior)
        momentum = data[price_column].diff(periods=self.lookback).abs()

        # Normalizar pelo preço médio
        avg_price = data[price_column].rolling(window=self.lookback).mean()
        momentum = momentum / avg_price

        # Multiplicar por 1000 para escala
        momentum = momentum * 1000

        # Preencher NaN com 0
        momentum = momentum.fillna(0)

        return momentum

    def _calculate_range_component(
        self,
        data: pd.DataFrame,
        price_column: str
    ) -> pd.Series:
        """
        Calcula componente baseado no range de preços

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            Series com componente de range
        """
        # Calcular high-low range (se houver colunas high/low)
        if 'high' in data.columns and 'low' in data.columns:
            range_val = data['high'] - data['low']
            range_val = range_val / data[price_column]
        else:
            # Se não tiver high/low, usar rolling range
            rolling_max = data[price_column].rolling(window=self.lookback).max()
            rolling_min = data[price_column].rolling(window=self.lookback).min()
            range_val = (rolling_max - rolling_min) / data[price_column]

        # Multiplicar por 1000 para escala
        range_val = range_val * 1000

        # Preencher NaN com 0
        range_val = range_val.fillna(0)

        return range_val

    def _normalize_volume(
        self,
        volume: pd.Series
    ) -> pd.Series:
        """
        Normaliza volume para valores entre 1 e 1000

        Args:
            volume: Series com valores de volume

        Returns:
            Series com volume normalizado
        """
        # Usar min/max em vez de percentis para gerar mais variação
        min_val = volume.min()
        max_val = volume.max()

        # Evitar divisão por zero
        if max_val - min_val == 0:
            return pd.Series(1, index=volume.index)

        # Normalizar para 1-1000
        normalized = 1 + (volume - min_val) / (max_val - min_val) * 999

        # Limitar entre 1 e 1000
        normalized = normalized.clip(1, 1000)

        return normalized

    def add_synthetic_volume(
        self,
        data: pd.DataFrame,
        price_column: str = 'close'
    ) -> pd.DataFrame:
        """
        Adiciona coluna de volume sintético ao DataFrame

        Args:
            data: DataFrame com dados de preços
            price_column: Nome da coluna de preço

        Returns:
            DataFrame com coluna 'volume' adicionada
        """
        synthetic_volume = self.calculate(data, price_column)

        # Criar cópia do DataFrame para evitar modificar o original
        data_with_volume = data.copy()

        # Adicionar coluna de volume sintético
        data_with_volume['volume'] = synthetic_volume.astype(int)

        logger.info(f"✓ Volume sintético adicionado ao DataFrame")

        return data_with_volume


# Instância global do calculador
synthetic_volume_calculator = SyntheticVolumeCalculator()


def add_synthetic_volume(
    data: pd.DataFrame,
    price_column: str = 'close'
) -> pd.DataFrame:
    """
    Função de conveniência para adicionar volume sintético ao DataFrame

    Args:
        data: DataFrame com dados de preços
        price_column: Nome da coluna de preço

    Returns:
        DataFrame com coluna 'volume' adicionada
    """
    return synthetic_volume_calculator.add_synthetic_volume(data, price_column)
