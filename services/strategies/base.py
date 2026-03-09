"""Base class for trading strategies"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
import pandas as pd

from models import Candle, Signal, SignalType


class BaseStrategy(ABC):
    """Base class for trading strategies"""

    def __init__(
        self,
        name: str,
        strategy_type: str,
        account_id: str,
        parameters: Dict[str, Any],
        assets: List[str]
    ):
        self.name = name
        self.strategy_type = strategy_type
        self.account_id = account_id
        self.parameters = parameters
        self.assets = assets
        self.is_active = True

    @abstractmethod
    async def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """
        Analyze candles and generate signal

        Args:
            candles: List of candles to analyze

        Returns:
            Optional[Signal]: Generated signal or None
        """
        pass

    @abstractmethod
    def validate_parameters(self) -> bool:
        """
        Validate strategy parameters

        Returns:
            bool: True if parameters are valid
        """
        pass

