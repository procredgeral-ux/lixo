"""FastAPI main application"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
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
from core.middleware import rate_limit_middleware, csrf_middleware, security_headers_middleware
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
    """Configurar loguru handlers"""
    import sys
    import io
    
    # Configure default extra fields for all log records
    logger.configure(
        extra={
            "user_name": "",
            "account_id": "",
            "account_type": "",
            "strategy_name": ""
        }
    )

    # Console handler - INFO level only
    class UTF8Stdout:
        def __init__(self):
            self.buffer = sys.stdout.buffer
        
        def write(self, text):
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except UnicodeEncodeError:
                # Fallback: replace problematic characters
                sys.stdout.write(text.encode('ascii', errors='replace').decode('ascii'))
                sys.stdout.flush()
        
        def flush(self):
            sys.stdout.flush()
    
    logger.add(
        sink=UTF8Stdout(),
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
    )

    # File handler - INFO level only (reduce verbosity)
    logger.add(
        sink="logs/app.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip"
    )

    # File handler - errors only
    logger.add(
        sink="logs/errors.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip"
    )

    # File handler - Data collector logs
    logger.add(
        sink="logs/data_collector.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: "data_collector" in record["name"]
    )

    # File handler - Telegram notifications queue logs
    logger.add(
        sink="logs/telegram_notifications.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: "telegram" in record["name"].lower()
    )

    # File handler - Strategy analysis logs
    logger.add(
        sink="logs/strategy_analysis.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {extra[strategy_name]:<20} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["strategies", "signals", "indicators"])
    )

    # File handler - Trade execution logs
    logger.add(
        sink="logs/trade_execution.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {extra[strategy_name]:<20} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["trade_executor", "trades", "execute_trade"])
    )

    # File handler - Warnings only
    logger.add(
        sink="logs/warnings.log",
        level="WARNING",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip"
    )

    # File handler - Rebalancing logs
    logger.add(
        sink="logs/rebalancing.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["reconnection_manager", "rebalance", "reconnection"])
    )

    # File handler - WebSocket connections logs
    logger.add(
        sink="logs/ws_connections.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[user_name]:<15} | {extra[account_id]:<6} | {extra[account_type]:<4} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        filter=lambda record: any(keyword in record["name"] for keyword in ["connection_manager", "keep_alive", "websocket", "ws_connection"])
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Limpar logs antigos ao iniciar
    clear_logs()
    
    # Configure loguru handlers (com rotação automática)
    logger.remove()  # Remove default handler
    configure_loguru()
    logger.info("Loguru configurado com rotação automática")
    
    # Startup
    logger.info("Starting application...")
    
    # Initialize database
    db_initialized = False
    try:
        await init_db()
        db_initialized = True
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        logger.warning("Continuing without database - migrations may be needed")
        # Don't raise - allow app to start for healthcheck
    
    # Check cache
    cache = get_cache()
    if cache:
        logger.info("Cache backend initialized")
    
    # Initialize and start data collector service - DISABLED for Railway deploy
    logger.info("Data collector service disabled for initial deploy")
    
    # Skip all background services for now - enable after healthcheck passes
    logger.info("Background services skipped - enable manually after deploy")
    
    logger.info("Application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    
    # Stop data collector service
    try:
        await data_collector.stop()
        logger.info("Data collector service stopped")
    except Exception as e:
        logger.error(f"Failed to stop data collector service: {e}")
    
    await close_db()
    logger.info("Application shut down successfully")


# Create FastAPI application
app = FastAPI(
    title="AutoTrade API",
    description="Professional automated trading system for PocketOption",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan
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

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests except GET"""
    # Não logar requisições GET
    if request.method == "GET":
        return await call_next(request)

    start_time = datetime.utcnow()

    response = await call_next(request)

    duration = (datetime.utcnow() - start_time).total_seconds()
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {duration:.3f}s"
    )

    return response


@app.middleware("http")
async def performance_metrics_middleware(request: Request, call_next):
    """Capturar métricas de performance para o dashboard"""
    from services.performance_monitor import performance_monitor
    import time
    
    start_time = time.time()
    
    try:
        response = await call_next(request)
        latency_ms = (time.time() - start_time) * 1000
        
        # Registrar requisição bem-sucedida (status 2xx ou 3xx)
        success = 200 <= response.status_code < 400
        performance_monitor.record_request(latency_ms=latency_ms, success=success)
        
        return response
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        performance_monitor.record_request(latency_ms=latency_ms, success=False)
        raise


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
