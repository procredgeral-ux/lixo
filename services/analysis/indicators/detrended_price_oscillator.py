"""Detrended Price Oscillator (DPO) indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class DetrendedPriceOscillator(TechnicalIndicator):
    """Detrended Price Oscillator - removes trend to show cycles"""

    def __init__(self, period: int = 20):
        """
        Initialize DPO
        
        Args:
            period: Lookback period for detrending (default: 20)
        """
        super().__init__("DetrendedPriceOscillator")
        self.period = period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate DPO parameters"""
        period = kwargs.get('period', self.period)
        return isinstance(period, int) and period > 0

    @cached_indicator("DetrendedPriceOscillator")
    @handle_indicator_errors("DetrendedPriceOscillator", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate DPO values
        
        Args:
            data: DataFrame with OHLC data (must have 'close' column)
            
        Returns:
            pd.Series: DPO values
        """
        # Validate input data
        validate_dataframe(data, ['close'], min_rows=self.period)
        
        close = data['close']
        
        # Calculate SMA with shift (detrending)
        sma = close.rolling(window=self.period).mean()
        
        # DPO = Close - SMA(period/2 + 1 periods ago)
        shift_period = int(self.period / 2) + 1
        dpo = close - sma.shift(shift_period)
        
        return dpo

    def get_signal(self, value: float, upper_threshold: float = 0.05, lower_threshold: float = -0.05) -> Optional[str]:
        """
        Get trading signal based on DPO level
        
        Args:
            value: Current DPO value
            upper_threshold: Upper threshold (default: 5%)
            lower_threshold: Lower threshold (default: -5%)
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if value <= lower_threshold:
            return 'buy'  # Price below trend = oversold
        elif value >= upper_threshold:
            return 'sell'  # Price above trend = overbought
        return None
