"""Klinger Volume Oscillator indicator"""
import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger

from .base import TechnicalIndicator
from .error_handler import handle_indicator_errors, validate_dataframe
from .cache import cached_indicator


class KlingerOscillator(TechnicalIndicator):
    """Klinger Volume Oscillator - volume-based trend indicator"""

    def __init__(self, fast_period: int = 34, slow_period: int = 55, signal_period: int = 13):
        """
        Initialize Klinger Oscillator
        
        Args:
            fast_period: Fast EMA period (default: 34)
            slow_period: Slow EMA period (default: 55)
            signal_period: Signal line period (default: 13)
        """
        super().__init__("KlingerOscillator")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def validate_parameters(self, **kwargs) -> bool:
        """Validate Klinger Oscillator parameters"""
        fast = kwargs.get('fast_period', self.fast_period)
        slow = kwargs.get('slow_period', self.slow_period)
        signal = kwargs.get('signal_period', self.signal_period)
        return (
            isinstance(fast, int) and fast > 0 and
            isinstance(slow, int) and slow > 0 and
            isinstance(signal, int) and signal > 0 and
            fast < slow
        )

    @cached_indicator("KlingerOscillator")
    @handle_indicator_errors("KlingerOscillator", fallback_value=None)
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Klinger Oscillator values
        
        Args:
            data: DataFrame with OHLC data (must have 'high', 'low', 'close', 'volume')
            
        Returns:
            pd.DataFrame: Klinger Oscillator values with columns ['kvo', 'signal']
        """
        # Validate input data
        validate_dataframe(data, ['high', 'low', 'close', 'volume'], min_rows=self.slow_period)
        
        high = data['high']
        low = data['low']
        close = data['close']
        volume = data['volume']
        
        # Calculate typical price
        typical_price = (high + low + close) / 3
        
        # Calculate trend (1 for up, -1 for down)
        trend = np.where(typical_price > typical_price.shift(1), 1, 
                        np.where(typical_price < typical_price.shift(1), -1, 0))
        
        # Calculate DM (daily measurement)
        dm = high - low
        
        # Calculate CM (cumulative measurement)
        cm = pd.Series(index=data.index, dtype=float)
        cm.iloc[0] = dm.iloc[0] if not pd.isna(dm.iloc[0]) else 0
        
        for i in range(1, len(data)):
            if trend[i] == trend[i-1]:
                cm.iloc[i] = cm.iloc[i-1] + dm.iloc[i]
            else:
                cm.iloc[i] = dm.iloc[i]
        
        # Calculate volume force
        vf = volume * abs(2 * (dm / cm) - 1) * trend * 100
        vf = vf.replace([np.inf, -np.inf], 0).fillna(0)
        
        # Calculate fast and slow EMAs
        kvo_fast = vf.ewm(span=self.fast_period, adjust=False).mean()
        kvo_slow = vf.ewm(span=self.slow_period, adjust=False).mean()
        
        # KVO is the difference
        kvo = kvo_fast - kvo_slow
        
        # Signal line
        signal = kvo.ewm(span=self.signal_period, adjust=False).mean()
        
        result = pd.DataFrame({
            'kvo': kvo,
            'signal': signal
        }, index=data.index)
        
        return result

    def get_signal(self, kvo: float, signal: float) -> Optional[str]:
        """
        Get trading signal based on KVO crossover
        
        Args:
            kvo: Current KVO value
            signal: Current signal line value
            
        Returns:
            Optional[str]: 'buy', 'sell', or None
        """
        if kvo > signal:
            return 'buy'
        elif kvo < signal:
            return 'sell'
        return None
