"""FastAPI main application"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime
from contextlib import asynccontextmanager
import shutil
from pathlib import Path

from core.config import settings
from core.database import init_db, close_db, check_db_connection
from core.cache import get_cache
from core.security.unified import initialize_security, shutdown_security, get_security_health
from core.middleware import rate_limit_middleware, csrf_middleware, security_headers_middleware
from core.middleware.metrics import setup_metrics_middleware
from api.cache import init_cache as init_api_cache, close_cache as close_api_cache
from schemas import HealthResponse, ErrorResponse, MessageResponse
from loguru import logger

# Import routers
from api.routers import auth, users, accounts, assets, strategies, trades, signals, candles, indicators, autotrade_config, maintenance, admin, connection

# Import data collector service
from services.data_collector.realtime import data_collector

# Configure rate limiter
limiter = Limiter(key_func=get_remote_address)


def clear_logs():
    """Limpar todos os arquivos de log ao iniciar"""
    import os
    import shutil
    
    # Obter caminho absoluto para o diretório de logs (backend/logs, não api/logs)
    current_dir = Path(__file__).parent.parent
    logs_dir = current_dir / "logs"
    
    print(f"Diretorio de logs: {logs_dir.absolute()}")
    print(f"Diretorio de logs existe: {logs_dir.exists()}")
    
    if logs_dir.exists():
        try:
            # Tentar deletar cada arquivo individualmente
            deleted_count = 0
            skipped_count = 0
            
            for filename in os.listdir(logs_dir):
                file_path = logs_dir / filename
                try:
                    if file_path.is_file():
                        os.unlink(file_path)
                        deleted_count += 1
                    elif file_path.is_dir() and filename == "ws":
                        # Limpar subpasta ws (WebSocket connection logs)
                        ws_deleted = 0
                        for ws_file in file_path.glob("*.log"):
                            try:
                                ws_file.unlink()
                                ws_deleted += 1
                            except:
                                skipped_count += 1
                        print(f"[OK] {ws_deleted} arquivos deletados de logs/ws")
                    elif file_path.is_dir() and filename == "users":
                        # Limpar subpasta users (logs por usuário)
                        users_deleted = 0
                        for user_file in file_path.glob("*.txt"):
                            try:
                                user_file.unlink()
                                users_deleted += 1
                            except:
                                skipped_count += 1
                        print(f"[OK] {users_deleted} arquivos deletados de logs/users")
                except Exception as e:
                    # Ignorar arquivos em uso
                    skipped_count += 1
                    print(f"[!] Arquivo em uso: {filename}")
            
            print(f"[OK] {deleted_count} arquivos deletados, {skipped_count} ignorados")
            
        except Exception as e:
            print(f"[ERROR] Não foi possível limpar os logs: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("[OK] Diretório de logs não existe, criando...")
        logs_dir.mkdir(parents=True, exist_ok=True)


def configure_loguru():
    """Configurar loguru handlers com LOG_LEVEL do .env e filtro dinâmico"""
    import sys
    import io
    
    # Obter nível de log das configurações
    log_level = settings.LOG_LEVEL.upper()
    
    # IMPORTANTE: Remover handlers padrão do Loguru para que o LOG_LEVEL funcione
    logger.remove()
    
    # Adicionar nível SUCCESS customizado ao loguru (se não existir)
    try:
        logger.level("SUCCESS")
    except ValueError:
        logger.level("SUCCESS", no=25, color="<green>", icon="✅")
    
    # Configure default extra fields for all log records
    logger.configure(
        extra={
            "user_name": "",
            "account_id": "",
            "account_type": "",
            "strategy_name": ""
        }
    )

    # Filtro global que verifica LoggerManager
    def log_filter(record):
        """Filtra logs baseado no LoggerManager"""
        try:
            from core.system_manager import get_logger_manager
            logger_manager = get_logger_manager()
            level = record["level"].name
            enabled = logger_manager.is_level_enabled(level)
            return enabled
        except Exception:
            # Se houver erro, permite o log passar
            return True

    # Console handler - usa LOG_LEVEL do .env + filtro dinâmico
    class UTF8Stdout:
        def __init__(self):
            self.buffer = sys.stdout.buffer
        
        def write(self, text):
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except UnicodeEncodeError:
                sys.stdout.write(text.encode('ascii', errors='replace').decode('ascii'))
                sys.stdout.flush()
        
        def flush(self):
            sys.stdout.flush()
    
    logger.add(
        sink=UTF8Stdout(),
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        filter=log_filter
    )

    # File handler - app.log (usa LOG_LEVEL do .env) - ROTAÇÃO: ~20k linhas (500KB)
    logger.add(
        sink="logs/app.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="50 MB"  # Rotação por tamanho (~20k linhas)
    )

    # File handler - errors.log (sempre ERROR)
    logger.add(
        sink="logs/errors.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip"
    )

    # File handler - Data collector logs (usa LOG_LEVEL do .env) - ROTAÇÃO: ~20k linhas (500KB)
    logger.add(
        sink="logs/data_collector.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="50 MB",  # Rotação por tamanho (~20k linhas)
        filter=lambda record: "data_collector" in record["name"]
    )

    # File handler - Telegram notifications queue logs (usa LOG_LEVEL do .env)
    logger.add(
        sink="logs/telegram_notifications.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: "telegram" in record["name"].lower()
    )

    # File handler - Strategy analysis logs (usa LOG_LEVEL do .env)
    logger.add(
        sink="logs/strategy_analysis.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {extra[strategy_name]:<20} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["strategies", "signals", "indicators"])
    )

    # File handler - Trade execution logs (usa LOG_LEVEL do .env)
    logger.add(
        sink="logs/trade_execution.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {extra[strategy_name]:<20} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["trade_executor", "trades", "execute_trade"])
    )

    # File handler - Warnings only (sempre WARNING)
    logger.add(
        sink="logs/warnings.log",
        level="WARNING",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip"
    )

    # File handler - Rebalancing logs (usa LOG_LEVEL do .env)
    logger.add(
        sink="logs/rebalancing.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["reconnection_manager", "rebalance", "reconnection"])
    )

    # File handler - WebSocket connections logs (usa LOG_LEVEL do .env)
    logger.add(
        sink="logs/ws_connections.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["connection_manager", "keep_alive", "websocket", "ws_connection"])
    )


# Configure logging at module level (before any other operations)
clear_logs()
configure_loguru()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - suporta modo Railway e modo completo"""
    
    if settings.RAILWAY_FAST_MODE:
        # Modo Railway - startup rápido sem inicializações pesadas
        logger.info(f"🚀 Application starting (Railway fast mode) | Log Level: {settings.LOG_LEVEL}")
        logger.info("✅ Fast startup - services will initialize on first request")
    else:
        # Modo completo - inicializa todos os serviços com logs detalhados
        logger.info(f"🚀 Application starting (Full mode) | Log Level: {settings.LOG_LEVEL}")
        logger.info("📝 Loguru configured with automatic rotation")
        
        # Initialize database
        try:
            await init_db()
            db_connected = await check_db_connection()
            if db_connected:
                logger.info("✅ Database initialized successfully")
            else:
                logger.warning("⚠️ Database connection check failed")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
        
        # Initialize admin API cache (Redis)
        try:
            await init_api_cache()
            logger.info("✅ Admin API cache initialized")
        except Exception as e:
            logger.warning(f"⚠️ Admin API cache initialization failed: {e}")
        
        # Initialize security (Redis sessions, token blacklist, audit)
        try:
            logger.info("🔒 Initializing security system...")
            await initialize_security()
            health = await get_security_health()
            if health['redis']['redis_connected']:
                logger.info("✅ Security system initialized with Redis")
            else:
                logger.warning("⚠️ Security system initialized in fallback mode (Redis unavailable)")
        except Exception as e:
            logger.error(f"❌ Security system initialization failed: {e}")
        
        # Initialize data collector service
        if settings.DATA_COLLECTOR_ENABLED:
            try:
                logger.info("📊 Initializing data collector service...")
                await data_collector.initialize()
                logger.info("✅ Data collector service initialized")
                
                # Start data collector
                await data_collector.start()
                logger.info("✅ Data collector service started")
            except Exception as e:
                logger.error(f"❌ Data collector initialization failed: {e}")
        
        # Initialize Telegram notification service
        if settings.TELEGRAM_ENABLED:
            try:
                from services.notifications.telegram_v2 import telegram_service
                await telegram_service.start()
                logger.info("✅ Telegram notification service started")
            except Exception as e:
                logger.warning(f"⚠️ Telegram service initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    
    if not settings.RAILWAY_FAST_MODE:
        # Stop data collector
        try:
            await data_collector.stop()
            logger.info("✅ Data collector stopped")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping data collector: {e}")
        
        # Shutdown security system
        try:
            await shutdown_security()
            logger.info("✅ Security system shutdown")
        except Exception as e:
            logger.warning(f"⚠️ Error shutting down security system: {e}")
    
        # Close admin API cache
        try:
            await close_api_cache()
            logger.info("✅ Admin API cache closed")
        except Exception as e:
            logger.warning(f"⚠️ Error closing admin API cache: {e}")


# Create FastAPI application
app = FastAPI(
    title="AutoTrade API",
    description="Professional automated trading system for PocketOption",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
    redirect_slashes=False
)

# Configure rate limiter
app.state.limiter = limiter

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(',')] if settings.CORS_ORIGINS else [],
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup metrics middleware for performance monitoring
setup_metrics_middleware(app)

# Add GZip compression middleware (reduz tamanho das respostas JSON)
# Compress respostas maiores que 1KB para evitar overhead em respostas pequenas
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ==================== EXCEPTION HANDLERS ====================

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded"""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests. Please try again later.",
                "retry_after": getattr(exc, "retry_after", 60)
            }
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation failed",
                "details": exc.errors()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error("Unhandled exception: {}", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "details": str(exc) if settings.DEBUG else "An error occurred"
            }
        }
    )


# ==================== MIDDLEWARE ====================

app.middleware("http")(security_headers_middleware)
app.middleware("http")(csrf_middleware)
app.middleware("http")(rate_limit_middleware)


# ==================== HEALTH CHECK ====================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint - simplified for Railway deployment"""
    # Basic health check - always return healthy for Railway healthcheck
    # Database check is done separately, not blocking deploy
    return HealthResponse(
        status="healthy",
        database="checking",
        redis=None,
        pocketoption=None,
        timestamp=datetime.utcnow()
    )


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "status": "ok",
        "service": "autotrade-api",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


# ==================== ROUTERS ====================

# Include routers
app.include_router(auth.router, prefix=f"{settings.API_PREFIX}/auth", tags=["Authentication"])
app.include_router(users.router, prefix=f"{settings.API_PREFIX}/users", tags=["Users"])
app.include_router(accounts.router, prefix=f"{settings.API_PREFIX}/accounts", tags=["Accounts"])
app.include_router(assets.router, prefix=f"{settings.API_PREFIX}/assets", tags=["Assets"])
app.include_router(strategies.router, prefix=f"{settings.API_PREFIX}/strategies", tags=["Strategies"])
app.include_router(trades.router, prefix=f"{settings.API_PREFIX}/trades", tags=["Trades"])
app.include_router(signals.router, prefix=f"{settings.API_PREFIX}/signals", tags=["Signals"])
app.include_router(candles.router, prefix=f"{settings.API_PREFIX}/candles", tags=["Candles"])
app.include_router(indicators.router, prefix=f"{settings.API_PREFIX}/indicators", tags=["Indicators"])
app.include_router(autotrade_config.router, prefix=f"{settings.API_PREFIX}/autotrade-config", tags=["AutoTrade Config"])
app.include_router(maintenance.router, prefix=f"{settings.API_PREFIX}/maintenance", tags=["Maintenance"])
app.include_router(admin.router, prefix=f"{settings.API_PREFIX}/admin", tags=["Admin"])
app.include_router(connection.router, prefix=f"{settings.API_PREFIX}/connection", tags=["Connection"])


# ==================== EVENTS ====================

@app.on_event("startup")
async def startup_event():
    """Startup event"""
    logger.info("Application startup event")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event"""
    logger.info("Application shutdown event")
    
    # Stop aggregation job
    try:
        from services.aggregation_job import aggregation_job
        await aggregation_job.stop()
        logger.info("Aggregation job stopped")
    except Exception as e:
        logger.warning(f"Failed to stop aggregation job: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
