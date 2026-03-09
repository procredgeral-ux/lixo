"""RSI (Relative Strength Index) indicator"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class RSI(TechnicalIndicator):
    """Relative Strength Index indicator"""

    def __init__(self, period: int = 14, smooth: int = 1, dynamic_levels: bool = False, use_true_levels: bool = False):
        """
        Initialize RSI indicator

        Args:
            period: RSI period (default: 14)
            smooth: Smoothing period for reducing noise (default: 1, no smoothing)
            dynamic_levels: Use dynamic overbought/oversold levels based on volatility (default: False)
            use_true_levels: Use True RSI Levels based on historical analysis (default: False)
        """
        super().__init__("RSI")
        self.period = period
        self.smooth = smooth
        self.dynamic_levels = dynamic_levels
        self.use_true_levels = use_true_levels

    def validate_parameters(self, **kwargs) -> bool:
        """Validate RSI parameters"""
        period = kwargs.get('period', self.period)
        smooth = kwargs.get('smooth', self.smooth)
        dynamic_levels = kwargs.get('dynamic_levels', self.dynamic_levels)
        return (
            isinstance(period, int) and period > 0 and
            isinstance(smooth, int) and smooth >= 1 and
            isinstance(dynamic_levels, bool)
        )

    @cached_indicator("RSI")
    @handle_indicator_errors("RSI", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate RSI values

        Args:
            data: DataFrame with OHLC data (must have 'close' column)

        Returns:
            pd.Series: RSI values
        """
        # Validate input data
        validate_dataframe(data, ['close'], min_rows=self.period)

        if 'close' not in data.columns:
            raise ValueError("DataFrame must have 'close' column")

        if len(data) < self.period:
            logger.warning(f"Not enough data points for RSI calculation (need {self.period}, got {len(data)})")
            return pd.Series([np.nan] * len(data), index=data.index)

        close = data['close']

        # Validate data integrity
        if (close < 0).any():
            logger.warning("RSI: Detected negative price values, applying correction")
            close = close.clip(lower=0)

        # Check for extreme values
        max_price = close.max()
        if max_price > 1e10 or np.isinf(max_price) or np.isnan(max_price):
            logger.warning(f"RSI: Detected extreme price values (max: {max_price})")
            return pd.Series([np.nan] * len(data), index=data.index)

        # Calculate price changes
        delta = close.diff().fillna(0)

        # Separate gains and losses
        gains = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        # Calculate average gains and losses (Wilder's smoothing)
        avg_gains = gains.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
        avg_losses = losses.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()

        # Calculate RS and RSI with division by zero protection
        avg_losses_safe = avg_losses.replace(0, np.nan)
        rs = avg_gains / avg_losses_safe
        rsi = 100 - (100 / (1 + rs))

        # Apply smoothing if requested
        if self.smooth > 1:
            rsi = rsi.rolling(window=self.smooth, min_periods=1).mean()

        # Clip to valid range (0 to 100)
        rsi = rsi.clip(0, 100)

        # Keep NaN values (do not fill with 50)
        return rsi

    def calculate_with_signals(
        self,
        data: pd.DataFrame,
        oversold: float = 30.0,
        overbought: float = 70.0
    ) -> pd.DataFrame:
        """
        Calculate RSI with trading signals and divergence detection

        Args:
            data: DataFrame with OHLC data
            oversold: Oversold threshold (default: 30)
            overbought: Overbought threshold (default: 70)

        Returns:
            pd.DataFrame: DataFrame with RSI, signals and divergence
        """
        rsi = self.calculate(data)

        # Use True RSI Levels if enabled
        if self.use_true_levels and len(data) >= 100:
            true_levels = self._find_true_rsi_levels(data, rsi)
            if true_levels:
                oversold = true_levels.get('oversold', oversold)
                overbought = true_levels.get('overbought', overbought)
                logger.info(f"✓ True RSI Levels: oversold={oversold:.2f}, overbought={overbought:.2f}")

        # Calculate dynamic levels if enabled
        if self.dynamic_levels:
            volatility = data['close'].pct_change().rolling(window=14).std()
            avg_volatility = volatility.mean()

            # Adjust levels based on volatility
            if avg_volatility > 0.02:  # High volatility
                oversold = 20.0
                overbought = 80.0
            elif avg_volatility > 0.01:  # Medium volatility
                oversold = 25.0
                overbought = 75.0
            # Low volatility - use default levels

        result = data.copy()
        result['rsi'] = rsi
        result['signal'] = rsi.apply(
            lambda x: self.get_signal(x, oversold, overbought)
        )
        result['confidence'] = rsi.apply(
            lambda x: self.calculate_confidence(x, oversold, overbought)
        )

        # Detect divergence
        divergence_data = self._detect_divergence(data, rsi)
        result['divergence'] = divergence_data.get('divergence', 'none')

        # Filter signals based on market conditions
        result['filtered_signal'] = self._filter_signals(data, result['signal'], result['rsi'])

        return result

    def _find_price_reversals(self, close: pd.Series, lookback: int = 100) -> List[Tuple[int, str]]:
        """
        Encontra pontos de reversão de preço

        Args:
            close: Série de preços de fechamento
            lookback: Número de períodos para analisar

        Returns:
            Lista de tuplas (índice, tipo) onde tipo é 'bottom' ou 'top'
        """
        reversals = []

        if len(close) < lookback:
            return reversals

        # Usar janela deslizante para encontrar topos e fundos
        window = 5
        for i in range(window, len(close) - window):
            # Verificar se é um fundo (bottom)
            if all(close.iloc[i-j] > close.iloc[i] for j in range(1, window+1)) and \
               all(close.iloc[i+j] > close.iloc[i] for j in range(1, window+1)):
                reversals.append((i, 'bottom'))

            # Verificar se é um topo (top)
            if all(close.iloc[i-j] < close.iloc[i] for j in range(1, window+1)) and \
               all(close.iloc[i+j] < close.iloc[i] for j in range(1, window+1)):
                reversals.append((i, 'top'))

        # Pegar apenas as últimas N reversões
        return reversals[-lookback:]

    def _group_by_levels(
        self,
        rsi_values: List[float],
        tolerance: float = 0.05
    ) -> Dict[float, List[float]]:
        """
        Agrupa valores de RSI por níveis dentro de uma tolerância

        Args:
            rsi_values: Lista de valores de RSI
            tolerance: Tolerância de 5% para agrupar

        Returns:
            Dict com nível como chave e lista de valores como valor
        """
        groups = {}

        for rsi in rsi_values:
            # Encontrar grupo existente
            found = False
            for level in groups.keys():
                if abs(rsi - level) / level <= tolerance:
                    groups[level].append(rsi)
                    found = True
                    break

            # Criar novo grupo se não encontrou
            if not found:
                groups[rsi] = [rsi]

        return groups

    def _find_confidence_levels(
        self,
        groups: Dict[float, List[float]],
        confidence: float = 0.8
    ) -> Optional[Dict[str, float]]:
        """
        Encontra níveis com confiança mínima

        Args:
            groups: Dict de grupos de RSI
            confidence: Nível de confiança mínimo (default 0.8)

        Returns:
            Dict com oversold e overbought ou None
        """
        oversold_levels = []
        overbought_levels = []

        # Separar níveis em oversold e overbought
        for level, values in groups.items():
            if len(values) < 3:  # Precisa de pelo menos 3 ocorrências
                continue

            if level < 50:
                oversold_levels.append((level, len(values)))
            else:
                overbought_levels.append((level, len(values)))

        # Ordenar por número de ocorrências
        oversold_levels.sort(key=lambda x: x[1], reverse=True)
        overbought_levels.sort(key=lambda x: x[1], reverse=True)

        # Calcular total de ocorrências
        total_oversold = sum(count for _, count in oversold_levels)
        total_overbought = sum(count for _, count in overbought_levels)

        # Encontrar níveis com confiança mínima
        oversold_level = None
        overbought_level = None

        if oversold_levels:
            top_oversold_count = oversold_levels[0][1]
            if top_oversold_count / total_oversold >= confidence:
                oversold_level = oversold_levels[0][0]

        if overbought_levels:
            top_overbought_count = overbought_levels[0][1]
            if top_overbought_count / total_overbought >= confidence:
                overbought_level = overbought_levels[0][0]

        if oversold_level is None or overbought_level is None:
            return None

        return {
            'oversold': oversold_level,
            'overbought': overbought_level
        }

    def _find_true_rsi_levels(
        self,
        data: pd.DataFrame,
        rsi: pd.Series,
        lookback: int = 100
    ) -> Optional[Dict[str, float]]:
        """
        Encontra níveis reais de RSI baseados em dados históricos

        Args:
            data: DataFrame com OHLC
            rsi: Série de valores RSI
            lookback: Número de períodos para analisar

        Returns:
            Dict com oversold e overbought ou None
        """
        try:
            # Encontrar pontos de reversão de preço
            reversals = self._find_price_reversals(data['close'], lookback)

            if len(reversals) < 10:
                logger.debug(f"Não há reversões suficientes ({len(reversals)}) para calcular True RSI Levels")
                return None

            # Separar reversões por tipo
            bottom_reversals = [idx for idx, rtype in reversals if rtype == 'bottom']
            top_reversals = [idx for idx, rtype in reversals if rtype == 'top']

            # Obter valores de RSI nas reversões
            oversold_rsi_values = [rsi.iloc[idx] for idx in bottom_reversals if idx < len(rsi)]
            overbought_rsi_values = [rsi.iloc[idx] for idx in top_reversals if idx < len(rsi)]

            if len(oversold_rsi_values) < 5 or len(overbought_rsi_values) < 5:
                logger.debug(f"Não há valores RSI suficientes (oversold={len(oversold_rsi_values)}, overbought={len(overbought_rsi_values)})")
                return None

            # Agrupar por níveis
            oversold_groups = self._group_by_levels(oversold_rsi_values, tolerance=0.05)
            overbought_groups = self._group_by_levels(overbought_rsi_values, tolerance=0.05)

            # Encontrar níveis com 80% de confiança
            oversold_level = self._find_confidence_levels(oversold_groups, confidence=0.8)
            overbought_level = self._find_confidence_levels(overbought_groups, confidence=0.8)

            if not oversold_level or not overbought_level:
                logger.debug("Não foi possível encontrar níveis com 80% de confiança")
                return None

            result = {
                'oversold': oversold_level.get('oversold', 30.0),
                'overbought': overbought_level.get('overbought', 70.0)
            }

            logger.info(f"✓ True RSI Levels encontrados: oversold={result['oversold']:.2f}, overbought={result['overbought']:.2f}")
            return result

        except Exception as e:
            logger.error(f"Erro ao calcular True RSI Levels: {e}", exc_info=True)
            return None

    def _filter_signals(
        self,
        data: pd.DataFrame,
        signals: pd.Series,
        rsi: pd.Series
    ) -> pd.Series:
        """
        Filter signals based on market conditions to reduce false positives

        Args:
            data: DataFrame with OHLC data
            signals: Original signals
            rsi: RSI values

        Returns:
            pd.Series: Filtered signals
        """
        filtered_signals = signals.copy()

        # Detect ranging market (lateralization)
        close = data['close']
        high = data['high']
        low = data['low']
        
        # Calculate range over last 20 periods
        range_high = high.rolling(window=20).max()
        range_low = low.rolling(window=20).min()
        range_pct = (range_high - range_low) / close * 100
        
        # If range is less than 2%, market is ranging - filter signals
        is_ranging = range_pct < 2.0
        
        # Calculate volatility
        volatility = close.pct_change().rolling(window=14).std()
        is_low_volatility = volatility < 0.005  # Less than 0.5% daily volatility
        
        # Filter signals in ranging or low volatility conditions
        for i in range(len(filtered_signals)):
            if i < 20:  # Need at least 20 periods for range calculation
                continue
                
            if (is_ranging.iloc[i] or is_low_volatility.iloc[i]) and filtered_signals.iloc[i] != 'hold':
                # Check for divergence - keep signal if divergence is present
                if i > 14:
                    current_close = close.iloc[i]
                    past_close_low = close.iloc[i-14:i].min()
                    past_close_high = close.iloc[i-14:i].max()
                    current_rsi = rsi.iloc[i]
                    past_rsi_low = rsi.iloc[i-14:i].min()
                    past_rsi_high = rsi.iloc[i-14:i].max()
                    
                    # Bullish divergence: lower lows + higher RSI
                    if (current_close < past_close_low and current_rsi > past_rsi_low):
                        continue  # Keep signal
                    # Bearish divergence: higher highs + lower RSI
                    elif (current_close > past_close_high and current_rsi < past_rsi_high):
                        continue  # Keep signal
                
                # No divergence - filter signal
                filtered_signals.iloc[i] = 'hold'

        return filtered_signals

    def _detect_divergence(self, data: pd.DataFrame, rsi: pd.Series, lookback: int = 14) -> Dict[str, Any]:
        """Detect divergence between price and RSI"""
        if len(data) < self.period + lookback:
            return {'divergence': 'none'}

        close = data['close']
        current_close = close.iloc[-1]
        current_rsi = rsi.iloc[-1]

        # Get historical values
        past_close_high = close.iloc[-lookback:-1].max()
        past_close_low = close.iloc[-lookback:-1].min()
        past_rsi_high = rsi.iloc[-lookback:-1].max()
        past_rsi_low = rsi.iloc[-lookback:-1].min()

        divergence = 'none'

        # Bullish divergence: lower lows + higher RSI
        if (current_close < past_close_low and current_rsi > past_rsi_low):
            divergence = 'bullish'
        # Bearish divergence: higher highs + lower RSI
        elif (current_close > past_close_high and current_rsi < past_rsi_high):
            divergence = 'bearish'

        return {
            'divergence': divergence,
            'current_close': current_close,
            'current_rsi': current_rsi,
            'past_close_high': past_close_high,
            'past_close_low': past_close_low,
            'past_rsi_high': past_rsi_high,
            'past_rsi_low': past_rsi_low
        }

    def _calculate_divergence_strength(
        self,
        data: pd.DataFrame,
        rsi: pd.Series,
        divergence_data: Dict[str, Any],
        lookback: int = 14
    ) -> int:
        """
        Calcula força da divergência (1-10)

        Args:
            data: DataFrame com OHLC
            rsi: Série de valores RSI
            divergence_data: Dados da divergência básica
            lookback: Período para análise

        Returns:
            int: Força da divergência (1-10)
        """
        if divergence_data['divergence'] == 'none':
            return 0

        try:
            strength = 5  # Base strength

            # Calcular diferença de preço
            if divergence_data['divergence'] == 'bullish':
                price_diff = divergence_data['past_close_low'] - divergence_data['current_close']
                rsi_diff = divergence_data['current_rsi'] - divergence_data['past_rsi_low']
            else:  # bearish
                price_diff = divergence_data['current_close'] - divergence_data['past_close_high']
                rsi_diff = divergence_data['past_rsi_high'] - divergence_data['current_rsi']

            # Aumentar força se as diferenças forem grandes
            if price_diff > 0:
                strength += min(2, int(price_diff / divergence_data['current_close'] * 100))

            if rsi_diff > 0:
                strength += min(2, int(rsi_diff / 10))

            # Verificar se há confirmação de volume (se disponível)
            if 'volume' in data.columns:
                current_volume = data['volume'].iloc[-1]
                avg_volume = data['volume'].iloc[-lookback:-1].mean()

                if current_volume > avg_volume * 1.5:
                    strength += 1

            # Limitar a 10
            return min(10, strength)

        except Exception as e:
            logger.error(f"Erro ao calcular força da divergência: {e}", exc_info=True)
            return 0

    def _confirm_with_volume(
        self,
        data: pd.DataFrame,
        divergence_data: Dict[str, Any],
        lookback: int = 14
    ) -> bool:
        """
        Confirma divergência com volume

        Args:
            data: DataFrame com OHLC
            divergence_data: Dados da divergência
            lookback: Período para análise

        Returns:
            bool: True se confirmado por volume
        """
        if 'volume' not in data.columns:
            return False

        try:
            current_volume = data['volume'].iloc[-1]
            avg_volume = data['volume'].iloc[-lookback:-1].mean()

            # Ajustado threshold para 1.05 (5% acima da média) para volume sintético
            return current_volume > avg_volume * 1.05

        except Exception as e:
            logger.error(f"Erro ao confirmar com volume: {e}", exc_info=True)
            return False

    def _confirm_with_indicators(
        self,
        data: pd.DataFrame,
        rsi: pd.Series,
        divergence_data: Dict[str, Any]
    ) -> bool:
        """
        Confirma divergência com outros indicadores

        Args:
            data: DataFrame com OHLC
            rsi: Série de valores RSI
            divergence_data: Dados da divergência

        Returns:
            bool: True se confirmado por outros indicadores
        """
        try:
            # Verificar se o preço está em níveis de suporte/resistência
            close = data['close'].iloc[-1]

            # Calcular média móvel de 20 períodos
            sma = close.rolling(window=20).mean()

            # Se divergência bullish, verificar se está abaixo da média
            if divergence_data['divergence'] == 'bullish':
                return close < sma.iloc[-1]
            # Se divergência bearish, verificar se está acima da média
            elif divergence_data['divergence'] == 'bearish':
                return close > sma.iloc[-1]

            return False

        except Exception as e:
            logger.error(f"Erro ao confirmar com indicadores: {e}", exc_info=True)
            return False

    def detect_divergence_advanced(
        self,
        data: pd.DataFrame,
        rsi: pd.Series,
        lookback: int = 14
    ) -> Dict[str, Any]:
        """
        Detecção avançada de divergência

        Args:
            data: DataFrame com OHLC
            rsi: Série de valores RSI
            lookback: Período para análise

        Returns:
            Dict com tipo de divergência, força, confirmação
        """
        try:
            # Detectar divergência básica
            basic_divergence = self._detect_divergence(data, rsi, lookback)

            if basic_divergence['divergence'] == 'none':
                return {'divergence': 'none', 'strength': 0}

            # Calcular força da divergência
            strength = self._calculate_divergence_strength(
                data, rsi, basic_divergence, lookback
            )

            # Validar com volume
            volume_confirmation = self._confirm_with_volume(
                data, basic_divergence, lookback
            )

            # Validar com outros indicadores
            indicator_confirmation = self._confirm_with_indicators(
                data, rsi, basic_divergence
            )

            result = {
                'divergence': basic_divergence['divergence'],
                'strength': strength,  # 1-10
                'volume_confirmation': volume_confirmation,
                'indicator_confirmation': indicator_confirmation,
                'details': basic_divergence
            }

            logger.info(
                f"✓ Divergência {basic_divergence['divergence']} detectada | "
                f"Força: {strength}/10 | "
                f"Volume: {'✓' if volume_confirmation else '✗'} | "
                f"Indicadores: {'✓' if indicator_confirmation else '✗'}"
            )

            return result

        except Exception as e:
            logger.error(f"Erro ao detectar divergência avançada: {e}", exc_info=True)
            return {'divergence': 'none', 'strength': 0}

    def _calculate_adx(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calcula ADX (Average Directional Index)

        Args:
            data: DataFrame com OHLC
            period: Período para cálculo (default 14)

        Returns:
            pd.Series: Valores de ADX
        """
        try:
            high = data['high']
            low = data['low']
            close = data['close']

            # Calcular True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # Calcular +DM e -DM
            plus_dm = high.diff()
            minus_dm = low.diff()

            plus_dm = plus_dm.where((plus_dm > 0) & (plus_dm > minus_dm), 0)
            minus_dm = minus_dm.where((minus_dm > 0) & (minus_dm > plus_dm), 0)

            # Calcular médias
            atr = tr.rolling(window=period).mean()
            plus_dm_smooth = plus_dm.rolling(window=period).mean()
            minus_dm_smooth = minus_dm.rolling(window=period).mean()

            # Calcular +DI e -DI
            plus_di = 100 * (plus_dm_smooth / atr)
            minus_di = 100 * (minus_dm_smooth / atr)

            # Calcular DX
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)

            # Calcular ADX
            adx = dx.rolling(window=period).mean()

            return adx

        except Exception as e:
            logger.error(f"Erro ao calcular ADX: {e}", exc_info=True)
            return pd.Series([0] * len(data))

    def confirm_trend(
        self,
        data: pd.DataFrame,
        min_adx: float = 25.0
    ) -> Optional[str]:
        """
        Confirma se há tendência forte

        Args:
            data: DataFrame com OHLC
            min_adx: Mínimo ADX para considerar tendência forte

        Returns:
            'uptrend', 'downtrend', ou None
        """
        try:
            # Calcular ADX
            adx = self._calculate_adx(data)

            if len(adx) == 0:
                return None

            current_adx = adx.iloc[-1]

            # Verificar se há tendência forte
            if current_adx < min_adx:
                logger.debug(f"ADX {current_adx:.2f} < {min_adx}: sem tendência forte")
                return None

            # Determinar direção da tendência
            close = data['close']
            sma_fast = close.rolling(window=20).mean()
            sma_slow = close.rolling(window=50).mean()

            if len(sma_fast) == 0 or len(sma_slow) == 0:
                return None

            if sma_fast.iloc[-1] > sma_slow.iloc[-1]:
                logger.info(f"✓ Tendência de alta detectada (ADX: {current_adx:.2f})")
                return 'uptrend'
            else:
                logger.info(f"✓ Tendência de baixa detectada (ADX: {current_adx:.2f})")
                return 'downtrend'

        except Exception as e:
            logger.error(f"Erro ao confirmar tendência: {e}", exc_info=True)
            return None

    def calculate_confidence(
        self,
        rsi_value: float,
        oversold: float = 30.0,
        overbought: float = 70.0,
        use_confidence_level: bool = False
    ) -> float:
        """
        Calculate confidence based on RSI value distance from thresholds

        Args:
            rsi_value: RSI value
            oversold: Oversold threshold
            overbought: Overbought threshold
            use_confidence_level: Use 80% confidence level calculation

        Returns:
            float: Confidence value (0.0 to 1.0)
        """
        if pd.isna(rsi_value):
            return 0.0

        if rsi_value <= oversold:
            # Closer to 0 = higher confidence
            distance = oversold - rsi_value
            return min(1.0, 0.5 + (distance / oversold) * 0.5)
        elif rsi_value >= overbought:
            # Closer to 100 = higher confidence
            distance = rsi_value - overbought
            return min(1.0, 0.5 + (distance / (100 - overbought)) * 0.5)
        return 0.0

    def calculate_confidence_level(
        self,
        rsi: pd.Series,
        price: pd.Series,
        sample_size: int = 5,
        tolerance: float = 0.05
    ) -> float:
        """
        Calcula nível de confiança baseado em reversões históricas (80% rule)

        Args:
            rsi: Série de valores RSI
            price: Série de preços
            sample_size: Tamanho da amostra (default 5)
            tolerance: Tolerância de 5% para agrupar níveis

        Returns:
            float: Nível de confiança (0.0 a 1.0)
        """
        try:
            # Encontrar pontos de reversão
            reversals = self._find_price_reversals(price, lookback=100)

            if len(reversals) < sample_size:
                return 0.0

            # Pegar últimas N reversões
            recent_reversals = reversals[-sample_size:]

            # Obter valores de RSI nas reversões
            rsi_at_reversals = []
            for idx, _ in recent_reversals:
                if idx < len(rsi):
                    rsi_at_reversals.append(rsi.iloc[idx])

            if len(rsi_at_reversals) < sample_size:
                return 0.0

            # Encontrar nível mais comum
            groups = self._group_by_levels(rsi_at_reversals, tolerance)

            if not groups:
                return 0.0

            # Encontrar nível com mais ocorrências
            max_level = max(groups.keys(), key=lambda k: len(groups[k]))
            max_count = len(groups[max_level])

            # Calcular porcentagem dentro da tolerância
            confidence = max_count / sample_size

            logger.debug(f"Confidence Level: {confidence:.2f} ({max_count}/{sample_size} reversões no nível {max_level:.2f})")
            return confidence

        except Exception as e:
            logger.error(f"Erro ao calcular confidence level: {e}", exc_info=True)
            return 0.0

    def validate_timeframe(self, timeframe_seconds: int) -> bool:
        """
        Valida se o timeframe é adequado para RSI

        Args:
            timeframe_seconds: Timeframe em segundos

        Returns:
            bool: True se timeframe é adequado
        """
        # RSI funciona melhor em H1 (3600s), H4 (14400s), D1 (86400s)
        # Menores timeframes têm muito ruído
        if timeframe_seconds < 3600:
            logger.warning(f"⚠️ RSI não recomendado para timeframe {timeframe_seconds}s (< 1h). Use H1 ou maiores.")
            return False
        return True

    def find_hidden_rsi_levels(
        self,
        data: pd.DataFrame,
        rsi: pd.Series,
        lookback: int = 200
    ) -> List[Dict[str, Any]]:
        """
        Encontra níveis ocultos de RSI

        Args:
            data: DataFrame com OHLC
            rsi: Série de valores RSI
            lookback: Número de períodos para analisar

        Returns:
            Lista de níveis ocultos com estatísticas
        """
        try:
            # Encontrar pontos de reversão de preço
            reversals = self._find_price_reversals(data['close'], lookback)

            if len(reversals) < 10:
                logger.debug(f"Não há reversões suficientes ({len(reversals)}) para encontrar hidden levels")
                return []

            # Separar reversões por tipo
            bottom_reversals = [idx for idx, rtype in reversals if rtype == 'bottom']
            top_reversals = [idx for idx, rtype in reversals if rtype == 'top']

            # Agrupar por níveis
            oversold_groups = self._group_by_levels(
                [rsi.iloc[idx] for idx in bottom_reversals if idx < len(rsi)],
                tolerance=0.05
            )
            overbought_groups = self._group_by_levels(
                [rsi.iloc[idx] for idx in top_reversals if idx < len(rsi)],
                tolerance=0.05
            )

            # Calcular estatísticas para cada nível
            hidden_levels = []

            for level, values in oversold_groups.items():
                if len(values) < 3:
                    continue

                # Calcular taxa de sucesso
                successful = 0
                for idx in bottom_reversals:
                    if idx >= len(data):
                        continue
                    # Verificar se o preço subiu após a reversão
                    if idx + 10 < len(data):
                        if data['close'].iloc[idx + 10] > data['close'].iloc[idx]:
                            successful += 1

                success_rate = successful / len(values) if len(values) > 0 else 0

                if success_rate >= 0.7:  # 70% de sucesso mínimo
                    hidden_levels.append({
                        'level': level,
                        'type': 'support',
                        'count': len(values),
                        'success_rate': success_rate,
                        'avg_rsi': sum(values) / len(values)
                    })

            for level, values in overbought_groups.items():
                if len(values) < 3:
                    continue

                # Calcular taxa de sucesso
                successful = 0
                for idx in top_reversals:
                    if idx >= len(data):
                        continue
                    # Verificar se o preço caiu após a reversão
                    if idx + 10 < len(data):
                        if data['close'].iloc[idx + 10] < data['close'].iloc[idx]:
                            successful += 1

                success_rate = successful / len(values) if len(values) > 0 else 0

                if success_rate >= 0.7:  # 70% de sucesso mínimo
                    hidden_levels.append({
                        'level': level,
                        'type': 'resistance',
                        'count': len(values),
                        'success_rate': success_rate,
                        'avg_rsi': sum(values) / len(values)
                    })

            # Ordenar por taxa de sucesso
            hidden_levels.sort(key=lambda x: x['success_rate'], reverse=True)

            logger.info(f"✓ Encontrados {len(hidden_levels)} níveis ocultos de RSI")
            return hidden_levels

        except Exception as e:
            logger.error(f"Erro ao encontrar hidden levels: {e}")
            return []

    def get_latest_signal(
        self,
        data: pd.DataFrame,
        oversold: float = 30.0,
        overbought: float = 70.0
    ) -> Optional[Dict[str, Any]]:
        """
        Get the latest trading signal

        Args:
            data: DataFrame with OHLC data
            oversold: Oversold threshold
            overbought: Overbought threshold

        Returns:
            Optional[Dict]: Signal information or None
        """
        try:
            if len(data) < self.period:
                return None

            rsi_values = self.calculate(data)
            latest_rsi = rsi_values.iloc[-1]

            signal = self.get_signal(latest_rsi, oversold, overbought)
            confidence = self.calculate_confidence(latest_rsi, oversold, overbought)

            return {
                'indicator': 'RSI',
                'value': latest_rsi,
                'signal': signal,
                'confidence': confidence,
                'oversold': oversold,
                'overbought': overbought
            }

        except Exception as e:
            logger.error(f"Erro ao obter sinal RSI: {e}")
            return None

    def is_oversold(self, rsi_value: float, threshold: float = 30.0) -> bool:
        """Check if RSI indicates oversold condition"""
        return rsi_value <= threshold

    def is_overbought(self, rsi_value: float, threshold: float = 70.0) -> bool:
        """Check if RSI indicates overbought condition"""
        return rsi_value >= threshold

    def get_strength(self, rsi_value: float) -> str:
        """
        Get RSI strength description

        Args:
            rsi_value: RSI value

        Returns:
            str: Strength description
        """
        if rsi_value >= 80:
            return "Strong Overbought"
        elif rsi_value >= 70:
            return "Overbought"
        elif rsi_value >= 55:
            return "Mildly Overbought"
        elif rsi_value <= 20:
            return "Strong Oversold"
        elif rsi_value <= 30:
            return "Oversold"
        elif rsi_value <= 45:
            return "Mildly Oversold"
        else:
            return "Neutral"

    def get_signal(self, rsi_value: float, oversold: float = 30.0, overbought: float = 70.0) -> Optional[str]:
        """
        Get trading signal based on RSI value

        Args:
            rsi_value: RSI value
            oversold: Oversold threshold
            overbought: Overbought threshold

        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if pd.isna(rsi_value):
            return None
        elif rsi_value <= oversold:
            return 'buy'
        elif rsi_value >= overbought:
            return 'sell'
        return None

    def calculate_confidence(self, rsi_value: float, oversold: float = 30.0, overbought: float = 70.0) -> float:
        """
        Calculate confidence based on RSI value distance from thresholds

        Args:
            rsi_value: RSI value
            oversold: Oversold threshold
            overbought: Overbought threshold

        Returns:
            float: Confidence value (0.0 to 1.0)
        """
        if pd.isna(rsi_value):
            return 0.0

        if rsi_value <= oversold:
            # Closer to 0 = higher confidence
            distance = oversold - rsi_value
            return min(1.0, 0.5 + (distance / oversold) * 0.5)
        elif rsi_value >= overbought:
            # Closer to 100 = higher confidence
            distance = rsi_value - overbought
            return min(1.0, 0.5 + (distance / (100 - overbought)) * 0.5)
        return 0.0
