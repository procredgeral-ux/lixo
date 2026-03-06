"""Database configuration and session management"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy import event
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from core.config import settings
from loguru import logger
import os
import time
import asyncio


# PostgreSQL connection - no SQLite-specific args needed
connect_args = {}

# Garantir que DATABASE_URL use asyncpg para async engine
database_url = settings.DATABASE_URL

# Log para debug (mascarado por segurança)
if database_url:
    masked_url = database_url.replace('://', '://***:***@').split('@')[0] + '@...' if '@' in database_url else '***'
    logger.info(f"[DB] DATABASE_URL configurada: {masked_url}")
else:
    logger.error("[DB] DATABASE_URL não configurada!")

if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

# Create async engine for PostgreSQL with optimized pooling for high load
try:
    engine = create_async_engine(
        database_url,
        echo=settings.DB_ECHO,
        pool_size=20,  # Conexões mantidas constantemente
        max_overflow=40,  # Conexões extras quando pool_size esgotado
        pool_pre_ping=True,  # Verifica saúde da conexão antes de usar
        pool_recycle=300,  # Recicla conexões após 5 minutos
        pool_timeout=30,  # Timeout para aguardar conexão disponível
        connect_args={
            'command_timeout': 60,
            'server_settings': {
                'application_name': 'tunestrade_app',
                'statement_timeout': '60000',
                'idle_in_transaction_session_timeout': '300000',
            }
        }
    )
    logger.success("[DB] Engine PostgreSQL criada com sucesso")
except Exception as e:
    logger.error(f"[DB] Erro ao criar engine: {e}")
    # Criar engine dummy para não quebrar imports
    engine = None

# No global lock needed for PostgreSQL (uses row-level locking)
db_lock = None

# Event listener para tracking de queries (só se engine foi criada)
if engine:
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """Capturar tempo antes da execução da query"""
        context._query_start_time = time.time()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """Tracking de query executada com tipo (SELECT, INSERT, UPDATE, DELETE)"""
        try:
            elapsed = (time.time() - context._query_start_time) * 1000  # ms
            
            # Detectar tipo de query a partir do statement SQL
            statement_lower = str(statement).strip().lower()
            if statement_lower.startswith('select'):
                query_type = 'select'
            elif statement_lower.startswith('insert'):
                query_type = 'insert'
            elif statement_lower.startswith('update'):
                query_type = 'update'
            elif statement_lower.startswith('delete'):
                query_type = 'delete'
            else:
                query_type = 'select'  # default
            
            # Import seguro do performance_monitor
            import sys
            if 'services.performance_monitor' in sys.modules:
                from services.performance_monitor import performance_monitor
                performance_monitor.record_db_query(time_ms=elapsed, error=False, query_type=query_type)
        except Exception:
            pass
else:
    logger.warning("[DB] Engine não criada - event listeners desabilitados")

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Patch para rastrear automaticamente todos os tipos de query
_original_execute = AsyncSession.execute
_original_add = AsyncSession.add
_original_add_all = AsyncSession.add_all
_original_delete = AsyncSession.delete

async def _patched_execute(self, statement, params=None, *args, **kwargs):
    """Wrapper para executar e rastrear tipo de query"""
    try:
        result = await _original_execute(self, statement, params, *args, **kwargs)
        
        # Detectar tipo de query a partir do statement
        query_type = 'select'  # default
        statement_str = str(statement).strip().lower()
        if statement_str.startswith('select'):
            query_type = 'select'
        elif statement_str.startswith('insert'):
            query_type = 'insert'
        elif statement_str.startswith('update'):
            query_type = 'update'
        elif statement_str.startswith('delete'):
            query_type = 'delete'
        
        # Registrar no performance monitor
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=False, query_type=query_type)
        except Exception:
            pass
        
        return result
    except Exception as e:
        # Registrar erro
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=True, query_type='select', error_message=str(e))
        except Exception:
            pass
        raise e

def _patched_add(self, instance, *args, **kwargs):
    """Wrapper para add (INSERT)"""
    try:
        result = _original_add(self, instance, *args, **kwargs)
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=False, query_type='insert')
        except Exception:
            pass
        return result
    except Exception as e:
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=True, query_type='insert', error_message=str(e))
        except Exception:
            pass
        raise e

def _patched_add_all(self, instances, *args, **kwargs):
    """Wrapper para add_all (múltiplos INSERTs)"""
    try:
        result = _original_add_all(self, instances, *args, **kwargs)
        try:
            from services.performance_monitor import performance_monitor
            if instances:
                for _ in instances:
                    performance_monitor.record_db_query(time_ms=0, error=False, query_type='insert')
        except Exception:
            pass
        return result
    except Exception as e:
        try:
            from services.performance_monitor import performance_monitor
            if instances:
                for _ in instances:
                    performance_monitor.record_db_query(time_ms=0, error=True, query_type='insert', error_message=str(e))
        except Exception:
            pass
        raise e

def _patched_delete(self, instance, *args, **kwargs):
    """Wrapper para delete (DELETE)"""
    try:
        result = _original_delete(self, instance, *args, **kwargs)
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=False, query_type='delete')
        except Exception:
            pass
        return result
    except Exception as e:
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_db_query(time_ms=0, error=True, query_type='delete', error_message=str(e))
        except Exception:
            pass
        raise e

# Aplicar patches
AsyncSession.execute = _patched_execute
AsyncSession.add = _patched_add
AsyncSession.add_all = _patched_add_all
AsyncSession.delete = _patched_delete

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI to get database session
    
    Usage:
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            ...
    """
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
    """Initialize database tables for PostgreSQL"""
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections"""
    await engine.dispose()


@asynccontextmanager
async def get_db_context():
    """
    Context manager for database session with PostgreSQL
    
    Usage:
        async with get_db_context() as db:
            result = await db.execute(query)
    """
    import time
    from services.performance_monitor import performance_monitor
    
    query_count_before = performance_monitor.stats['db_queries']
    
    # PostgreSQL doesn't need locks - uses row-level locking
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            
            # Contar queries executadas nesta sessão
            queries_executed = performance_monitor.stats['db_queries'] - query_count_before
            if queries_executed > 0:
                pass  # Log silenciado - não registrar queries executadas
        except Exception as e:
            # Try rollback only if session is still active
            try:
                if session.is_active:
                    await session.rollback()
            except Exception:
                pass  # Ignore rollback errors
            # Registrar erro no performance monitor e logar
            try:
                performance_monitor.stats['db_errors'] += 1
                error_msg = str(e)
                # Erro específico de duplicatas - informar usuário
                if "2 were matched" in error_msg and "UPDATE" in error_msg:
                    logger.error(f"[DB ERROR] Detectado registros duplicados. Execute: python cleanup_duplicates.py")
                else:
                    logger.error(f"[DB ERROR] Transação falhou: {e}")
            except Exception:
                pass
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Check if database connection is working"""
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
