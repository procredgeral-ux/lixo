"""Custom strategy that supports dynamic indicator-based analysis"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from functools import wraps
import pandas as pd
import numpy as np
from loguru import logger

from models import Candle, Signal, SignalType
from services.strategies.base import BaseStrategy
from services.strategies.confluence import ConfluenceCalculator, SignalDirection
from services.user_logger import user_logger


class CustomStrategy(BaseStrategy):
    """Custom strategy that dynamically uses selected indicators"""

    def __init__(
        self,
        name: str,
        strategy_type: str,
        account_id: str,
        parameters: Dict[str, Any],
        assets: List[str],
        indicators: Optional[List[Dict[str, Any]]] = None,
        user_name: str = None,
        strategy_display_name: str = None
    ):
        super().__init__(name, strategy_type, account_id, parameters, assets)
        self.indicators = indicators or []
        self.user_name = user_name or "Unknown"
        self.strategy_display_name = strategy_display_name or name
        
        # Extract strategy-level parameters
        self.min_confidence = parameters.get('min_confidence', 0.5)
        self.required_signals = parameters.get('required_signals', 1)
        self.timeframe = parameters.get('timeframe', 60)  # Default 1 minute

        # Initialize confluence calculator - valores ajustados para permitir mais trades
        min_confluence = parameters.get('min_confluence', 0.5)  # Reduzido de 0.6 para 0.5
        require_trend_confirmation = parameters.get('require_trend_confirmation', False)
        self.confluence_calculator = ConfluenceCalculator(
            min_confluence=min_confluence,
            require_trend_confirmation=require_trend_confirmation
        )
        
        # Map indicator types to their implementations
        self.indicator_cache: Dict[str, Any] = {}

    async def analyze(self, candles: List[Candle], symbol: str = "Unknown") -> Optional[Signal]:
        """
        Analyze candles using selected indicators and generate signal

        Args:
            candles: List of candles to analyze
            symbol: Asset symbol being analyzed

        Returns:
            Optional[Signal]: Generated signal or None
        """
        if len(candles) < 20:
            return None

        if not self.indicators:
            logger.warning("⚠️ Nenhum indicador configurado para esta estratégia!")
            return None

        # Convert candles to DataFrame for easier processing
        df = pd.DataFrame([{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume if hasattr(c, 'volume') else None
        } for c in candles])

        # Adicionar volume sintético se não existir
        if 'volume' not in df.columns or df['volume'].isna().all():
            try:
                from services.analysis.indicators.synthetic_volume import add_synthetic_volume
                df = add_synthetic_volume(df, price_column='close')
                logger.debug(f"✓ Volume sintético adicionado ao DataFrame ({len(df)} candles)")
            except Exception as e:
                logger.warning(f"⚠️ Não foi possível adicionar volume sintético: {e}")

        # Calculate signals from each indicator
        indicator_signals = []
        indicator_details: List[Dict[str, Any]] = []
        
        # Contadores para log consolidado
        total_indicators = len(self.indicators)
        analyzed_count = 0
        signals_generated = 0
        
        for indicator_info in self.indicators:
            indicator_type = indicator_info.get('type')
            indicator_params = indicator_info.get('parameters', {})
            # Fix: converter JSON string para dict se necessário
            if isinstance(indicator_params, str):
                try:
                    import json
                    indicator_params = json.loads(indicator_params)
                except:
                    indicator_params = {}
            indicator_name = indicator_info.get('name')
            
            # Log individual removido - será consolidado no final
            
            signal_data = await self._analyze_indicator(
                indicator_type,
                indicator_params,
                indicator_name,
                df,
                candles,
                symbol
            )
            
            analyzed_count += 1
            
            if signal_data:
                signal, details = signal_data
                # Log individual removido - será consolidado no final
                indicator_signals.append(signal)
                indicator_details.append(details)
                signals_generated += 1
            else:
                # SILENCIADO no console - não logar indicadores sem sinal
                pass

        # Log consolidado no final da análise
        if analyzed_count > 0:
            logger.debug(f"🔍 [USUÁRIO: {self.user_name}] [ATIVO: {symbol}] Análise concluída: {analyzed_count} indicadores analisados, {signals_generated} sinais gerados")
        
        # Combine signals using confluence calculator
        if not indicator_signals:
            return None

        # Prepare signals for confluence calculator
        confluence_signals = []
        for signal, details in zip(indicator_signals, indicator_details):
            signal_direction = None
            if signal.signal_type == SignalType.BUY:
                signal_direction = SignalDirection.BUY
            elif signal.signal_type == SignalType.SELL:
                signal_direction = SignalDirection.SELL
            
            if signal_direction:
                confluence_signals.append({
                    'direction': signal_direction,
                    'confidence': signal.confidence,
                    'indicator_type': details.get('type', 'unknown'),
                    'divergence': details.get('divergence', 'none')
                })

        # Calculate confluence using improved system
        confluence_result = self.confluence_calculator.calculate_confluence(confluence_signals)
        
        # DEBUG: Log do resultado do confluence - SILENCIADO
        # logger.debug(f"📊 [CONFLUENCE] direction={confluence_result.get('direction')}, score={confluence_result.get('weighted_score'):.4f}")
        
        # Log detalhado do confluence no arquivo do usuário - DESABILITADO
        # (já está silenciado no user_logger)
        
        # Check if signal should be generated
        if not self.confluence_calculator.should_generate_signal(confluence_result, df):
            # SILENCIADO: não logar sinais bloqueados no console
            logger.debug(f"🚫 [CONFLUENCE] Sinal bloqueado - {confluence_result.get('direction')}")
            return None
        
        # EXTRA SAFETY: Nunca gere sinal se direction for HOLD
        if confluence_result['direction'] == SignalDirection.HOLD:
            logger.error(f"🚫 [CONFLUENCE SAFETY] HOLD detectado após should_generate_signal! Bloqueando.")
            return None

        # Determine signal type from confluence result
        if confluence_result['direction'] == SignalDirection.BUY:
            combined_signal_type = SignalType.BUY
        elif confluence_result['direction'] == SignalDirection.SELL:
            combined_signal_type = SignalType.SELL
        else:
            return None

        # Calculate combined confidence
        combined_confidence = confluence_result['weighted_score']
        confluence_score = confluence_result['confluence_score']

        # Create combined signal with confluence information
        signal = Signal(
            signal_type=combined_signal_type,
            confidence=combined_confidence,
            price=candles[-1].close,
            indicators=indicator_details,
            confluence=confluence_score
        )

        return signal

    async def _analyze_indicator(
        self,
        indicator_type: str,
        indicator_params: Dict[str, Any],
        indicator_name: Optional[str],
        df: pd.DataFrame,
        candles: List[Candle],
        symbol: str = "Unknown"
    ) -> Optional[Tuple[Signal, Dict[str, Any]]]:
        """
        Analyze using a specific indicator

        Args:
            indicator_type: Type of indicator (rsi, macd, etc.)
            indicator_params: Parameters for the indicator
            indicator_name: Display name for the indicator
            df: DataFrame with candle data
            candles: List of Candle objects
            symbol: Asset symbol being analyzed

        Returns:
            Optional[Tuple[Signal, Dict[str, Any]]]: Generated signal and indicator details or None
        """
        try:
            # Import indicator implementation dynamically
            indicator_class = await self._load_indicator(indicator_type)
            
            if not indicator_class:
                logger.warning(f"Could not load indicator: {indicator_type}")
                return None

            # Calculate minimum rows required based on indicator parameters
            min_rows_required = self._get_min_rows_for_indicator(indicator_type, indicator_params)
            
            # Check if we have enough data
            if len(df) < min_rows_required:
                logger.warning(
                    f"⚠️ [USUÁRIO: {self.user_name}] [ATIVO: {symbol}] [{indicator_type}] Dados insuficientes: {len(df)} rows, mínimo {min_rows_required} necessário"
                )
                return None

            # Pass only parameters accepted by the indicator's __init__
            # Get the __init__ signature to filter parameters
            import inspect
            init_params = inspect.signature(indicator_class.__init__).parameters
            valid_params = {
                k: v for k, v in indicator_params.items()
                if k in init_params and k != 'self'
            }
            
            # Create indicator instance with filtered parameters
            indicator = indicator_class(**valid_params)
            
            # Calculate indicator values
            values = indicator.calculate(df)
            
            if values is None:
                logger.warning(f"⚠️ [USUÁRIO: {self.user_name}] [ATIVO: {symbol}] [{indicator_type}] Cálculo retornou None")
                return None
            
            # Log values info - COMPLETAMENTE SILENCIADO
            # Não logar informações individuais de indicadores
            
            # Generate signal based on indicator values
            result = self._generate_signal_from_indicator(
                indicator_type,
                indicator_name,
                indicator_params,
                values,
                df,
                candles,
                symbol
            )
            
            if result is None:
                # SILENCIADO: não logar no console
                pass
            
            return result

        except Exception as e:
            logger.error(f"[ATIVO: {symbol}] Error analyzing indicator {indicator_type}: {e}", exc_info=True)
            return None

    def _get_min_rows_for_indicator(self, indicator_type: str, indicator_params: Dict[str, Any]) -> int:
        """
        Calculate minimum rows required for an indicator based on its parameters.
        
        Args:
            indicator_type: Type of indicator
            indicator_params: Parameters for the indicator
            
        Returns:
            int: Minimum number of rows required
        """
        indicator_type = indicator_type.lower()
        
        # Default minimum rows
        default_min = 20
        
        # Define minimum rows based on indicator type and parameters
        min_rows_map = {
            'macd': lambda p: max(
                p.get('slow_period', 7),
                p.get('fast_period', 3) + p.get('signal_period', 3)
            ),
            'ichimoku_cloud': lambda p: max(
                p.get('senkou_span_b_period', 14),
                p.get('kijun_period', 7),
                p.get('tenkan_period', 3)
            ),
            'fibonacci_retracement': lambda p: p.get('lookback', 35),
            'bollinger_bands': lambda p: p.get('period', 20),
            'rsi': lambda p: p.get('period', 14),
            'sma': lambda p: p.get('period', 20),
            'ema': lambda p: p.get('period', 20),
            'stochastic': lambda p: max(p.get('k_period', 14), p.get('d_period', 3)),
            'atr': lambda p: p.get('period', 14),
            'cci': lambda p: p.get('period', 20),
            'roc': lambda p: p.get('period', 10),
            'williams_r': lambda p: p.get('period', 14),
            'momentum': lambda p: p.get('period', 10),
            'adx': lambda p: p.get('period', 14) * 2,  # ADX needs more data
            'parabolic_sar': lambda p: 10,  # Minimum for Parabolic SAR
            'zonas': lambda p: p.get('lookback', 50),
            'supertrend': lambda p: p.get('period', 10),
            'donchian_channels': lambda p: p.get('period', 20),
            'keltner_channels': lambda p: p.get('period', 20),
            'heiken_ashi': lambda p: 5,
            'pivot_points': lambda p: 5,
            'money_flow_index': lambda p: p.get('period', 14),
            'average_directional_index': lambda p: p.get('period', 14) * 2,
        }
        
        # Get the minimum rows function for this indicator type
        min_rows_func = min_rows_map.get(indicator_type)
        
        if min_rows_func:
            try:
                return min_rows_func(indicator_params)
            except Exception:
                pass
        
        return default_min

    async def _load_indicator(self, indicator_type: str) -> Optional[Any]:
        """
        Dynamically load indicator implementation

        Args:
            indicator_type: Type of indicator (rsi, macd, etc.)

        Returns:
            Indicator class or None
        """
        # Check cache first
        if indicator_type in self.indicator_cache:
            return self.indicator_cache[indicator_type]

        try:
            # Map indicator types to their module paths
            indicator_map = {
                'rsi': 'services.analysis.indicators.rsi.RSI',
                'macd': 'services.analysis.indicators.macd.MACD',
                'bollinger_bands': 'services.analysis.indicators.bollinger.BollingerBands',
                'sma': 'services.analysis.indicators.sma.SMA',
                'ema': 'services.analysis.indicators.ema.EMA',
                'stochastic': 'services.analysis.indicators.stochastic.Stochastic',
                'atr': 'services.analysis.indicators.atr.ATR',
                'cci': 'services.analysis.indicators.cci.CCI',
                'roc': 'services.analysis.indicators.roc.ROC',
                'williams_r': 'services.analysis.indicators.williams_r.WilliamsR',
                'zonas': 'services.analysis.indicators.zonas.Zonas',
                'momentum': 'services.analysis.indicators.momentum.Momentum',
                'adx': 'services.analysis.indicators.adx.ADX',
                # Novos indicadores
                'parabolic_sar': 'services.analysis.indicators.parabolic_sar.ParabolicSAR',
                'ichimoku_cloud': 'services.analysis.indicators.ichimoku_cloud.IchimokuCloud',
                'money_flow_index': 'services.analysis.indicators.money_flow_index.MoneyFlowIndex',
                'average_directional_index': 'services.analysis.indicators.average_directional_index.AverageDirectionalIndex',
                'keltner_channels': 'services.analysis.indicators.keltner_channels.KeltnerChannels',
                'donchian_channels': 'services.analysis.indicators.donchian_channels.DonchianChannels',
                'heiken_ashi': 'services.analysis.indicators.heiken_ashi.HeikenAshi',
                'pivot_points': 'services.analysis.indicators.pivot_points.PivotPoints',
                'supertrend': 'services.analysis.indicators.supertrend.Supertrend',
                'fibonacci_retracement': 'services.analysis.indicators.fibonacci_retracement.FibonacciRetracement',
                'vwap': 'services.analysis.indicators.vwap.VWAP',
                'obv': 'services.analysis.indicators.obv.OBV',
            }

            module_path = indicator_map.get(indicator_type)
            if not module_path:
                logger.warning(f"Unknown indicator type: {indicator_type}")
                return None

            # Import dynamically
            parts = module_path.split('.')
            module_name = '.'.join(parts[:-1])
            class_name = parts[-1]

            module = __import__(module_name, fromlist=[class_name])
            indicator_class = getattr(module, class_name)

            # Cache the class
            self.indicator_cache[indicator_type] = indicator_class

            return indicator_class

        except Exception as e:
            logger.error(f"Failed to load indicator {indicator_type}: {e}", exc_info=True)
            return None

    def _generate_oscillator_signal(
        self,
        indicator_type: str,
        current_value: float,
        previous_value: float,
        oversold: float,
        overbought: float,
        candles: List[Candle],
        indicator_params: Dict[str, Any],
        scale_factor: float = 100.0
    ) -> Optional[Tuple[Signal, Dict[str, Any]]]:
        """
        Generate signal for oscillator indicators (RSI, CCI, ROC, Williams %R)

        Args:
            indicator_type: Type of indicator
            current_value: Current indicator value
            previous_value: Previous indicator value
            oversold: Oversold threshold
            overbought: Overbought threshold
            candles: List of Candle objects
            indicator_params: Indicator parameters
            scale_factor: Factor to scale distance calculation (default 100)

        Returns:
            Signal and details or None
        """
        if current_value < oversold:
            confidence = max(self.min_confidence, 0.7 + (oversold - current_value) / scale_factor * 0.3)
            signal = Signal(
                signal_type=SignalType.BUY,
                confidence=confidence,
                price=candles[-1].close
            )
            result = {
                f"{indicator_type}_value": current_value,
                f"{indicator_type}_previous": previous_value,
                "oversold": oversold,
                "overbought": overbought,
                "distance_from_oversold": oversold - current_value,
                "distance_from_overbought": overbought - current_value,
            }
            return signal, result
        elif current_value > overbought:
            confidence = max(self.min_confidence, 0.7 + (current_value - overbought) / scale_factor * 0.3)
            signal = Signal(
                signal_type=SignalType.SELL,
                confidence=confidence,
                price=candles[-1].close
            )
            result = {
                f"{indicator_type}_value": current_value,
                f"{indicator_type}_previous": previous_value,
                "oversold": oversold,
                "overbought": overbought,
                "distance_from_oversold": oversold - current_value,
                "distance_from_overbought": overbought - current_value,
            }
            return signal, result
        else:
            return None

    def _generate_signal_from_indicator(
        self,
        indicator_type: str,
        indicator_name: Optional[str],
        indicator_params: Dict[str, Any],
        values: Any,
        df: pd.DataFrame,
        candles: List[Candle],
        symbol: str = "Unknown"
    ) -> Optional[Tuple[Signal, Dict[str, Any]]]:
        """
        Generate signal based on indicator values

        Args:
            indicator_type: Type of indicator
            indicator_name: Display name for the indicator
            indicator_params: Parameters for the indicator
            values: Indicator values (can be Series, DataFrame, or tuple)
            df: DataFrame with candle data
            candles: List of Candle objects
            symbol: Asset symbol being analyzed

        Returns:
            Optional[Signal]: Generated signal or None
        """
        try:
            indicator_type = (indicator_type or "").strip().lower()
            indicator_label = indicator_name or indicator_type
            indicator_params = indicator_params or {}

            def _build_details(signal: Signal, value: Optional[float], result: Dict[str, Any]) -> Tuple[Signal, Dict[str, Any]]:
                details: Dict[str, Any] = {
                    "type": indicator_type,
                    "name": indicator_label,
                    "signal": signal.signal_type.value,
                    "confidence": signal.confidence,
                    "parameters": indicator_params,
                    "result": result,
                    "divergence": result.get('divergence', 'none') if isinstance(result, dict) else 'none',
                    "symbol": symbol
                }
                if value is not None:
                    details["value"] = value
                return signal, details
            if indicator_type == 'zonas':
                # "Zonas" indicator returns a DataFrame with multiple support/resistance fields
                # The indicator returns a DataFrame where each column is a Series of values for each candle
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None

                # Get the last row (last candle's data) - this is a Series with column names as index
                last_row = values.iloc[-1]
                price = candles[-1].close

                def _valid(value):
                    try:
                        if value is None:
                            return False
                        if hasattr(value, 'item'):  # Handle numpy types
                            value = value.item()
                        if pd.isna(value) or value == float('nan') or value == float('inf') or value == -float('inf'):
                            return False
                        return True
                    except Exception as e:
                        logger.warning(f"Error in _valid({value!r}): {e}")
                        return False

                def _to_float(value):
                    """Convert value to float, unwrapping nested containers when needed."""
                    if value is None:
                        return None

                    import numpy as np

                    try:
                        # Unwrap pandas Series iteratively
                        while isinstance(value, pd.Series):
                            if value.empty:
                                return None
                            value = value.iloc[-1]

                        # Unwrap pandas DataFrame (take last row/column)
                        if isinstance(value, pd.DataFrame):
                            if value.empty:
                                return None
                            value = value.iloc[-1]
                            if isinstance(value, pd.Series):
                                if value.empty:
                                    return None
                                value = value.iloc[-1]

                        # Unwrap numpy arrays / lists / tuples (take last element)
                        if isinstance(value, (list, tuple, np.ndarray)):
                            if len(value) == 0:
                                return None
                            value = value[-1]

                        # Unwrap numpy scalar types
                        if isinstance(value, np.ndarray):
                            value = value.item() if value.size == 1 else value.reshape(-1)[-1]

                        # Use item() when available (e.g., numpy scalar)
                        if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
                            try:
                                value = value.item()
                            except (TypeError, ValueError):
                                pass

                        if value is None:
                            return None

                        if isinstance(value, (np.integer, np.floating)):
                            return float(value)

                        return float(value)
                    except (TypeError, ValueError, IndexError) as exc:
                        return None

                # Access values from last_row (which is a Series with column names as index)
                try:
                    # Safely extract values
                    def safe_get(row, key, default=None):
                        try:
                            value = row.get(key, default)
                            if value is not None and hasattr(value, 'item'):
                                value = value.item()
                            return value
                        except Exception as e:
                            return default

                    def safe_to_float(value, key):
                        """Convert value to float safely"""
                        if value is None:
                            return None

                        converted = _to_float(value)
                        return converted

                    # Extract all values first
                    raw_support_low = safe_get(last_row, 'support_low')
                    raw_support_high = safe_get(last_row, 'support_high')
                    raw_support_strength = safe_get(last_row, 'support_strength')
                    raw_resistance_low = safe_get(last_row, 'resistance_low')
                    raw_resistance_high = safe_get(last_row, 'resistance_high')
                    raw_resistance_strength = safe_get(last_row, 'resistance_strength')

                    # Convert all values to float
                    support_low = safe_to_float(raw_support_low, 'support_low')
                    support_high = safe_to_float(raw_support_high, 'support_high')
                    support_strength = safe_to_float(raw_support_strength, 'support_strength')
                    resistance_low = safe_to_float(raw_resistance_low, 'resistance_low')
                    resistance_high = safe_to_float(raw_resistance_high, 'resistance_high')
                    resistance_strength = safe_to_float(raw_resistance_strength, 'resistance_strength')

                    # Set default values if None
                    support_strength = support_strength if support_strength is not None else 0.0
                    resistance_strength = resistance_strength if resistance_strength is not None else 0.0
                except Exception as e:
                    logger.warning(f"Error extracting values from zonas indicator: {e}", exc_info=True)
                    return None

                tolerance = price * 0.001  # 0.1% tolerance around the zone bounds

                if _valid(support_low) and _valid(support_high):
                    if price >= support_low - tolerance and price <= support_high + tolerance:
                        # Convert support_strength to float before calculation
                        strength_value = _to_float(support_strength)
                        if strength_value is None:
                            strength_value = 0.0
                        confidence = max(
                            self.min_confidence,
                            min(1.0, 0.5 + (strength_value / 100.0) * 0.5)
                        )
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=confidence,
                            price=price
                        )
                        result = {
                            "price": price,
                            "support_low": support_low,
                            "support_high": support_high,
                            "support_strength": support_strength,
                            "tolerance": tolerance,
                            "zone": "support",
                        }
                        return _build_details(signal, price, result)

                if _valid(resistance_low) and _valid(resistance_high):
                    if price <= resistance_high + tolerance and price >= resistance_low - tolerance:
                        # Convert resistance_strength to float before calculation
                        strength_value = _to_float(resistance_strength)
                        if strength_value is None:
                            strength_value = 0.0
                        confidence = max(
                            self.min_confidence,
                            min(1.0, 0.5 + (strength_value / 100.0) * 0.5)
                        )
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=confidence,
                            price=price
                        )
                        result = {
                            "price": price,
                            "resistance_low": resistance_low,
                            "resistance_high": resistance_high,
                            "resistance_strength": resistance_strength,
                            "tolerance": tolerance,
                            "zone": "resistance",
                        }
                        return _build_details(signal, price, result)

                # No signal from zonas
                return None

            # Handle tuple returns (like bollinger_bands, macd)
            macd_line = None
            signal_line = None
            histogram = None
            upper_band = None
            middle_band = None
            lower_band = None
            last_k_value = None
            last_d_value = None
            previous_k_value = None
            previous_d_value = None

            if isinstance(values, tuple):
                # For bollinger_bands, use the middle band
                if indicator_type == 'bollinger_bands':
                    upper_band, middle_band, lower_band = values
                    if len(middle_band) < 2:
                        logger.warning(f"[ATIVO: {symbol}] Bollinger Bands: insuficiente dados")
                        return None
                    current_value = float(middle_band.iloc[-1])
                    previous_value = float(middle_band.iloc[-2])
                # For macd, use the first element (macd line)
                elif indicator_type == 'macd':
                    macd_line = values[0]
                    signal_line = values[1] if len(values) > 1 else None
                    histogram = values[2] if len(values) > 2 else None
                    if macd_line is None or len(macd_line) < 2:
                        logger.warning(f"[ATIVO: {symbol}] MACD: insuficiente dados ou valor None")
                        return None
                    current_value = float(macd_line.iloc[-1])
                    previous_value = float(macd_line.iloc[-2])
                else:
                    # For other tuple returns, use the first element
                    current_value = float(values[0].iloc[-1]) if hasattr(values[0], 'iloc') else values[0]
                    previous_value = float(values[0].iloc[-2]) if hasattr(values[0], 'iloc') and len(values[0]) > 1 else current_value
            elif indicator_type == 'stochastic':
                # Stochastic returns DataFrame with %K and %D columns
                # Use %K for signal generation
                if not isinstance(values, pd.DataFrame) or values.empty or '%K' not in values.columns or len(values) == 0:
                    logger.warning(f"[ATIVO: {symbol}] Stochastic indicator returned invalid data")
                    return None
                k_values = values['%K']
                if len(k_values) < 2:
                    logger.warning(f"[ATIVO: {symbol}] Stochastic %K column insuficiente dados")
                    return None
                last_k_value = k_values.iloc[-1]
                if pd.isna(last_k_value):
                    logger.warning(f"[ATIVO: {symbol}] Stochastic %K value is NaN")
                    return None
                current_value = float(last_k_value)
                previous_value = float(k_values.iloc[-2]) if not pd.isna(k_values.iloc[-2]) else current_value
                last_k_value = current_value
                previous_k_value = previous_value
                if '%D' in values.columns and len(values['%D']) > 0:
                    last_d_value = float(values['%D'].iloc[-1])
                    previous_d_value = float(values['%D'].iloc[-2]) if len(values['%D']) > 1 else last_d_value
            else:
                if not isinstance(values, (pd.Series, pd.DataFrame)) or len(values) < 2:
                    logger.warning(f"[ATIVO: {symbol}] {indicator_type}: insuficiente dados")
                    return None
                
                # Se for um DataFrame com múltiplas colunas, extrair a coluna principal
                if isinstance(values, pd.DataFrame) and len(values.columns) > 1:
                    # Para novos indicadores que retornam DataFrames, usar a coluna principal
                    # Tentar identificar a coluna principal comum
                    signal_columns = ['signal', 'trend', 'supertrend', 'upper_band', 'lower_band', 'middle_band', 'close', 'open', 'high', 'low']
                    # Também verificar colunas com prefixos (ex: ha_close, ha_open)
                    prefixed_columns = ['ha_close', 'ha_open', 'ha_high', 'ha_low', 'pp', 'r1', 's1', 'upper', 'lower']
                    primary_col = None
                    for col in values.columns:
                        if col in signal_columns or col in prefixed_columns:
                            primary_col = col
                            break
                    if primary_col is None:
                        primary_col = values.columns[0]  # Usar primeira coluna se não encontrar
                    
                    current_value = float(values[primary_col].iloc[-1])
                    previous_value = float(values[primary_col].iloc[-2])
                else:
                    current_value = float(values.iloc[-1])
                    previous_value = float(values.iloc[-2])

            # Simple signal generation logic
            # This can be extended with more sophisticated logic

            if indicator_type == 'cci':
                overbought = indicator_params.get('overbought', 100)
                oversold = indicator_params.get('oversold', -100)

                signal_result = self._generate_oscillator_signal(
                    indicator_type='cci',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=200.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)
                
                # Sinal flexível: CCI > 0 = momento bullish
                if current_value > 0 and current_value < overbought:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"cci": current_value, "condition": "positive_momentum"}
                    return _build_details(signal, current_value, result)
                
                # Sinal SELL: CCI < 0 = momento bearish
                if current_value < 0 and current_value > oversold:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"cci": current_value, "condition": "negative_momentum"}
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'roc':
                overbought = indicator_params.get('overbought', 2)
                oversold = indicator_params.get('oversold', -2)

                signal_result = self._generate_oscillator_signal(
                    indicator_type='roc',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=4.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)
                
                # Sinal flexível: ROC > 0 = momentum positivo
                if current_value > 0:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"roc": current_value, "condition": "positive_roc"}
                    return _build_details(signal, current_value, result)
                
                # Sinal SELL: ROC < 0 = momentum negativo
                if current_value < 0:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"roc": current_value, "condition": "negative_roc"}
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'williams_r':
                overbought = indicator_params.get('overbought', -20)
                oversold = indicator_params.get('oversold', -80)

                signal_result = self._generate_oscillator_signal(
                    indicator_type='williams_r',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=60.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'rsi':
                overbought = indicator_params.get('overbought', 70)
                oversold = indicator_params.get('oversold', 30)
                
                signal_result = self._generate_oscillator_signal(
                    indicator_type='rsi',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=100.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)
                
                # Sinal flexível: RSI > 50 = momento bullish
                if current_value > 50 and current_value < overbought:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {
                        "rsi": current_value,
                        "condition": "bullish_momentum"
                    }
                    return _build_details(signal, current_value, result)
                
                # Sinal SELL: RSI < 50 = momento bearish
                if current_value < 50 and current_value > oversold:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {
                        "rsi": current_value,
                        "condition": "bearish_momentum"
                    }
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'macd':
                # MACD crossover logic
                if current_value > 0 and previous_value < 0:
                    signal_line_value = float(signal_line.iloc[-1]) if signal_line is not None and len(signal_line) > 0 else None
                    histogram_value = float(histogram.iloc[-1]) if histogram is not None and len(histogram) > 0 else None
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.75,
                        price=candles[-1].close
                    )
                    result = {
                        "macd_line": current_value,
                        "macd_previous": previous_value,
                        "signal_line": signal_line_value,
                        "signal_previous": float(signal_line.iloc[-2]) if signal_line is not None and len(signal_line) > 1 else None,
                        "histogram": histogram_value,
                        "histogram_previous": float(histogram.iloc[-2]) if histogram is not None and len(histogram) > 1 else None,
                    }
                    return _build_details(signal, current_value, result)
                elif current_value < 0 and previous_value > 0:
                    signal_line_value = float(signal_line.iloc[-1]) if signal_line is not None and len(signal_line) > 0 else None
                    histogram_value = float(histogram.iloc[-1]) if histogram is not None and len(histogram) > 0 else None
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.75,
                        price=candles[-1].close
                    )
                    result = {
                        "macd_line": current_value,
                        "macd_previous": previous_value,
                        "signal_line": signal_line_value,
                        "signal_previous": float(signal_line.iloc[-2]) if signal_line is not None and len(signal_line) > 1 else None,
                        "histogram": histogram_value,
                        "histogram_previous": float(histogram.iloc[-2]) if histogram is not None and len(histogram) > 1 else None,
                    }
                    return _build_details(signal, current_value, result)
                
                # Sinal de tendência: MACD positivo = BUY, negativo = SELL
                if current_value > 0 and histogram is not None and len(histogram) > 0:
                    hist_val = float(histogram.iloc[-1])
                    if hist_val > 0:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.65,
                            price=candles[-1].close
                        )
                        result = {
                            "macd_line": current_value,
                            "histogram": hist_val,
                            "condition": "bullish_trend"
                        }
                        return _build_details(signal, current_value, result)
                elif current_value < 0 and histogram is not None and len(histogram) > 0:
                    hist_val = float(histogram.iloc[-1])
                    if hist_val < 0:
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=0.65,
                            price=candles[-1].close
                        )
                        result = {
                            "macd_line": current_value,
                            "histogram": hist_val,
                            "condition": "bearish_trend"
                        }
                        return _build_details(signal, current_value, result)

            elif indicator_type in ['sma', 'ema']:
                # Moving average crossover with price
                if len(candles) < 2:
                    logger.warning(f"[ATIVO: {symbol}] Moving Average: insuficiente candles")
                    return None
                price = candles[-1].close
                previous_price = candles[-2].close
                if price > current_value and previous_price < previous_value:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.7,
                        price=price
                    )
                    result = {
                        "ma_value": current_value,
                        "ma_previous": previous_value,
                        "price": price,
                        "previous_price": previous_price,
                        "cross_above": True,
                    }
                    return _build_details(signal, current_value, result)
                elif price < current_value and previous_price > previous_value:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.7,
                        price=price
                    )
                    result = {
                        "ma_value": current_value,
                        "ma_previous": previous_value,
                        "price": price,
                        "previous_price": previous_price,
                        "cross_below": True,
                    }
                    return _build_details(signal, current_value, result)
                
                # Sinal de tendência: preço acima da média = BUY, abaixo = SELL
                if price > current_value:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=price
                    )
                    result = {
                        "ma_value": current_value,
                        "price": price,
                        "condition": "price_above_ma"
                    }
                    return _build_details(signal, current_value, result)
                elif price < current_value:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=price
                    )
                    result = {
                        "ma_value": current_value,
                        "price": price,
                        "condition": "price_below_ma"
                    }
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'stochastic':
                k_period = indicator_params.get('k_period', 14)
                overbought = indicator_params.get('overbought', 80)
                oversold = indicator_params.get('oversold', 20)
                
                if current_value < oversold:
                    confidence = max(self.min_confidence, 0.7 + (oversold - current_value) / 100 * 0.3)
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=confidence,
                        price=candles[-1].close
                    )
                    result = {
                        "k_line": last_k_value,
                        "k_previous": previous_k_value,
                        "d_line": last_d_value,
                        "d_previous": previous_d_value,
                        "oversold": oversold,
                        "overbought": overbought,
                        "k_period": k_period,
                    }
                    return _build_details(signal, current_value, result)
                elif current_value > overbought:
                    confidence = max(self.min_confidence, 0.7 + (current_value - overbought) / 100 * 0.3)
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=confidence,
                        price=candles[-1].close
                    )
                    result = {
                        "k_line": last_k_value,
                        "k_previous": previous_k_value,
                        "d_line": last_d_value,
                        "d_previous": previous_d_value,
                        "oversold": oversold,
                        "overbought": overbought,
                        "k_period": k_period,
                    }
                    return _build_details(signal, current_value, result)
                
                # Sinal flexível: K-line > D-line = BUY, K < D = SELL
                if last_k_value > last_d_value:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {
                        "k_line": last_k_value,
                        "d_line": last_d_value,
                        "condition": "k_above_d"
                    }
                    return _build_details(signal, current_value, result)
                else:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {
                        "k_line": last_k_value,
                        "d_line": last_d_value,
                        "condition": "k_below_d"
                    }
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'bollinger_bands':
                # Bollinger Bands breakout
                std_dev = indicator_params.get('std_dev', 2)
                period = indicator_params.get('period', 20)
                
                # Usar valores já calculados pelo indicador
                current_upper = upper_band.iloc[-1]
                current_lower = lower_band.iloc[-1]
                current_middle = middle_band.iloc[-1]
                price = candles[-1].close
                
                if price > current_upper:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.8,
                        price=price
                    )
                    result = {
                        "upper_band": float(current_upper),
                        "lower_band": float(current_lower),
                        "middle_band": float(current_middle),
                        "price": price,
                        "std_dev": std_dev,
                        "bandwidth": float(current_upper - current_lower),
                    }
                    return _build_details(signal, float(current_upper), result)
                elif price < current_lower:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.8,
                        price=price
                    )
                    result = {
                        "upper_band": float(current_upper),
                        "lower_band": float(current_lower),
                        "middle_band": float(current_middle),
                        "price": price,
                        "std_dev": std_dev,
                        "bandwidth": float(current_upper - current_lower),
                    }
                    return _build_details(signal, float(current_lower), result)
                
                # Sinal flexível: preço abaixo da média = BUY, acima = SELL
                if pd.notna(current_middle):
                    if price < current_middle:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.6,
                            price=price
                        )
                        result = {
                            "price": price,
                            "middle": float(current_middle),
                            "lower": float(current_lower) if pd.notna(current_lower) else None,
                            "condition": "below_middle_band"
                        }
                        return _build_details(signal, current_value, result)
                    else:
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=0.6,
                            price=price
                        )
                        result = {
                            "price": price,
                            "middle": float(current_middle),
                            "upper": float(current_upper) if pd.notna(current_upper) else None,
                            "condition": "above_middle_band"
                        }
                        return _build_details(signal, current_value, result)

            elif indicator_type == 'parabolic_sar':
                # Parabolic SAR: sinal quando SAR cruza preço
                if len(candles) < 2:
                    return None
                price = candles[-1].close
                previous_price = candles[-2].close
                
                # SAR value está em current_value (último valor da série)
                sar_value = current_value
                previous_sar = previous_value
                
                # SAR abaixo do preço = tendência de alta (BUY)
                # SAR acima do preço = tendência de baixa (SELL)
                if previous_sar > previous_price and sar_value < price:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.75,
                        price=price
                    )
                    result = {"sar_value": sar_value, "sar_previous": previous_sar, "price": price, "trend_change": "up"}
                    return _build_details(signal, sar_value, result)
                elif previous_sar < previous_price and sar_value > price:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.75,
                        price=price
                    )
                    result = {"sar_value": sar_value, "sar_previous": previous_sar, "price": price, "trend_change": "down"}
                    return _build_details(signal, sar_value, result)
                
                # Sinal flexível: SAR abaixo do preço = BUY, acima = SELL
                if sar_value < price:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=price
                    )
                    result = {"sar_value": sar_value, "price": price, "condition": "sar_below_price"}
                    return _build_details(signal, sar_value, result)
                else:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=price
                    )
                    result = {"sar_value": sar_value, "price": price, "condition": "sar_above_price"}
                    return _build_details(signal, sar_value, result)

            elif indicator_type == 'ichimoku_cloud':
                # Ichimoku: sinal quando preço cruza a nuvem ou Tenkan cruza Kijun
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None
                
                price = candles[-1].close
                tenkan = values.get('tenkan_sen', pd.Series([None])).iloc[-1]
                kijun = values.get('kijun_sen', pd.Series([None])).iloc[-1]
                senkou_a = values.get('senkou_span_a', pd.Series([None])).iloc[-1]
                senkou_b = values.get('senkou_span_b', pd.Series([None])).iloc[-1]
                
                if pd.isna(tenkan) or pd.isna(kijun):
                    return None
                
                # Tenkan cruza Kijun para cima = BUY
                # Tenkan cruza Kijun para baixo = SELL
                tenkan_prev = values.get('tenkan_sen', pd.Series([None])).iloc[-2] if len(values) > 1 else None
                kijun_prev = values.get('kijun_sen', pd.Series([None])).iloc[-2] if len(values) > 1 else None
                
                if pd.notna(tenkan_prev) and pd.notna(kijun_prev):
                    if tenkan_prev < kijun_prev and tenkan > kijun:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.7,
                            price=price
                        )
                        result = {"tenkan": float(tenkan), "kijun": float(kijun), "cross": "tenkan_above_kijun"}
                        return _build_details(signal, float(tenkan), result)
                    elif tenkan_prev > kijun_prev and tenkan < kijun:
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=0.7,
                            price=price
                        )
                        result = {"tenkan": float(tenkan), "kijun": float(kijun), "cross": "tenkan_below_kijun"}
                        return _build_details(signal, float(tenkan), result)
                
                # Sinal flexível: Tenkan > Kijun = BUY, Tenkan < Kijun = SELL
                if tenkan > kijun:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=price
                    )
                    result = {"tenkan": float(tenkan), "kijun": float(kijun), "condition": "tenkan_above_kijun"}
                    return _build_details(signal, float(tenkan), result)
                else:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=price
                    )
                    result = {"tenkan": float(tenkan), "kijun": float(kijun), "condition": "tenkan_below_kijun"}
                    return _build_details(signal, float(tenkan), result)

            elif indicator_type == 'money_flow_index':
                # MFI: oscilador similar ao RSI mas com volume
                overbought = indicator_params.get('overbought', 80)
                oversold = indicator_params.get('oversold', 20)
                
                signal_result = self._generate_oscillator_signal(
                    indicator_type='money_flow_index',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=100.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)
                
                # Sinal flexível: MFI > 50 = pressão compradora
                if current_value > 50:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"mfi": current_value, "condition": "bullish_pressure"}
                    return _build_details(signal, current_value, result)
                
                # Sinal SELL: MFI < 50 = pressão vendedora
                if current_value < 50:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"mfi": current_value, "condition": "bearish_pressure"}
                    return _build_details(signal, current_value, result)

            elif indicator_type in ['average_directional_index', 'adx']:
                # ADX: força da tendência - sinal quando ADX > 25 (tendência forte)
                adx_threshold = indicator_params.get('adx_threshold', 25)
                
                # Sinal flexível: qualquer valor de ADX > 10 gera sinal
                if current_value > 10:
                    # Tentar obter direção dos DI lines
                    plus_di = None
                    minus_di = None
                    if isinstance(values, pd.DataFrame):
                        plus_di = values['plus_di'].iloc[-1] if 'plus_di' in values.columns else None
                        minus_di = values['minus_di'].iloc[-1] if 'minus_di' in values.columns else None
                    
                    # Se temos DI lines, usar para direção
                    if plus_di is not None and minus_di is not None and pd.notna(plus_di) and pd.notna(minus_di):
                        if plus_di > minus_di:
                            signal_type = SignalType.BUY
                        else:
                            signal_type = SignalType.SELL
                    else:
                        # Sem DI lines, assumir BUY como padrão quando ADX está ativo
                        signal_type = SignalType.BUY
                    
                    confidence = min(0.85, 0.55 + (current_value - 10) / 50 * 0.3)
                    signal = Signal(
                        signal_type=signal_type,
                        confidence=confidence,
                        price=candles[-1].close
                    )
                    result = {
                        "adx": current_value,
                        "plus_di": float(plus_di) if plus_di is not None and pd.notna(plus_di) else None,
                        "minus_di": float(minus_di) if minus_di is not None and pd.notna(minus_di) else None,
                        "condition": "trend_strength"
                    }
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'keltner_channels':
                # Keltner: similar a Bollinger mas com ATR
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None
                
                price = candles[-1].close
                upper = values.get('upper', pd.Series([None])).iloc[-1]
                lower = values.get('lower', pd.Series([None])).iloc[-1]
                middle = values.get('middle', pd.Series([None])).iloc[-1]
                
                if pd.isna(upper) or pd.isna(lower):
                    return None
                
                if price > float(upper):
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.75,
                        price=price
                    )
                    result = {"upper": float(upper), "lower": float(lower), "middle": float(middle) if pd.notna(middle) else None}
                    return _build_details(signal, float(upper), result)
                elif price < float(lower):
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.75,
                        price=price
                    )
                    result = {"upper": float(upper), "lower": float(lower), "middle": float(middle) if pd.notna(middle) else None}
                    return _build_details(signal, float(lower), result)
                
                # Sinal flexível: preço abaixo da média = possível reversão para cima
                if pd.notna(middle) and price < float(middle):
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=price
                    )
                    result = {"price": price, "middle": float(middle), "lower": float(lower), "condition": "below_middle"}
                    return _build_details(signal, current_value, result)
                
                # Sinal SELL: preço acima da média = possível reversão para baixo
                if pd.notna(middle) and price > float(middle):
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=price
                    )
                    result = {"price": price, "middle": float(middle), "upper": float(upper), "condition": "above_middle"}
                    return _build_details(signal, current_value, result)

            elif indicator_type == 'donchian_channels':
                # Donchian: breakout das bandas
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None
                
                price = candles[-1].close
                upper = values.get('upper', pd.Series([None])).iloc[-1]
                lower = values.get('lower', pd.Series([None])).iloc[-1]
                middle = values.get('middle', pd.Series([None])).iloc[-1]
                
                if pd.isna(upper) or pd.isna(lower):
                    return None
                
                if price > float(upper):
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.75,
                        price=price
                    )
                    result = {"upper": float(upper), "lower": float(lower), "middle": float(middle) if pd.notna(middle) else None, "breakout": "upper"}
                    return _build_details(signal, float(upper), result)
                elif price < float(lower):
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.75,
                        price=price
                    )
                    result = {"upper": float(upper), "lower": float(lower), "middle": float(middle) if pd.notna(middle) else None, "breakout": "lower"}
                    return _build_details(signal, float(lower), result)
                
                # Sinal padrão: gerar BUY se preço está na metade inferior do canal
                if pd.notna(middle) and pd.notna(lower):
                    channel_range = float(upper) - float(lower)
                    if channel_range > 0:
                        position = (price - float(lower)) / channel_range
                        if position < 0.5:  # 50% inferior do canal = BUY
                            signal = Signal(
                                signal_type=SignalType.BUY,
                                confidence=0.6,
                                price=price
                            )
                            result = {"price": price, "position": position, "condition": "lower_channel"}
                            return _build_details(signal, current_value, result)
                        else:  # 50% superior do canal = SELL
                            signal = Signal(
                                signal_type=SignalType.SELL,
                                confidence=0.6,
                                price=price
                            )
                            result = {"price": price, "position": position, "condition": "upper_channel"}
                            return _build_details(signal, current_value, result)

            elif indicator_type == 'heiken_ashi':
                # Heiken Ashi: candle de reversão
                if not isinstance(values, pd.DataFrame) or values.empty or len(values) < 2:
                    return None
                
                last = values.iloc[-1]
                prev = values.iloc[-2]
                
                # Heiken Ashi retorna colunas com prefixo 'ha_'
                ha_close = last.get('ha_close') or last.get('close')
                ha_open = last.get('ha_open') or last.get('open')
                prev_close = prev.get('ha_close') or prev.get('close')
                prev_open = prev.get('ha_open') or prev.get('open')
                
                if pd.isna(ha_close) or pd.isna(ha_open) or pd.isna(prev_close) or pd.isna(prev_open):
                    return None
                
                # Candle verde (close > open) após candle vermelho = BUY
                # Candle vermelho (close < open) após candle verde = SELL
                if prev_close < prev_open and ha_close > ha_open:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.7,
                        price=candles[-1].close
                    )
                    result = {"ha_close": float(ha_close), "ha_open": float(ha_open), "pattern": "green_after_red"}
                    return _build_details(signal, float(ha_close), result)
                elif prev_close > prev_open and ha_close < ha_open:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.7,
                        price=candles[-1].close
                    )
                    result = {"ha_close": float(ha_close), "ha_open": float(ha_open), "pattern": "red_after_green"}
                    return _build_details(signal, float(ha_close), result)
                
                # Sinal flexível: candle verde atual = BUY, vermelho = SELL
                if ha_close > ha_open:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"ha_close": float(ha_close), "ha_open": float(ha_open), "pattern": "green_candle"}
                    return _build_details(signal, float(ha_close), result)
                else:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=candles[-1].close
                    )
                    result = {"ha_close": float(ha_close), "ha_open": float(ha_open), "pattern": "red_candle"}
                    return _build_details(signal, float(ha_close), result)

            elif indicator_type == 'pivot_points':
                # Pivot Points: preço próximo a níveis de suporte/resistência
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None
                
                price = candles[-1].close
                # Pivot Points retorna 'pp' não 'pivot'
                pivot = values.get('pp', pd.Series([None])).iloc[-1]
                r1 = values.get('r1', pd.Series([None])).iloc[-1]
                s1 = values.get('s1', pd.Series([None])).iloc[-1]
                
                if pd.isna(pivot):
                    return None
                
                tolerance = price * 0.002  # 0.2% de tolerância
                
                # Próximo a suporte = BUY
                if pd.notna(s1) and abs(price - float(s1)) < tolerance:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.7,
                        price=price
                    )
                    result = {"pivot": float(pivot), "s1": float(s1), "r1": float(r1) if pd.notna(r1) else None, "level": "support"}
                    return _build_details(signal, float(s1), result)
                # Próximo a resistência = SELL
                elif pd.notna(r1) and abs(price - float(r1)) < tolerance:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.7,
                        price=price
                    )
                    result = {"pivot": float(pivot), "s1": float(s1) if pd.notna(s1) else None, "r1": float(r1), "level": "resistance"}
                    return _build_details(signal, float(r1), result)

            elif indicator_type == 'supertrend':
                # Supertrend: sinal quando muda de direção
                if not isinstance(values, pd.DataFrame) or values.empty or len(values) < 2:
                    return None
                
                price = candles[-1].close
                trend = values.get('trend', pd.Series([None])).iloc[-1]
                prev_trend = values.get('trend', pd.Series([None])).iloc[-2] if len(values) > 1 else None
                
                if pd.isna(trend):
                    return None
                
                # Tendência muda de -1 (down) para 1 (up) = BUY
                # Tendência muda de 1 (up) para -1 (down) = SELL
                if prev_trend is not None and pd.notna(prev_trend):
                    if prev_trend < 0 and trend > 0:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.75,
                            price=price
                        )
                        result = {"trend": int(trend), "previous_trend": int(prev_trend), "change": "to_bullish"}
                        return _build_details(signal, price, result)
                    elif prev_trend > 0 and trend < 0:
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=0.75,
                            price=price
                        )
                        result = {"trend": int(trend), "previous_trend": int(prev_trend), "change": "to_bearish"}
                        return _build_details(signal, price, result)
                
                # Sinal flexível: tendência bullish atual (trend = 1) = BUY, bearish (trend = -1) = SELL
                if trend > 0:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.6,
                        price=price
                    )
                    result = {"trend": int(trend), "condition": "bullish_trend"}
                    return _build_details(signal, price, result)
                else:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.6,
                        price=price
                    )
                    result = {"trend": int(trend), "condition": "bearish_trend"}
                    return _build_details(signal, price, result)

            elif indicator_type == 'fibonacci_retracement':
                # Fibonacci: preço próximo a níveis de 38.2%, 50%, 61.8%
                if not isinstance(values, pd.DataFrame) or values.empty:
                    return None
                
                price = candles[-1].close
                level_382 = values.get('level_382', pd.Series([None])).iloc[-1]
                level_500 = values.get('level_500', pd.Series([None])).iloc[-1]
                level_618 = values.get('level_618', pd.Series([None])).iloc[-1]
                
                tolerance = price * 0.002
                
                # Verificar se preço está próximo a algum nível importante
                levels = [
                    (level_382, "38.2%", level_618 if pd.notna(level_618) else None),
                    (level_500, "50%", level_382 if pd.notna(level_382) else level_618 if pd.notna(level_618) else None),
                    (level_618, "61.8%", level_382 if pd.notna(level_382) else None)
                ]
                
                for level_val, level_name, opposite_level in levels:
                    if pd.notna(level_val) and abs(price - float(level_val)) < tolerance:
                        # Determinar direção baseado no nível anterior
                        if opposite_level is not None and pd.notna(opposite_level):
                            if price > float(opposite_level):
                                # Preço subiu até este nível = possível reversão para baixo
                                signal_type = SignalType.SELL
                            else:
                                # Preço desceu até este nível = possível reversão para cima
                                signal_type = SignalType.BUY
                        else:
                            signal_type = SignalType.BUY  # Default
                        
                        signal = Signal(
                            signal_type=signal_type,
                            confidence=0.7,
                            price=price
                        )
                        result = {"level": level_name, "level_value": float(level_val), "price": price}
                        return _build_details(signal, float(level_val), result)
                
                # Sinal flexível: preço entre 38.2% e 61.8% (zona de compra/venda)
                if pd.notna(level_382) and pd.notna(level_618):
                    fib_range = float(level_618) - float(level_382)
                    if fib_range > 0:
                        position_in_range = (price - float(level_382)) / fib_range
                        if position_in_range < 0.4:  # Zona inferior = BUY
                            signal = Signal(
                                signal_type=SignalType.BUY,
                                confidence=0.6,
                                price=price
                            )
                            result = {
                                "price": price,
                                "level_382": float(level_382),
                                "level_618": float(level_618),
                                "position": position_in_range,
                                "condition": "lower_fib_zone"
                            }
                            return _build_details(signal, current_value, result)
                        elif position_in_range > 0.6:  # Zona superior = SELL
                            signal = Signal(
                                signal_type=SignalType.SELL,
                                confidence=0.6,
                                price=price
                            )
                            result = {
                                "price": price,
                                "level_382": float(level_382),
                                "level_618": float(level_618),
                                "position": position_in_range,
                                "condition": "upper_fib_zone"
                            }
                            return _build_details(signal, current_value, result)

            elif indicator_type == 'momentum':
                # Momentum: sinal de oscilador mas também com lógica de tendência
                overbought = indicator_params.get('overbought', 2)
                oversold = indicator_params.get('oversold', -2)
                
                # Primeiro tentar sinal de oscilador (oversold/overbought)
                signal_result = self._generate_oscillator_signal(
                    indicator_type='momentum',
                    current_value=current_value,
                    previous_value=previous_value,
                    oversold=oversold,
                    overbought=overbought,
                    candles=candles,
                    indicator_params=indicator_params,
                    scale_factor=4.0
                )
                if signal_result:
                    signal, result = signal_result
                    return _build_details(signal, current_value, result)
                
                # Se não houver sinal de oscilador, usar cruzamento de zero
                # Momentum cruzando de negativo para positivo = BUY
                # Momentum cruzando de positivo para negativo = SELL
                if previous_value < 0 and current_value > 0:
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        confidence=0.7,
                        price=candles[-1].close
                    )
                    result = {
                        "momentum": current_value,
                        "momentum_prev": previous_value,
                        "cross": "zero_up",
                        "overbought": overbought,
                        "oversold": oversold
                    }
                    return _build_details(signal, current_value, result)
                elif previous_value > 0 and current_value < 0:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        confidence=0.7,
                        price=candles[-1].close
                    )
                    result = {
                        "momentum": current_value,
                        "momentum_prev": previous_value,
                        "cross": "zero_down",
                        "overbought": overbought,
                        "oversold": oversold
                    }
                    return _build_details(signal, current_value, result)
                
                # Sinal de continuação de tendência
                # Se momentum está consistentemente positivo/negativo
                if len(values) >= 3:
                    recent_values = values.iloc[-3:]
                    if all(v > 0 for v in recent_values if pd.notna(v)):
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.6,
                            price=candles[-1].close
                        )
                        result = {
                            "momentum": current_value,
                            "condition": "positive_momentum",
                            "overbought": overbought,
                            "oversold": oversold
                        }
                        return _build_details(signal, current_value, result)
                    elif all(v < 0 for v in recent_values if pd.notna(v)):
                        signal = Signal(
                            signal_type=SignalType.SELL,
                            confidence=0.6,
                            price=candles[-1].close
                        )
                        result = {
                            "momentum": current_value,
                            "condition": "negative_momentum",
                            "overbought": overbought,
                            "oversold": oversold
                        }
                        return _build_details(signal, current_value, result)

            elif indicator_type == 'atr':
                # ATR: sinal baseado na mudança de volatilidade
                if len(values) < 5:
                    return None
                
                current_atr = current_value
                prev_atr = previous_value
                price = candles[-1].close
                
                # Calcular média móvel do ATR
                atr_sma = values.iloc[-5:].mean()
                
                # Sinal flexível baseado na volatilidade atual
                if pd.notna(atr_sma) and atr_sma > 0:
                    atr_ratio = current_atr / atr_sma
                    
                    # ATR acima da média com aumento recente = possível movimento
                    if current_atr > atr_sma and prev_atr <= atr_sma:
                        price_change = candles[-1].close - candles[-2].close if len(candles) >= 2 else 0
                        signal_type = SignalType.BUY if price_change >= 0 else SignalType.SELL
                        
                        signal = Signal(
                            signal_type=signal_type,
                            confidence=0.65,
                            price=price
                        )
                        result = {
                            "atr": current_atr,
                            "atr_sma": float(atr_sma),
                            "ratio": float(atr_ratio),
                            "condition": "volatility_spike"
                        }
                        return _build_details(signal, current_value, result)
                    
                    # ATR muito baixo = possível acumulação (sinal de compra para breakout)
                    if atr_ratio < 0.6:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.6,
                            price=price
                        )
                        result = {
                            "atr": current_atr,
                            "atr_ratio": float(atr_ratio),
                            "condition": "low_volatility_accumulation"
                        }
                        return _build_details(signal, current_value, result)
                    
                    # Sinal padrão: qualquer volatilidade média gera sinal BUY
                    if 0.6 <= atr_ratio <= 2.0:
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            confidence=0.55,
                            price=price
                        )
                        result = {
                            "atr": current_atr,
                            "atr_sma": float(atr_sma),
                            "ratio": float(atr_ratio),
                            "condition": "normal_volatility"
                        }
                        return _build_details(signal, current_value, result)

            # Add more indicator types as needed
            # ...

            return None

        except Exception as e:
            logger.error(f"[ATIVO: {symbol}] Error generating signal from {indicator_type}: {e}", exc_info=True)
            return None

    def validate_parameters(self) -> bool:
        """Validate strategy parameters"""
        # Validate min_confidence
        if not 0 <= self.min_confidence <= 1:
            return False
        
        # Validate required_signals
        if self.required_signals < 1:
            return False
        
        # Validate timeframe
        if self.timeframe < 1:
            return False
        
        return True
