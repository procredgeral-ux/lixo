"""Configuration settings for the application"""
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Environment
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=False, env="DEBUG")
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"

    # Database - usa variável de ambiente ou SQLite como fallback
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./autotrade.db",
        env="DATABASE_URL"
    )
    DB_ECHO: bool = False

    # Redis (opcional - pode ser desabilitado)
    REDIS_HOST: str = Field(default="localhost", env="REDIS_HOST")
    REDIS_PORT: int = Field(default=6379, env="REDIS_PORT")
    REDIS_DB: int = Field(default=0, env="REDIS_DB")
    REDIS_PASSWORD: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    REDIS_ENABLED: bool = Field(default=False, env="REDIS_ENABLED")
    REDIS_CACHE_TTL: int = Field(default=300, env="REDIS_CACHE_TTL")

    # JWT
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120  # 2 horas (era 30min)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # PocketOption
    POCKETOPTION_DEMO_SSID: Optional[str] = Field(None, env="POCKETOPTION_DEMO_SSID")
    POCKETOPTION_LIVE_SSID: Optional[str] = Field(None, env="POCKETOPTION_LIVE_SSID")
    POCKETOPTION_DEFAULT_REGION: str = "EUROPA"
    POCKETOPTION_PING_INTERVAL: int = 20
    POCKETOPTION_RECONNECT_DELAY: int = 5
    POCKETOPTION_MAX_RECONNECT_ATTEMPTS: int = 10
    POCKETOPTION_MAINTENANCE_CHECK_ENABLED: bool = Field(
        default=True,
        env="POCKETOPTION_MAINTENANCE_CHECK_ENABLED",
    )
    POCKETOPTION_MAINTENANCE_CHECK_URL: str = Field(
        default="https://pocketoption.com/pt/cabinet/demo-quick-high-low/",
        env="POCKETOPTION_MAINTENANCE_CHECK_URL",
    )
    POCKETOPTION_MAINTENANCE_CHECK_INTERVAL: int = Field(
        default=60,
        env="POCKETOPTION_MAINTENANCE_CHECK_INTERVAL",
    )
    POCKETOPTION_MAINTENANCE_CHECK_TIMEOUT: int = Field(
        default=10,
        env="POCKETOPTION_MAINTENANCE_CHECK_TIMEOUT",
    )

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_ENABLED: bool = False

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 200  # Aumentado de 100
    RATE_LIMIT_PER_MINUTE_AUTH: int = 500  # Aumentado de 300

    # CORS - Railway usa domínios dinâmicos *.up.railway.app
    CORS_ORIGINS: str = "*"  # Em produção Railway, permitir todas as origens ou configurar via env
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    CORS_ALLOW_HEADERS: List[str] = ["Content-Type", "Authorization", "X-Requested-With"]

    # Monitoring
    SENTRY_DSN: str = ""
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090

    # Email (for notifications)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@autotrade.com"
    SMTP_USE_TLS: bool = True
    EMAIL_ENABLED: bool = False

    # Telegram (for notifications)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ENABLED: bool = False

    # Risk Management
    MAX_TRADES_PER_DAY: int = 20
    MAX_TRADES_SIMULTANEOUS: int = 5
    MAX_TRADE_AMOUNT: float = 100.0
    MAX_DAILY_LOSS_PERCENT: float = 5.0
    MIN_SIGNAL_CONFIDENCE: float = 0.7

    # Data Collection
    DATA_COLLECTION_INTERVAL: int = 1
    HISTORICAL_DATA_DAYS: int = 365
    MAX_CANDLES_PER_REQUEST: int = 1000
    DATA_COLLECTOR_ENABLED: bool = True

    # Railway Deployment
    RAILWAY_FAST_MODE: bool = Field(default=False, env="RAILWAY_FAST_MODE")

    # Strategy
    DEFAULT_TIMEFRAME: int = 60
    DEFAULT_AMOUNT: float = 10.0
    DEFAULT_DURATION: int = 60
    STRATEGY_BACKTEST_INITIAL_BALANCE: float = 1000.0

    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30
    WS_MAX_CONNECTIONS: int = 1000
    WS_MESSAGE_QUEUE_SIZE: int = 100

    # Logging
    LOG_FILE: str = "logs/autotrade.log"
    LOG_ROTATION: str = "1 day"
    LOG_RETENTION: str = "7 days"
    LOG_FORMAT: str = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

    @field_validator('SECRET_KEY')
    @classmethod
    def validate_secret_key(cls, v):
        if len(v) < 32:
            raise ValueError('SECRET_KEY deve ter pelo menos 32 caracteres')
        if v == "your-secret-key-change-this-in-production":
            raise ValueError('SECRET_KEY não pode ser o valor padrão')
        return v

    @field_validator('ENVIRONMENT')
    @classmethod
    def validate_environment(cls, v):
        if v not in ["development", "staging", "production"]:
            raise ValueError('ENVIRONMENT deve ser development, staging ou production')
        return v

    @field_validator('API_PORT')
    @classmethod
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError('API_PORT deve estar entre 1 e 65535')
        return v

    @field_validator('ACCESS_TOKEN_EXPIRE_MINUTES')
    @classmethod
    def validate_token_expiry(cls, v):
        if v < 1 or v > 1440:
            raise ValueError('ACCESS_TOKEN_EXPIRE_MINUTES deve estar entre 1 e 1440')
        return v

    @field_validator('MAX_TRADES_PER_DAY')
    @classmethod
    def validate_max_trades(cls, v):
        if v < 1 or v > 1000:
            raise ValueError('MAX_TRADES_PER_DAY deve estar entre 1 e 1000')
        return v

    @field_validator('MAX_TRADE_AMOUNT')
    @classmethod
    def validate_max_amount(cls, v):
        if v < 1 or v > 100000:
            raise ValueError('MAX_TRADE_AMOUNT deve estar entre 1 e 100000')
        return v

    @property
    def REDIS_URL(self) -> str:
        """Generate Redis URL from environment variable or components"""
        import os
        # Railway fornece REDIS_URL diretamente
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            return redis_url
        
        # Senão, construir a partir dos componentes
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @field_validator('REDIS_ENABLED')
    @classmethod
    def validate_redis_config(cls, v, info):
        if v:
            # Validar que host está configurado
            host = info.data.get('REDIS_HOST')
            port = info.data.get('REDIS_PORT')
            if not host or not port:
                raise ValueError('REDIS_HOST e REDIS_PORT são obrigatórios quando REDIS_ENABLED=true')
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.ENVIRONMENT == "development"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
