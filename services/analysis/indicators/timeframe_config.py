"""
Configuração de períodos de indicadores baseada em timeframe.
Este módulo fornece valores padrão otimizados para cada indicador
baseado no timeframe de análise selecionado (3s até H4).
"""

from typing import Dict, Any, Optional


# Timeframes suportados em segundos
TIMEFRAMES = {
    '3s': 3,
    '5s': 5,
    '15s': 15,
    '30s': 30,
    '1m': 60,
    '5m': 300,
    '15m': 900,
    '30m': 1800,
    '1h': 3600,
    '4h': 14400,
}

# Configuração de períodos otimizados por timeframe e tipo de indicador
# Valores baseados em análise de mercado para cada timeframe
INDICATOR_PERIODS_BY_TIMEFRAME: Dict[int, Dict[str, Any]] = {
    # === SCALPING (3s - 30s) ===
    3: {
        'rsi': {'period': 7, 'smooth': 1},
        'macd': {'fast_period': 3, 'slow_period': 6, 'signal_period': 2},
        'bollinger_bands': {'period': 10, 'std_dev': 2.0},
        'sma': {'period': 10},
        'ema': {'period': 10},
        'stochastic': {'k_period': 5, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 7},
        'cci': {'period': 10, 'constant': 0.015},
        'roc': {'period': 5},
        'williams_r': {'period': 7},
        'momentum': {'period': 5},
        'adx': {'period': 7, 'di_period': 5},
        'parabolic_sar': {'af': 0.01, 'max_af': 0.1, 'period': 10},
        'supertrend': {'period': 7, 'multiplier': 2.5},
        'donchian_channels': {'period': 10},
        'keltner_channels': {'period': 10, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 7},
        'average_directional_index': {'period': 7},
        'awesome_oscillator': {'fast_period': 3, 'slow_period': 6},
        'klinger_oscillator': {'fast_period': 20, 'slow_period': 45, 'signal_period': 7},
        'force_index': {'period': 7},
        'detrended_price_oscillator': {'period': 7},
        'mass_index': {'period': 7, 'sum_period': 14},
        'true_strength_index': {'r_period': 7, 's_period': 7, 'signal_period': 7},
        'ultimate_oscillator': {'fast_period': 3, 'middle_period': 6, 'slow_period': 9},
        'zonas': {'lookback': 20},
        'fibonacci_retracement': {'lookback': 15},
        'ichimoku_cloud': {'tenkan_period': 3, 'kijun_period': 6, 'senkou_span_b_period': 12, 'displacement': 6},
    },
    
    5: {
        'rsi': {'period': 9, 'smooth': 1},
        'macd': {'fast_period': 4, 'slow_period': 9, 'signal_period': 3},
        'bollinger_bands': {'period': 12, 'std_dev': 2.0},
        'sma': {'period': 12},
        'ema': {'period': 12},
        'stochastic': {'k_period': 7, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 9},
        'cci': {'period': 12, 'constant': 0.015},
        'roc': {'period': 7},
        'williams_r': {'period': 9},
        'momentum': {'period': 7},
        'adx': {'period': 9, 'di_period': 7},
        'parabolic_sar': {'af': 0.01, 'max_af': 0.1, 'period': 12},
        'supertrend': {'period': 9, 'multiplier': 2.5},
        'donchian_channels': {'period': 12},
        'keltner_channels': {'period': 12, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 9},
        'average_directional_index': {'period': 9},
        'awesome_oscillator': {'fast_period': 4, 'slow_period': 9},
        'klinger_oscillator': {'fast_period': 25, 'slow_period': 55, 'signal_period': 9},
        'force_index': {'period': 9},
        'detrended_price_oscillator': {'period': 9},
        'mass_index': {'period': 9, 'sum_period': 18},
        'true_strength_index': {'r_period': 9, 's_period': 9, 'signal_period': 9},
        'ultimate_oscillator': {'fast_period': 4, 'middle_period': 9, 'slow_period': 14},
        'zonas': {'lookback': 25},
        'fibonacci_retracement': {'lookback': 20},
        'ichimoku_cloud': {'tenkan_period': 4, 'kijun_period': 9, 'senkou_span_b_period': 18, 'displacement': 9},
    },
    
    15: {
        'rsi': {'period': 10, 'smooth': 1},
        'macd': {'fast_period': 5, 'slow_period': 12, 'signal_period': 4},
        'bollinger_bands': {'period': 15, 'std_dev': 2.0},
        'sma': {'period': 15},
        'ema': {'period': 15},
        'stochastic': {'k_period': 8, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 10},
        'cci': {'period': 15, 'constant': 0.015},
        'roc': {'period': 8},
        'williams_r': {'period': 10},
        'momentum': {'period': 8},
        'adx': {'period': 10, 'di_period': 8},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 15},
        'supertrend': {'period': 10, 'multiplier': 3.0},
        'donchian_channels': {'period': 15},
        'keltner_channels': {'period': 15, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 10},
        'average_directional_index': {'period': 10},
        'awesome_oscillator': {'fast_period': 5, 'slow_period': 12},
        'klinger_oscillator': {'fast_period': 30, 'slow_period': 65, 'signal_period': 10},
        'force_index': {'period': 10},
        'detrended_price_oscillator': {'period': 10},
        'mass_index': {'period': 10, 'sum_period': 20},
        'true_strength_index': {'r_period': 10, 's_period': 10, 'signal_period': 10},
        'ultimate_oscillator': {'fast_period': 5, 'middle_period': 10, 'slow_period': 15},
        'zonas': {'lookback': 30},
        'fibonacci_retracement': {'lookback': 25},
        'ichimoku_cloud': {'tenkan_period': 5, 'kijun_period': 12, 'senkou_span_b_period': 24, 'displacement': 12},
    },
    
    30: {
        'rsi': {'period': 12, 'smooth': 1},
        'macd': {'fast_period': 6, 'slow_period': 14, 'signal_period': 5},
        'bollinger_bands': {'period': 18, 'std_dev': 2.0},
        'sma': {'period': 18},
        'ema': {'period': 18},
        'stochastic': {'k_period': 9, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 12},
        'cci': {'period': 18, 'constant': 0.015},
        'roc': {'period': 9},
        'williams_r': {'period': 12},
        'momentum': {'period': 9},
        'adx': {'period': 12, 'di_period': 9},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 18},
        'supertrend': {'period': 12, 'multiplier': 3.0},
        'donchian_channels': {'period': 18},
        'keltner_channels': {'period': 18, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 12},
        'average_directional_index': {'period': 12},
        'awesome_oscillator': {'fast_period': 6, 'slow_period': 14},
        'klinger_oscillator': {'fast_period': 35, 'slow_period': 75, 'signal_period': 12},
        'force_index': {'period': 12},
        'detrended_price_oscillator': {'period': 12},
        'mass_index': {'period': 12, 'sum_period': 24},
        'true_strength_index': {'r_period': 12, 's_period': 12, 'signal_period': 12},
        'ultimate_oscillator': {'fast_period': 6, 'middle_period': 12, 'slow_period': 18},
        'zonas': {'lookback': 35},
        'fibonacci_retracement': {'lookback': 30},
        'ichimoku_cloud': {'tenkan_period': 6, 'kijun_period': 14, 'senkou_span_b_period': 28, 'displacement': 14},
    },
    
    # === DAY TRADING (1m - 30m) ===
    60: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 7, 'slow_period': 16, 'signal_period': 5},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 10, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 7, 'slow_period': 16},
        'klinger_oscillator': {'fast_period': 40, 'slow_period': 85, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 21},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 35},
        'ichimoku_cloud': {'tenkan_period': 7, 'kijun_period': 16, 'senkou_span_b_period': 32, 'displacement': 16},
    },
    
    300: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 14, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 12, 'slow_period': 26},
        'klinger_oscillator': {'fast_period': 55, 'slow_period': 110, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 28},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 40},
        'ichimoku_cloud': {'tenkan_period': 12, 'kijun_period': 26, 'senkou_span_b_period': 52, 'displacement': 26},
    },
    
    900: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 14, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 12, 'slow_period': 26},
        'klinger_oscillator': {'fast_period': 55, 'slow_period': 110, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 28},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 45},
        'ichimoku_cloud': {'tenkan_period': 12, 'kijun_period': 26, 'senkou_span_b_period': 52, 'displacement': 26},
    },
    
    1800: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 14, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 12, 'slow_period': 26},
        'klinger_oscillator': {'fast_period': 55, 'slow_period': 110, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 28},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 50},
        'ichimoku_cloud': {'tenkan_period': 12, 'kijun_period': 26, 'senkou_span_b_period': 52, 'displacement': 26},
    },
    
    # === SWING TRADING (1h - 4h) ===
    3600: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 14, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 12, 'slow_period': 26},
        'klinger_oscillator': {'fast_period': 55, 'slow_period': 110, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 28},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 50},
        'ichimoku_cloud': {'tenkan_period': 12, 'kijun_period': 26, 'senkou_span_b_period': 52, 'displacement': 26},
    },
    
    14400: {
        'rsi': {'period': 14, 'smooth': 1},
        'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
        'bollinger_bands': {'period': 20, 'std_dev': 2.0},
        'sma': {'period': 20},
        'ema': {'period': 20},
        'stochastic': {'k_period': 14, 'd_period': 3, 'smooth': 1},
        'atr': {'period': 14},
        'cci': {'period': 20, 'constant': 0.015},
        'roc': {'period': 10},
        'williams_r': {'period': 14},
        'momentum': {'period': 10},
        'adx': {'period': 14, 'di_period': 10},
        'parabolic_sar': {'af': 0.02, 'max_af': 0.2, 'period': 20},
        'supertrend': {'period': 14, 'multiplier': 3.0},
        'donchian_channels': {'period': 20},
        'keltner_channels': {'period': 20, 'atr_multiplier': 2.0},
        'money_flow_index': {'period': 14},
        'average_directional_index': {'period': 14},
        'awesome_oscillator': {'fast_period': 12, 'slow_period': 26},
        'klinger_oscillator': {'fast_period': 55, 'slow_period': 110, 'signal_period': 14},
        'force_index': {'period': 14},
        'detrended_price_oscillator': {'period': 14},
        'mass_index': {'period': 14, 'sum_period': 28},
        'true_strength_index': {'r_period': 14, 's_period': 14, 'signal_period': 14},
        'ultimate_oscillator': {'fast_period': 7, 'middle_period': 14, 'slow_period': 28},
        'zonas': {'lookback': 50},
        'fibonacci_retracement': {'lookback': 50},
        'ichimoku_cloud': {'tenkan_period': 12, 'kijun_period': 26, 'senkou_span_b_period': 52, 'displacement': 26},
    },
}


def get_indicator_params_for_timeframe(indicator_type: str, timeframe_seconds: int, 
                                        custom_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna os parâmetros otimizados para um indicador baseado no timeframe.
    
    Args:
        indicator_type: Tipo do indicador (rsi, macd, etc.)
        timeframe_seconds: Timeframe em segundos
        custom_params: Parâmetros customizados que sobrescrevem os padrões
        
    Returns:
        Dict com parâmetros otimizados para o timeframe
    """
    # Normalizar timeframe para o mais próximo disponível
    available_timeframes = sorted(INDICATOR_PERIODS_BY_TIMEFRAME.keys())
    closest_timeframe = min(available_timeframes, key=lambda x: abs(x - timeframe_seconds))
    
    # Obter configuração para o timeframe
    timeframe_config = INDICATOR_PERIODS_BY_TIMEFRAME.get(closest_timeframe, {})
    
    # Obter parâmetros para o indicador específico
    indicator_params = timeframe_config.get(indicator_type.lower(), {})
    
    # Se não houver configuração específica, usar valores padrão genéricos
    if not indicator_params:
        # Valores padrão de fallback para timeframe 5s
        if timeframe_seconds <= 5:
            indicator_params = {'period': 9}
        elif timeframe_seconds <= 15:
            indicator_params = {'period': 10}
        elif timeframe_seconds <= 60:
            indicator_params = {'period': 14}
        else:
            indicator_params = {'period': 20}
    
    # Mesclar com parâmetros customizados (se houver)
    if custom_params:
        indicator_params = {**indicator_params, **custom_params}
    
    return indicator_params


def calculate_min_rows_for_indicator(indicator_type: str, timeframe_seconds: int, 
                                     indicator_params: Optional[Dict[str, Any]] = None) -> int:
    """
    Calcula o número mínimo de candles necessários para um indicador.
    
    Args:
        indicator_type: Tipo do indicador
        timeframe_seconds: Timeframe em segundos
        indicator_params: Parâmetros do indicador
        
    Returns:
        int: Número mínimo de candles necessários
    """
    # Obter parâmetros otimizados se não fornecidos
    if indicator_params is None:
        indicator_params = get_indicator_params_for_timeframe(indicator_type, timeframe_seconds)
    
    # Mapeamento de tipos para cálculo de períodos
    min_rows_map = {
        'macd': lambda p: max(
            p.get('slow_period', 26),
            p.get('fast_period', 12) + p.get('signal_period', 9)
        ),
        'ichimoku_cloud': lambda p: max(
            p.get('senkou_span_b_period', 52),
            p.get('kijun_period', 26),
            p.get('tenkan_period', 12)
        ) + p.get('displacement', 26),
        'fibonacci_retracement': lambda p: p.get('lookback', 50),
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
        'adx': lambda p: p.get('period', 14) * 2,
        'average_directional_index': lambda p: p.get('period', 14) * 2,
        'parabolic_sar': lambda p: p.get('period', 20),
        'zonas': lambda p: p.get('lookback', 50),
        'supertrend': lambda p: p.get('period', 14),
        'donchian_channels': lambda p: p.get('period', 20),
        'keltner_channels': lambda p: p.get('period', 20),
        'heiken_ashi': lambda p: 5,
        'pivot_points': lambda p: 5,
        'money_flow_index': lambda p: p.get('period', 14),
        'awesome_oscillator': lambda p: p.get('slow_period', 26),
        'klinger_oscillator': lambda p: p.get('slow_period', 110),
        'force_index': lambda p: p.get('period', 14),
        'detrended_price_oscillator': lambda p: p.get('period', 14),
        'mass_index': lambda p: p.get('period', 14),
        'true_strength_index': lambda p: max(p.get('r_period', 14), p.get('s_period', 14)),
        'ultimate_oscillator': lambda p: p.get('slow_period', 28),
    }
    
    # Obter função de cálculo para o indicador
    min_rows_func = min_rows_map.get(indicator_type.lower())
    
    if min_rows_func:
        try:
            return min_rows_func(indicator_params)
        except Exception:
            pass
    
    # Fallback: usar período genérico ou 20
    return indicator_params.get('period', 20)


def adjust_params_for_timeframe(indicator_type: str, base_params: Dict[str, Any], 
                                timeframe_seconds: int) -> Dict[str, Any]:
    """
    Ajusta parâmetros de indicador para um timeframe específico.
    Útil quando se quer ajustar parâmetros já definidos.
    
    Args:
        indicator_type: Tipo do indicador
        base_params: Parâmetros base do indicador
        timeframe_seconds: Timeframe em segundos
        
    Returns:
        Dict com parâmetros ajustados
    """
    # Obter parâmetros otimizados para o timeframe
    optimized_params = get_indicator_params_for_timeframe(indicator_type, timeframe_seconds)
    
    # Mesclar: base_params sobrescreve otimizados, exceto se for None
    result = {**optimized_params}
    for key, value in base_params.items():
        if value is not None:
            result[key] = value
    
    return result


# Lista de todos os indicadores suportados com seus parâmetros
ALL_INDICATORS = [
    'rsi', 'macd', 'bollinger_bands', 'sma', 'ema', 'stochastic', 
    'atr', 'cci', 'roc', 'williams_r', 'momentum', 'adx',
    'parabolic_sar', 'supertrend', 'donchian_channels', 'keltner_channels',
    'money_flow_index', 'average_directional_index', 'awesome_oscillator',
    'klinger_oscillator', 'force_index', 'detrended_price_oscillator',
    'mass_index', 'true_strength_index', 'ultimate_oscillator',
    'zonas', 'fibonacci_retracement', 'ichimoku_cloud', 'heiken_ashi',
    'pivot_points', 'vwap', 'obv'
]
