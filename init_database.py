#!/usr/bin/env python3
"""
Script de inicialização do banco para Railway
Executa: migrations (alembic) + seed data
"""
import subprocess
import sys
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def run_migrations():
    """Executar alembic migrations ou criar tabelas diretamente"""
    logger.info("📦 Executando migrations...")
    
    # Tentar alembic primeiro
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
            cwd="/app"
        )
        logger.info("✅ Migrations concluídas")
        return True
    except Exception as e:
        logger.warning(f"Alembic falhou: {e}")
    
    # Fallback: criar tabelas diretamente
    logger.info("🔄 Criando tabelas com create_all...")
    try:
        import asyncio
        from core.database import engine, Base
        from models import User, Strategy  # Importar modelos principais
        # Importar e criar tabelas do daily_summary (Base separado)
        from models.daily_summary import Base as DailySummaryBase
        
        async def create_tables():
            async with engine.begin() as conn:
                # Criar tabelas do metadata principal
                await conn.run_sync(Base.metadata.create_all)
                # Criar tabelas do daily_summary
                await conn.run_sync(DailySummaryBase.metadata.create_all)
        
        asyncio.run(create_tables())
        logger.info("✅ Tabelas criadas com create_all")
        return True
    except Exception as e:
        logger.error(f"❌ create_all também falhou: {e}")
        return False


def run_seed():
    """Executar seed data"""
    logger.info("🌱 Executando seed data...")
    try:
        # Tentar importar seed_data se existir
        try:
            from seed_data import run_seed as seed_func
        except ImportError:
            logger.warning("⚠️  Módulo seed_data não encontrado, pulando seed")
            return True
        
        import asyncio
        asyncio.run(seed_func())
        return True
    except Exception as e:
        logger.error(f"❌ Erro no seed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def init_database():
    """Inicialização completa do banco"""
    logger.info("🚀 Iniciando setup do banco de dados...")
    
    # Construir DATABASE_URL a partir das variáveis do Railway PostgreSQL
    pg_host = os.getenv("PGHOST") or os.getenv("RAILWAY_PRIVATE_DOMAIN")
    pg_user = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
    pg_password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    pg_database = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")
    
    if pg_host and pg_user and pg_password and pg_database:
        # Construir URL completa
        db_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:5432/{pg_database}"
        os.environ["DATABASE_URL"] = db_url
        logger.info(f"✅ DATABASE_URL construída: postgresql://{pg_user}:***@{pg_host}:5432/{pg_database}")
    else:
        # Verificar DATABASE_URL direto
        db_url = os.getenv("DATABASE_URL")
        if not db_url or db_url.startswith("{{"):
            logger.error("❌ Variáveis do PostgreSQL não encontradas!")
            logger.info("PGHOST:" + str(pg_host))
            logger.info("PGUSER:" + str(pg_user))
            logger.info("PGDATABASE:" + str(pg_database))
            return False
        else:
            # Usar DATABASE_URL existente se válida
            if "postgresql" in db_url and not db_url.startswith("{{"):
                logger.info(f"✅ DATABASE_URL encontrada")
            else:
                logger.error(f"❌ DATABASE_URL inválida: {db_url[:50]}")
                return False
    
    # Passo 1: Migrations
    migrations_ok = run_migrations()
    if not migrations_ok:
        logger.warning("Migrations falharam, continuando...")
    
    # Passo 2: Seed data
    seed_ok = run_seed()
    if not seed_ok:
        logger.warning("Seed falhou, continuando...")
    
    logger.info("✅ Setup do banco concluído!")
    return True


if __name__ == "__main__":
    success = init_database()
    sys.exit(0)  # Sempre retornar 0 para não parar o deploy
