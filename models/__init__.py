"""Database models"""
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum, Table
from sqlalchemy.orm import relationship, validates
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
import uuid
import json
from zoneinfo import ZoneInfo

from core.database import Base

# Timezone de Brasília (UTC-3)
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

def get_brasilia_time():
    """Retorna datetime atual no timezone de Brasília"""
    return datetime.now(BRASILIA_TZ)

def get_brasilia_time_naive():
    """Retorna datetime atual sem timezone (offset-naive) para compatibilidade com PostgreSQL"""
    return datetime.utcnow()

def generate_uuid():
    """Generate UUID string"""
    return str(uuid.uuid4())


# Association table for Strategy-Indicator many-to-many relationship
strategy_indicators = Table(
    'strategy_indicators',
    Base.metadata,
    Column('strategy_id', String, ForeignKey('strategies.id'), primary_key=True),
    Column('indicator_id', String, ForeignKey('indicators.id'), primary_key=True),
    Column('parameters', JSON, nullable=True, default=dict),
    Column('created_at', DateTime, default=datetime.utcnow)
)


class User(Base):
    """User model"""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    telegram_chat_id = Column(String, nullable=True, index=True)
    telegram_username = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    # Sistema de planos: Free, VIP (Semanal), VIP+ (Mensal)
    role = Column(String, default="free")  # 'free', 'vip', 'vip_plus'
    vip_start_date = Column(DateTime(timezone=False), nullable=True)  # Data de início do VIP (naive para compatibilidade)
    vip_end_date = Column(DateTime(timezone=False), nullable=True)  # Data de término do VIP (naive para compatibilidade)
    maintenance_logout_at = Column(DateTime, nullable=True)  # Timestamp quando usuário foi deslogado por manutenção
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("Strategy", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    """PocketOption trading account model"""
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    ssid_demo = Column(Text, nullable=True)  # SSID da conta demo
    ssid_real = Column(Text, nullable=True)  # SSID da conta real
    name = Column(String, nullable=True)
    autotrade_demo = Column(Boolean, default=False, index=True)  # Se True, conecta e opera em demo
    autotrade_real = Column(Boolean, default=False, index=True)  # Se True, conecta e opera em real
    uid = Column(Integer, nullable=True)
    platform = Column(Integer, default=1)
    balance_demo = Column(Float, default=0.0)
    balance_real = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    is_active = Column(Boolean, default=True, index=True)
    last_connected = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    # Relationships
    user = relationship("User", back_populates="accounts")
    trades = relationship("Trade", back_populates="account", cascade="all, delete-orphan")
    strategies = relationship("Strategy", back_populates="account", cascade="all, delete-orphan")


class Asset(Base):
    """Trading asset model"""
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # forex, crypto, commodity, stock, index
    is_active = Column(Boolean, default=True)
    payout = Column(Float, nullable=True)
    min_order_amount = Column(Float, default=1.0)
    max_order_amount = Column(Float, default=50000.0)
    min_duration = Column(Integer, default=5)
    max_duration = Column(Integer, default=43200)
    available_timeframes = Column(JSON, nullable=True)  # Available timeframes from payout
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    # Relationships
    trades = relationship("Trade", back_populates="asset")


class TradeStatus(str, Enum):
    """Trade status enum"""
    PENDING = "pending"
    ACTIVE = "active"
    CLOSED = "closed"
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    CANCELLED = "cancelled"


class TradeDirection(str, Enum):
    """Trade direction enum"""
    CALL = "call"
    PUT = "put"


class Trade(Base):
    """Trade/Order model"""
    __tablename__ = "trades"

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=True, index=True)
    
    # PocketOption order ID
    order_id = Column(String, nullable=True)
    
    # Connection type used for this trade (demo or real)
    connection_type = Column(String, nullable=True)
    
    direction = Column(SQLEnum(TradeDirection), nullable=False)
    amount = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    duration = Column(Integer, nullable=False)  # in seconds
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.PENDING, nullable=False, index=True)
    
    profit = Column(Float, nullable=True)
    payout = Column(Float, nullable=True)
    
    placed_at = Column(DateTime, default=get_brasilia_time, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    closed_at = Column(DateTime, nullable=True, index=True)
    
    # Signal information
    signal_confidence = Column(Float, nullable=True)
    signal_indicators = Column(JSON, nullable=True)

    # Relationships
    account = relationship("Account", back_populates="trades")
    asset = relationship("Asset", back_populates="trades")
    strategy = relationship("Strategy", back_populates="trades")


class StrategyType(str, Enum):
    """Strategy type enum"""
    RSI = "rsi"
    MACD = "macd"
    BOLLINGER = "bollinger"
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    MULTI_OSCILLATOR = "multi_oscillator"
    SCALPING = "scalping"
    BREAKOUT = "breakout"
    CONFLUENCE = "confluence"
    CONFLUENCE_LONG_TERM = "confluence_long_term"
    CUSTOM = "custom"


class Strategy(Base):
    """Trading strategy model"""
    __tablename__ = "strategies"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=False)  # Aceitar qualquer string para o tipo
    parameters = Column(JSON, nullable=False)
    assets = Column(JSON, nullable=False)  # List of asset symbols
    indicators = Column(JSON, nullable=True)  # List of indicator IDs

    is_active = Column(Boolean, default=True)
    
    # Performance metrics
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_profit = Column(Float, default=0.0)
    total_loss = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=get_brasilia_time_naive)
    updated_at = Column(DateTime, default=get_brasilia_time_naive, onupdate=get_brasilia_time_naive)
    last_executed = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="strategies")
    account = relationship("Account", back_populates="strategies")
    trades = relationship("Trade", back_populates="strategy")
    signals = relationship("Signal", back_populates="strategy", cascade="all, delete-orphan")
    indicators = relationship("Indicator", secondary="strategy_indicators", back_populates="strategies")
    performance_snapshots = relationship(
        "StrategyPerformanceSnapshot",
        back_populates="strategy",
        cascade="all, delete-orphan"
    )


class StrategyPerformanceSnapshot(Base):
    """Cached strategy performance metrics"""
    __tablename__ = "strategy_performance_snapshots"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=False, index=True)
    period = Column(String, nullable=False, index=True)

    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_loss = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)

    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    avg_win = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    largest_win = Column(Float, default=0.0)
    largest_loss = Column(Float, default=0.0)
    consecutive_wins = Column(Integer, default=0)
    consecutive_losses = Column(Integer, default=0)

    monthly_returns = Column(JSON, nullable=False, default=list)

    calculated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    strategy = relationship("Strategy", back_populates="performance_snapshots")


class SignalType(str, Enum):
    """Signal type enum"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Signal(Base):
    """Trading signal model"""
    __tablename__ = "signals"

    id = Column(String, primary_key=True, default=generate_uuid)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=False, index=True)
    
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    timeframe = Column(Integer, nullable=False, index=True)  # Timeframe em segundos (3, 5, 30, 60)
    signal_type = Column(SQLEnum(SignalType), nullable=False)
    confidence = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    indicators = Column(JSON, nullable=True)
    confluence = Column(Float, nullable=True)  # Confluência de indicadores (0-100%)
    signal_source = Column(String, nullable=True, default='indicators')  # Source of the signal (indicators, ml, manual, etc.)
    
    is_executed = Column(Boolean, default=False)
    trade_id = Column(String, ForeignKey("trades.id"), nullable=True)
    
    created_at = Column(DateTime, default=get_brasilia_time_naive, index=True)
    executed_at = Column(DateTime, nullable=True)

    # Relationships
    strategy = relationship("Strategy", back_populates="signals")


class MonitoringAccountType(str, Enum):
    """Monitoring account type enum"""
    PAYOUT = "payout"
    ATIVOS = "ativos"


class MonitoringAccount(Base):
    """Monitoring account model for payout and assets"""
    __tablename__ = "monitoring_accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    ssid = Column(Text, nullable=False)  # SSID atual
    account_type = Column(String, nullable=False)  # 'payout' ou 'ativos'
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    uid = Column(Integer, nullable=True)
    platform = Column(Integer, default=1)
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)


class AutoTradeConfig(Base):
    """AutoTrade configuration model"""
    __tablename__ = "autotrade_configs"

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=True, index=True)
    
    # Configurações de operação
    amount = Column(Float, nullable=False, default=1.0)  # Valor da operação
    
    # Configurações de Stop Loss/Stop Gain (número de trades consecutivos antes de parar)
    stop1 = Column(Integer, nullable=False, default=3)  # Stop Gain: vitórias consecutivas
    stop2 = Column(Integer, nullable=False, default=5)  # Stop Loss: perdas consecutivas
    no_hibernate_on_consecutive_stop = Column(Boolean, nullable=False, default=False)  # Não hibernar ao atingir stop consecutivo

    # Configurações de Stop Amount (valores monetários para parar)
    stop_amount_win = Column(Float, nullable=False, default=0.0)  # Stop Amount Win: valor de lucro total para parar
    stop_amount_loss = Column(Float, nullable=False, default=0.0)  # Stop Amount Loss: valor de perda total para parar
    
    # Configurações de Soros (número de níveis, 0 para desabilitado)
    soros = Column(Integer, nullable=False, default=0)
    
    # Configurações de Martingale (número de níveis, 0 para desabilitado)
    martingale = Column(Integer, nullable=False, default=0)
    
    # Configurações de timeframe (timeframe em segundos que o usuário quer receber sinais)
    # Valores possíveis: 3, 5, 30, 60
    timeframe = Column(Integer, nullable=False, default=5)
    
    # Configurações adicionais
    min_confidence = Column(Float, nullable=False, default=0.7)  # Confiança mínima para executar trade
    cooldown_seconds = Column(String, nullable=True, default='0')  # Tempo mínimo entre operações (em segundos). Formato: "X" (fixo) ou "X-X" (randomizado, ex: "5-10")
    trade_timing = Column(String, nullable=False, default='on_signal')  # 'on_signal' ou 'on_candle_close'
    execute_all_signals = Column(Boolean, default=False)  # Executar todos os sinais, ignorando bloqueio de operações simultâneas
    all_win_percentage = Column(Float, nullable=False, default=0.0)  # Porcentagem da banca para ativar All-win (0 = desativado)
    highest_balance = Column(Float, nullable=True, default=None)  # Saldo mais alto alcançado (para cálculo do all-win)
    initial_balance = Column(Float, nullable=True, default=None)  # Saldo inicial quando a estratégia foi ligada pela primeira vez
    
    # Controle de estado
    is_active = Column(Boolean, default=False)
    daily_trades_count = Column(Integer, default=0)  # Contador de trades diários
    last_trade_date = Column(DateTime, nullable=True)  # Data do último trade
    last_trade_time = Column(DateTime, nullable=True)  # Timestamp do último trade (para cooldown)
    consecutive_stop_cooldown_until = Column(DateTime, nullable=True)  # Timestamp até quando o cooldown de stop consecutivo está ativo
    last_activity_timestamp = Column(DateTime, nullable=True)  # Timestamp da última atividade (trade executado ou estratégia ativada)
    
    # Controle de Soros e Martingale
    soros_level = Column(Integer, default=0)  # Nível atual do Soros (0 = desativado)
    soros_amount = Column(Float, default=0.0)  # Valor atual do Soros
    martingale_level = Column(Integer, default=0)  # Nível atual do Martingale (0 = desativado)
    martingale_amount = Column(Float, default=0.0)  # Valor atual do Martingale
    loss_consecutive = Column(Integer, default=0)  # Contador de perdas consecutivas para stop loss
    win_consecutive = Column(Integer, default=0)  # Contador de vitórias consecutivas para stop gain
    total_wins = Column(Integer, default=0)  # Total de vitórias (não consecutivas)
    total_losses = Column(Integer, default=0)  # Total de perdas (não consecutivas)
    
    # Redução Inteligente - ajusta valor da operação após sequência de losses/wins
    smart_reduction_enabled = Column(Boolean, default=False)  # Ativar/desativar redução inteligente
    smart_reduction_loss_trigger = Column(Integer, default=3)  # Número de losses consecutivos para reduzir amount
    smart_reduction_win_restore = Column(Integer, default=2)  # Número de wins consecutivos para restaurar amount
    smart_reduction_percentage = Column(Float, default=0.5)  # Percentual de redução (0.5 = 50%)
    smart_reduction_active = Column(Boolean, default=False)  # Estado atual: True = amount reduzido está ativo
    smart_reduction_base_amount = Column(Float, default=0.0)  # Valor base original para restaurar
    smart_reduction_loss_count = Column(Integer, default=0)  # Contador específico de losses para redução (independente do stop loss)
    smart_reduction_win_count = Column(Integer, default=0)  # Contador específico de wins para restauração
    smart_reduction_cascading = Column(Boolean, default=False)  # Redução recursiva/cascata: aplica redução sobre redução
    smart_reduction_cascade_level = Column(Integer, default=0)  # Nível atual da cascata de redução (0 = não em cascata)
    
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    # Relationships
    account = relationship("Account", backref="autotrade_config")


@dataclass
class Candle:
    """Candle data class for strategy analysis (not a database model)"""
    id: int = None
    asset_id: int = None
    timeframe: int = None
    timestamp: datetime = None
    open: float = None
    high: float = None
    low: float = None
    close: float = None
    volume: float = None


class IndicatorType(str, Enum):
    """Indicator type enum"""
    RSI = "rsi"
    MACD = "macd"
    BOLLINGER_BANDS = "bollinger_bands"
    SMA = "sma"
    EMA = "ema"
    STOCHASTIC = "stochastic"
    ATR = "atr"
    CCI = "cci"
    ROC = "roc"
    WILLIAMS_R = "williams_r"
    ZONAS = "zonas"
    CUSTOM = "custom"


class Indicator(Base):
    """Indicator model with configurable parameters"""
    __tablename__ = "indicators"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)  # Aceitar qualquer string para o tipo
    description = Column(Text, nullable=True)

    # Configurable parameters stored as JSON
    # Example: {"period": 14, "overbought": 70, "oversold": 30} for RSI
    _parameters = Column("parameters", JSON, nullable=False, default=dict)

    # Indicator settings
    is_active = Column(Boolean, default=True, index=True)
    is_default = Column(Boolean, default=False)  # Se True, é um indicador padrão do sistema

    # Metadata
    version = Column(String, default="1.0")
    created_at = Column(DateTime, default=get_brasilia_time)
    updated_at = Column(DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    # Relationships
    strategies = relationship("Strategy", secondary="strategy_indicators", back_populates="indicators")

    @property
    def parameters(self):
        """Get parameters as dictionary"""
        if isinstance(self._parameters, str):
            try:
                return json.loads(self._parameters)
            except (json.JSONDecodeError, TypeError):
                return {}
        return self._parameters or {}

    @parameters.setter
    def parameters(self, value):
        """Set parameters, converting dict to JSON string if needed"""
        if isinstance(value, dict):
            self._parameters = value
            return

        if isinstance(value, str):
            try:
                self._parameters = json.loads(value)
                return
            except (json.JSONDecodeError, TypeError):
                self._parameters = value
                return

        self._parameters = value
