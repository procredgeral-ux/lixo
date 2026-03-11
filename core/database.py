"""Database configuration and session management"""
import os
import sys

# Windows: Use SelectorEventLoop instead of ProactorEventLoop for async database compatibility
if sys.platform == 'win32':
    import asyncio
    import selectors
    # Set the event loop policy to use SelectorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy import event, text
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from core.config import settings
from loguru import logger
import time
import asyncio


def parse_database_url(url: str) -> tuple[str, bool]:
    """Parse DATABASE_URL and extract SSL configuration."""
    parsed = urlparse(url)
    is_localhost = (
        'localhost' in parsed.hostname or 
        '127.0.0.1' in parsed.hostname or
        parsed.hostname == '0.0.0.0'
    ) if parsed.hostname else False
    query_params = parse_qs(parsed.query)
    sslmode_list = query_params.pop('sslmode', [])
    sslmode = sslmode_list[0] if sslmode_list else None
    if is_localhost:
        ssl_enabled = False
    elif sslmode in ['require', 'prefer', 'verify-ca', 'verify-full']:
        ssl_enabled = True
    elif sslmode == 'disable':
        ssl_enabled = False
    else:
        ssl_enabled = True
    if query_params:
        new_query = urlencode(query_params, doseq=True)
    else:
        new_query = ''
    clean_url = urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment
    ))
    return clean_url, ssl_enabled


# Parse DATABASE_URL
database_url, use_ssl = parse_database_url(settings.DATABASE_URL)

# Detect local before any modifications
is_local = 'localhost' in database_url or '127.0.0.1' in database_url

# Replace localhost with 127.0.0.1 to avoid Windows hostname issues
if 'localhost' in database_url:
    database_url = database_url.replace('localhost', '127.0.0.1')
    logger.info("[DB] Replaced localhost with 127.0.0.1")

# Convert to async driver format based on environment
if is_local:
    # Use psycopg for local (better Windows support)
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
else:
    # Use asyncpg for production (Railway)
    database_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

if database_url:
    masked = database_url.replace('://', '://***:***@').split('@')[0] + '@...' if '@' in database_url else '***'
    logger.info(f"[DB] DATABASE_URL: {masked}")
    logger.info(f"[DB] SSL: {use_ssl}, Local: {is_local}")
else:
    logger.error("[DB] DATABASE_URL not configured!")


# Create engine
try:
    if is_local:
        # Minimal config for Windows - but with larger pool
        logger.info("[DB] Using pool config for Windows")
        engine = create_async_engine(
            database_url,
            echo=settings.DB_ECHO,
            pool_size=5,
            max_overflow=10
        )
    else:
        logger.info("[DB] Using production pool settings (Railway)")
        
        # Detect if using Railway internal network (private domain)
        is_railway_internal = 'railway.internal' in database_url or 'postgres-' in database_url
        
        if is_railway_internal:
            # Internal Railway network - no SSL needed
            logger.info("[DB] Railway internal network detected - SSL disabled")
            engine = create_async_engine(
                database_url,
                echo=settings.DB_ECHO,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_timeout=30,
                connect_args={
                    'server_settings': {'application_name': 'tunestrade_app'}
                }
            )
        else:
            # External connection (public proxy) - use SSL with disabled verification
            logger.info("[DB] External connection - SSL enabled with cert verification disabled")
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            engine = create_async_engine(
                database_url,
                echo=settings.DB_ECHO,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_timeout=30,
                connect_args={
                    'ssl': ssl_context,
                    'server_settings': {'application_name': 'tunestrade_app'}
                }
            )
    logger.success("[DB] Engine PostgreSQL criada")
except Exception as e:
    logger.error(f"[DB] Erro ao criar engine: {e}")
    engine = None

# Event listeners
if engine:
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.time()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        try:
            elapsed = (time.time() - context._query_start_time) * 1000
            stmt = str(statement).strip().lower()
            qtype = 'select'
            if stmt.startswith('insert'): qtype = 'insert'
            elif stmt.startswith('update'): qtype = 'update'
            elif stmt.startswith('delete'): qtype = 'delete'
            import sys
            if 'services.performance_monitor' in sys.modules:
                from services.performance_monitor import performance_monitor
                performance_monitor.record_db_query(time_ms=elapsed, error=False, query_type=qtype)
        except Exception:
            pass

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Base class
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database - test connection"""
    if not engine:
        raise RuntimeError("Database engine not initialized")
    try:
        # Test SQLAlchemy connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.commit()
        logger.info("[DB] Database connection OK")
    except Exception as e:
        logger.error(f"[DB] Connection check failed: {e}")
        raise


async def close_db():
    """Close database connections"""
    if engine:
        await engine.dispose()


@asynccontextmanager
async def get_db_context():
    """Context manager for database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            try:
                if session.is_active:
                    await session.rollback()
            except Exception:
                pass
            logger.error(f"[DB ERROR] Transação falhou: {e}")
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Check if database connection is working"""
    if not engine:
        return False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
