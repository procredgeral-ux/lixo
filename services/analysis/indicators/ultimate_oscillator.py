"""Ultimate Oscillator indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class UltimateOscillator(TechnicalIndicator):
    """Ultimate Oscillator - multi-timeframe momentum indicator"""

    def __init__(self, short_period: int = 7, medium_period: int = 14, long_period: int = 28):
        """
        Initialize Ultimate Oscillator
        
        Args:
            short_period: Short timeframe period (default: 7)
            medium_period: Medium timeframe period (default: 14)
            long_period: Long timeframe period (default: 28)
        """
        super().__init__("UltimateOscillator")
        self.short_period = short_period
        self.medium_period = medium_period
        self.long_period = long_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Ultimate Oscillator parameters"""
        short = kwargs.get('short_period', self.short_period)
        medium = kwargs.get('medium_period', self.medium_period)
        long = kwargs.get('long_period', self.long_period)
        return (
            isinstance(short, int) and short > 0 and
            isinstance(medium, int) and medium > 0 and
            isinstance(long, int) and long > 0 and
            short < medium < long
        )

    def _calculate_bp_tr(self, data: pd.DataFrame) -> tuple:
        """Calculate Buying Pressure and True Range"""
        close = data['close']
        low = data['low']
        high = data['high']
        
        # Buying Pressure = Close - True Low
        # True Low = Minimum of current low or previous close
        prev_close = close.shift(1)
        true_low = pd.concat([low, prev_close], axis=1).min(axis=1)
        buying_pressure = close - true_low
        
        # True Range = True High - True Low
        # True High = Maximum of current high or previous close
        true_high = pd.concat([high, prev_close], axis=1).max(axis=1)
        true_range = true_high - true_low
        
        return buying_pressure, true_range

    @cached_indicator("UltimateOscillator")
    @handle_indicator_errors("UltimateOscillator", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Ultimate Oscillator values
        
        Args:
            data: DataFrame with OHLC data
            
        Returns:
            pd.Series: Ultimate Oscillator values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close'], min_rows=self.long_period)
        
        buying_pressure, true_range = self._calculate_bp_tr(data)
        
        # Calculate averages for each timeframe
        # Short period
        bp_short = buying_pressure.rolling(window=self.short_period).sum()
        tr_short = true_range.rolling(window=self.short_period).sum()
        avg_short = bp_short / tr_short
        
        # Medium period
        bp_medium = buying_pressure.rolling(window=self.medium_period).sum()
        tr_medium = true_range.rolling(window=self.medium_period).sum()
        avg_medium = bp_medium / tr_medium
        
        # Long period
        bp_long = buying_pressure.rolling(window=self.long_period).sum()
        tr_long = true_range.rolling(window=self.long_period).sum()
        avg_long = bp_long / tr_long
        
        # Ultimate Oscillator = 100 * [(4 * avg_short) + (2 * avg_medium) + avg_long] / 7
        uo = 100 * ((4 * avg_short) + (2 * avg_medium) + avg_long) / 7
        uo = uo.replace([np.inf, -np.inf], 50).fillna(50)
        
        return uo

    def get_signal(self, value: float, oversold: float = 30.0, overbought: float = 70.0) -> Optional[str]:
        """
        Get trading signal based on Ultimate Oscillator level
        
        Args:
            value: Current UO value
            oversold: Oversold threshold (default: 30)
            overbought: Overbought threshold (default: 70)
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if value <= oversold:
            return 'buy'
        elif value >= overbought:
            return 'sell'
        return None
