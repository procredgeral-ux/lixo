"""Schemas for API responses and requests"""

import json
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import date, datetime, timezone
from typing import Optional, List, Any, Dict
from enum import Enum


# ============================================
# HEALTH & GENERAL
# ============================================

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    database: Optional[str] = None
    redis: Optional[str] = None
    pocketoption: Optional[str] = None
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Error response"""
    error: dict


class MessageResponse(BaseModel):
    """Message response"""
    message: str


# ============================================
# AUTHENTICATION
# ============================================

class UserCreate(BaseModel):
    """User creation schema"""
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str


class UserLogin(BaseModel):
    """User login schema"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Token response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Token refresh schema"""
    refresh_token: str


class UserResponse(BaseModel):
    """User response"""
    id: str
    email: str
    name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    telegram_chat_id: Optional[str] = None
    telegram_username: Optional[str] = None
    role: str = 'free'
    vip_start_date: Optional[datetime] = None
    vip_end_date: Optional[datetime] = None


class UserAdminResponse(UserResponse):
    """User response for admin panel with account balances"""
    demo_balance: float = 0.0
    real_balance: float = 0.0


class UserUpdate(BaseModel):
    """User update schema"""
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class UserStats(BaseModel):
    """User statistics"""
    balance_demo: float = 0.0
    balance_real: float = 0.0
    win_rate_demo: float = 0.0
    win_rate_real: float = 0.0
    loss_rate_demo: float = 0.0
    loss_rate_real: float = 0.0
    total_trades_demo: int = 0
    total_trades_real: int = 0
    # Campos adicionais para dashboard
    lucro_hoje: float = 0.0
    lucro_semana: float = 0.0
    melhor_estrategia: str = ""
    taxa_sucesso: float = 0.0
    trades_hoje: int = 0
    maior_ganho: float = 0.0
    maior_perda: float = 0.0
    tempo_ativo: str = ""
    highest_balance: Optional[float] = None  # Saldo máximo já alcançado


# ============================================
# ACCOUNTS
# ============================================

class AccountResponse(BaseModel):
    """Account response"""
    id: str
    user_id: str
    name: Optional[str] = None
    autotrade_demo: bool = False
    autotrade_real: bool = False
    is_active: bool
    uid: Optional[int] = None
    platform: int = 1
    balance_demo: float = 0.0
    balance_real: float = 0.0
    currency: str = "USD"
    ssid_demo: Optional[str] = None
    ssid_real: Optional[str] = None
    last_connected: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class AccountCreate(BaseModel):
    """Account creation schema"""
    name: str
    autotrade_demo: bool = True
    autotrade_real: bool = False
    ssid_demo: Optional[str] = None
    ssid_real: Optional[str] = None


class AccountUpdate(BaseModel):
    """Account update schema"""
    name: Optional[str] = None
    is_active: Optional[bool] = None
    ssid_demo: Optional[str] = None
    ssid_real: Optional[str] = None


# ============================================
# ASSETS
# ============================================

class AssetResponse(BaseModel):
    """Asset response"""
    id: str
    symbol: str
    name: str
    type: str
    payout: Optional[float] = None
    is_active: bool = True
    min_order_amount: float = 1.0
    max_order_amount: float = 50000.0
    min_duration: int = 5
    max_duration: int = 43200
    available_timeframes: Optional[List[int]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============================================
# TRADES
# ============================================

class TradeResponse(BaseModel):
    """Trade response"""
    id: str
    user_id: str
    account_id: str
    asset_id: str
    symbol: str
    strategy_name: Optional[str] = None
    direction: str  # "call" or "put"
    amount: float
    duration: int
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    profit: Optional[float] = None
    status: str  # "pending", "won", "lost", "refunded"
    signal_confidence: Optional[float] = None
    signal_indicators: Optional[Any] = None
    created_at: datetime


class TradeCreate(BaseModel):
    """Trade creation schema"""
    symbol: str
    direction: str
    amount: float
    duration: int


class TradesListResponse(BaseModel):
    """Trades list response"""
    trades: List[TradeResponse]
    total: int
    page: int
    page_size: int


# ============================================
# STRATEGIES
# ============================================

class StrategyResponse(BaseModel):
    """Strategy response"""
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    indicators: Optional[List[Dict[str, Any]]] = None
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator('parameters', mode='before')
    @classmethod
    def parse_parameters(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    @field_validator('indicators', mode='before')
    @classmethod
    def parse_indicators(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v


class StrategyCreate(BaseModel):
    """Strategy creation schema"""
    name: str
    account_id: str
    type: str
    assets: Optional[List[str]] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    indicators: Optional[List[Dict[str, Any]]] = None


class StrategyUpdate(BaseModel):
    """Strategy update schema"""
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    indicators: Optional[List[Dict[str, Any]]] = None
    assets: Optional[List[str]] = None
    is_active: Optional[bool] = None


class StrategyWithPerformance(StrategyResponse):
    """Strategy with performance data"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0


class StrategyPerformance(BaseModel):
    """Strategy performance"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    monthly_returns: List[float] = []


class StrategyPerformanceSnapshotResponse(BaseModel):
    """Strategy performance snapshot"""
    strategy_id: str
    strategy_name: str
    performance: StrategyPerformance
    snapshot_date: datetime


class BacktestRequest(BaseModel):
    """Backtest request"""
    start_date: datetime
    end_date: datetime
    initial_balance: float = 1000.0


class BacktestResponse(BaseModel):
    """Backtest response"""
    strategy_id: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float
    total_profit: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float


# ============================================
# SIGNALS
# ============================================

class SignalResponse(BaseModel):
    """Signal response"""
    id: str
    strategy_id: str
    strategy_name: Optional[str] = None
    asset_id: str
    asset_name: Optional[str] = None
    symbol: str
    signal_type: str  # "call" or "put"
    confidence: float
    timeframe: int
    price: Optional[float] = None
    indicators: Optional[Any] = None
    confluence: Optional[float] = None  # Confluência de indicadores (0-100%)
    is_executed: bool = False
    created_at: datetime


class SignalsListResponse(BaseModel):
    """Signals list response"""
    signals: List[SignalResponse]
    total: int
    page: int
    page_size: int


# ============================================
# INDICATORS
# ============================================

class IndicatorResponse(BaseModel):
    """Indicator response"""
    id: str
    name: str
    type: str
    parameters: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class IndicatorCreate(BaseModel):
    """Indicator creation schema"""
    name: str
    type: str
    parameters: Optional[Dict[str, Any]] = None


class IndicatorUpdate(BaseModel):
    """Indicator update schema"""
    name: Optional[str] = None
    type: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class IndicatorsListResponse(BaseModel):
    """Indicators list response"""
    indicators: List[IndicatorResponse]
    total: int
    page: int
    page_size: int


# ============================================
# CANDLES
# ============================================

class CandleDataResponse(BaseModel):
    """Candle data response"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class CandleResponse(BaseModel):
    """Candle response"""
    symbol: str
    timeframe: int
    candles: List[CandleDataResponse]


# ============================================
# AUTOTRADE CONFIG
# ============================================

class AutoTradeConfigResponse(BaseModel):
    """AutoTrade config response"""
    id: str
    account_id: str
    strategy_id: Optional[str] = None
    amount: float = 1.0
    stop1: int = 0
    stop2: int = 0
    no_hibernate_on_consecutive_stop: bool = False
    stop_amount_win: float = 0.0
    stop_amount_loss: float = 0.0
    soros: int = 0
    martingale: int = 0
    timeframe: int = 5
    cooldown_seconds: str = '0'
    min_confidence: float = 0.7
    trade_timing: str = 'on_signal'
    execute_all_signals: bool = False
    all_win_percentage: float = 0.0
    highest_balance: Optional[float] = None
    # Redução Inteligente
    smart_reduction_enabled: bool = False
    smart_reduction_loss_trigger: int = 3
    smart_reduction_win_restore: int = 2
    smart_reduction_percentage: float = 50.0
    smart_reduction_loss_count: int = 0
    smart_reduction_win_count: int = 0
    smart_reduction_cascading: bool = False  # Redução recursiva/cascata
    smart_reduction_cascade_level: int = 0  # Nível atual da cascata
    created_at: datetime
    updated_at: Optional[datetime] = None


class AutoTradeConfigCreate(BaseModel):
    """AutoTrade config creation schema"""
    account_id: str
    strategy_id: Optional[str] = None
    user_id: Optional[str] = None  # Para admin configurar outro usuário
    amount: float = 10.0
    stop1: int = 3
    stop2: int = 5
    no_hibernate_on_consecutive_stop: bool = False
    stop_amount_win: float = 0.0
    stop_amount_loss: float = 0.0
    soros: int = 0
    martingale: int = 0
    timeframe: int = 5
    cooldown_seconds: str = '0'
    min_confidence: float = 0.7
    trade_timing: str = 'on_signal'
    execute_all_signals: bool = False
    all_win_percentage: float = 0.0
    highest_balance: Optional[float] = None
    is_active: bool = True
    # Redução Inteligente
    smart_reduction_enabled: bool = False
    smart_reduction_loss_trigger: int = 3
    smart_reduction_win_restore: int = 2
    smart_reduction_percentage: float = 50.0
    smart_reduction_loss_count: int = 0
    smart_reduction_win_count: int = 0
    smart_reduction_cascading: bool = False  # Redução recursiva/cascata
    smart_reduction_cascade_level: int = 0  # Nível atual da cascata

    @field_validator('cooldown_seconds', mode='before')
    @classmethod
    def ensure_cooldown_is_string(cls, v):
        if v is None:
            return '0'
        return str(v)

    class Config:
        extra = 'allow'  # Permitir campos extras como user_id


class AutoTradeConfigUpdate(BaseModel):
    """AutoTrade config update schema"""
    account_id: Optional[str] = None
    strategy_id: Optional[str] = None
    amount: Optional[float] = None
    stop1: Optional[int] = None
    stop2: Optional[int] = None
    no_hibernate_on_consecutive_stop: Optional[bool] = None
    stop_amount_win: Optional[float] = None
    stop_amount_loss: Optional[float] = None
    soros: Optional[int] = None
    martingale: Optional[int] = None
    timeframe: Optional[int] = None
    cooldown_seconds: Optional[str] = None
    min_confidence: Optional[float] = None
    trade_timing: Optional[str] = None
    execute_all_signals: Optional[bool] = None
    all_win_percentage: Optional[float] = None
    highest_balance: Optional[float] = None
    is_active: Optional[bool] = None
    # Redução Inteligente
    smart_reduction_enabled: Optional[bool] = None
    smart_reduction_loss_trigger: Optional[int] = None
    smart_reduction_win_restore: Optional[int] = None
    smart_reduction_percentage: Optional[float] = None
    smart_reduction_loss_count: Optional[int] = None
    smart_reduction_win_count: Optional[int] = None
    smart_reduction_cascading: Optional[bool] = None  # Redução recursiva/cascata
    smart_reduction_cascade_level: Optional[int] = None  # Nível atual da cascata

    @field_validator('cooldown_seconds', mode='before')
    @classmethod
    def ensure_cooldown_is_string(cls, v):
        if v is None:
            return None
        return str(v)


# ============================================
# INDICATOR RANKING
# ============================================

class IndicatorCombinationRanking(BaseModel):
    """Indicator combination ranking"""
    combination: str  # Sorted list of indicator names
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    avg_profit: float


class IndicatorRankingsResponse(BaseModel):
    """Indicator rankings response"""
    rankings: List[IndicatorCombinationRanking]
    total_combinations: int


# ============================================
# REPORTS
# ============================================

class DailySummaryResponse(BaseModel):
    """Resposta do resumo diário de sinais"""
    id: str
    date: date
    strategy_id: str
    asset_id: str
    total_signals: int
    buy_signals: int
    sell_signals: int
    executed_signals: int
    avg_confidence: float
    execution_rate: float
    
    class Config:
        from_attributes = True


class ReportQueryParams(BaseModel):
    """Parâmetros para queries de relatório"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    strategy_id: Optional[str] = None
    asset_id: Optional[str] = None


__all__ = [
    # Health & General
    "HealthResponse",
    "ErrorResponse",
    "MessageResponse",
    
    # Authentication
    "UserCreate",
    "UserLogin",
    "Token",
    "TokenRefresh",
    "UserResponse",
    "UserAdminResponse",
    "UserUpdate",
    "UserStats",
    
    # Accounts
    "AccountResponse",
    "AccountCreate",
    "AccountUpdate",
    
    # Assets
    "AssetResponse",
    
    # Trades
    "TradeResponse",
    "TradeCreate",
    "TradesListResponse",
    
    # Strategies
    "StrategyResponse",
    "StrategyCreate",
    "StrategyUpdate",
    "StrategyWithPerformance",
    "StrategyPerformance",
    "StrategyPerformanceSnapshotResponse",
    "BacktestRequest",
    "BacktestResponse",
    
    # Signals
    "SignalResponse",
    "SignalsListResponse",
    
    # Indicators
    "IndicatorResponse",
    "IndicatorCreate",
    "IndicatorUpdate",
    "IndicatorsListResponse",
    
    # Candles
    "CandleDataResponse",
    "CandleResponse",
    
    # AutoTrade Config
    "AutoTradeConfigResponse",
    "AutoTradeConfigCreate",
    "AutoTradeConfigUpdate",

    # Indicator Ranking
    "IndicatorCombinationRanking",
    "IndicatorRankingsResponse",
    
    # Reports
    "DailySummaryResponse",
    "ReportQueryParams"
]
