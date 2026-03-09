"""True Strength Index (TSI) indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class TrueStrengthIndex(TechnicalIndicator):
    """True Strength Index - momentum oscillator with double smoothing"""

    def __init__(self, long_period: int = 25, short_period: int = 13, signal_period: int = 7):
        """
        Initialize True Strength Index
        
        Args:
            long_period: Long EMA period (default: 25)
            short_period: Short EMA period (default: 13)
            signal_period: Signal line period (default: 7)
        """
        super().__init__("TrueStrengthIndex")
        self.long_period = long_period
        self.short_period = short_period
        self.signal_period = signal_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate TSI parameters"""
        long_p = kwargs.get('long_period', self.long_period)
        short_p = kwargs.get('short_period', self.short_period)
        signal_p = kwargs.get('signal_period', self.signal_period)
        return (
            isinstance(long_p, int) and long_p > 0 and
            isinstance(short_p, int) and short_p > 0 and
            isinstance(signal_p, int) and signal_p > 0 and
            short_p < long_p
        )

    @cached_indicator("TrueStrengthIndex")
    @handle_indicator_errors("TrueStrengthIndex", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate TSI values
        
        Args:
            data: DataFrame with OHLC data (must have 'close' column)
            
        Returns:
            pd.DataFrame: TSI values with columns ['tsi', 'signal']
        """
        # Validate input data
        validate_dataframe(data, ['close'], min_rows=self.long_period)
        
        close = data['close']
        
        # Calculate price change
        price_change = close.diff()
        
        # Absolute price change
        abs_price_change = price_change.abs()
        
        # Double smooth the price change
        pc_smooth1 = price_change.ewm(span=self.long_period, adjust=False).mean()
        pc_smooth2 = pc_smooth1.ewm(span=self.short_period, adjust=False).mean()
        
        # Double smooth the absolute price change
        apc_smooth1 = abs_price_change.ewm(span=self.long_period, adjust=False).mean()
        apc_smooth2 = apc_smooth1.ewm(span=self.short_period, adjust=False).mean()
        
        # TSI = 100 * (Double Smoothed PC / Double Smoothed Absolute PC)
        tsi = 100 * (pc_smooth2 / apc_smooth2)
        tsi = tsi.replace([np.inf, -np.inf], 0).fillna(0)
        
        # Signal line
        signal = tsi.ewm(span=self.signal_period, adjust=False).mean()
        
        result = pd.DataFrame({
            'tsi': tsi,
            'signal': signal
        }, index=data.index)
        
        return result

    def get_signal(self, tsi: float, signal: float) -> Optional[str]:
        """
        Get trading signal based on TSI crossover
        
        Args:
            tsi: Current TSI value
            signal: Current signal line value
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if tsi > signal and tsi < 0:
            return 'buy'  # Crossing above signal in negative territory
        elif tsi < signal and tsi > 0:
            return 'sell'  # Crossing below signal in positive territory
        return None
