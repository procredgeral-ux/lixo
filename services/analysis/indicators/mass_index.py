"""Mass Index indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class MassIndex(TechnicalIndicator):
    """Mass Index - detects trend reversals based on volatility expansion"""

    def __init__(self, ema_period: int = 9, double_ema_period: int = 25):
        """
        Initialize Mass Index
        
        Args:
            ema_period: Single EMA period (default: 9)
            double_ema_period: Double EMA period (default: 25)
        """
        super().__init__("MassIndex")
        self.ema_period = ema_period
        self.double_ema_period = double_ema_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Mass Index parameters"""
        ema = kwargs.get('ema_period', self.ema_period)
        double_ema = kwargs.get('double_ema_period', self.double_ema_period)
        return (
            isinstance(ema, int) and ema > 0 and
            isinstance(double_ema, int) and double_ema > 0
        )

    @cached_indicator("MassIndex")
    @handle_indicator_errors("MassIndex", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate Mass Index values
        
        Args:
            data: DataFrame with OHLC data (must have 'high' and 'low' columns)
            
        Returns:
            pd.Series: Mass Index values
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low'], min_rows=self.double_ema_period)
        
        high = data['high']
        low = data['low']
        
        # Calculate range
        high_low_range = high - low
        
        # Single EMA of range
        ema1 = high_low_range.ewm(span=self.ema_period, adjust=False).mean()
        
        # Double EMA of range
        ema2 = ema1.ewm(span=self.ema_period, adjust=False).mean()
        
        # EMA ratio
        ema_ratio = ema1 / ema2
        
        # Mass Index = Sum of EMA ratios over double_ema_period
        mass_index = ema_ratio.rolling(window=self.double_ema_period).sum()
        
        return mass_index

    def get_signal(self, value: float, bulge_threshold: float = 27.0) -> Optional[str]:
        """
        Get trading signal based on Mass Index level
        
        Mass Index > 27 suggests possible reversal (volatility bulge)
        
        Args:
            value: Current Mass Index value
            bulge_threshold: Reversal threshold (default: 27.0)
            
        Returns:
            Optional[str]: 'reversal' when above threshold, None otherwise
        """
        if value >= bulge_threshold:
            return 'reversal'
        return None
