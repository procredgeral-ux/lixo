"""Force Index indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class ForceIndex(TechnicalIndicator):
    """Force Index - measures buying/selling pressure"""

    def __init__(self, period: int = 13):
        """
        Initialize Force Index
        
        Args:
            period: EMA period for smoothing (default: 13)
        """
        super().__init__("ForceIndex")
        self.period = period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Force Index parameters"""
        period = kwargs.get('period', self.period)
        return isinstance(period, int) and period > 0

    @cached_indicator("ForceIndex")
    @handle_indicator_errors("ForceIndex", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Force Index values
        
        Args:
            data: DataFrame with OHLC data (must have 'close' and 'volume' columns)
            
        Returns:
            pd.Series: Force Index values
        """
        # Validate input data
        validate_dataframe(data, ['close', 'volume'], min_rows=2)
        
        close = data['close']
        volume = data['volume']
        
        # Calculate price change
        price_change = close.diff()
        
        # Raw Force Index = Volume * Price Change
        raw_force = volume * price_change
        
        # Smooth with EMA
        force_index = raw_force.ewm(span=self.period, adjust=False).mean()
        
        return force_index

    def get_signal(self, current_fi: float, previous_fi: float) -> Optional[str]:
        """
        Get trading signal based on Force Index crossover
        
        Args:
            current_fi: Current Force Index value
            previous_fi: Previous Force Index value
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        # Crossing above zero = buying pressure
        if previous_fi < 0 and current_fi > 0:
            return 'buy'
        # Crossing below zero = selling pressure
        elif previous_fi > 0 and current_fi < 0:
            return 'sell'
        return None
