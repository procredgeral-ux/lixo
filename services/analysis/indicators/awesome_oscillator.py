"""Awesome Oscillator (AO) indicator"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class AwesomeOscillator(TechnicalIndicator):
    """Awesome Oscillator - momentum indicator based on simple moving averages"""

    def __init__(self, fast_period: int = 5, slow_period: int = 34):
        """
        Initialize Awesome Oscillator
        
        Args:
            fast_period: Fast SMA period (default: 5)
            slow_period: Slow SMA period (default: 34)
        """
        super().__init__("AwesomeOscillator")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate AO parameters"""
        fast = kwargs.get('fast_period', self.fast_period)
        slow = kwargs.get('slow_period', self.slow_period)
        return (
            isinstance(fast, int) and fast > 0 and
            isinstance(slow, int) and slow > 0 and
            fast < slow
        )

    @cached_indicator("AwesomeOscillator")
    @handle_indicator_errors("AwesomeOscillator", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Awesome Oscillator values
        
        Args:
            data: DataFrame with OHLC data (must have 'high' and 'low' columns)
            
        Returns:
            pd.Series: AO values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low'], min_rows=self.slow_period)
        
        # Calculate median price
        median_price = (data['high'] + data['low']) / 2
        
        # Calculate fast and slow SMAs
        sma_fast = median_price.rolling(window=self.fast_period).mean()
        sma_slow = median_price.rolling(window=self.slow_period).mean()
        
        # AO is the difference
        ao = sma_fast - sma_slow
        
        return ao

    def get_signal(self, current_ao: float, previous_ao: float) -> Optional[str]:
        """
        Get trading signal based on AO crossover
        
        Args:
            current_ao: Current AO value
            previous_ao: Previous AO value
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if previous_ao < 0 and current_ao > 0:
            return 'buy'  # Crossing above zero
        elif previous_ao > 0 and current_ao < 0:
            return 'sell'  # Crossing below zero
        return None
