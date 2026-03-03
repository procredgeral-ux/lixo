#!/usr/bin/env python3
"""
Script de inicialização do banco para Railway
Executa: migrations (alembic) + seed data
"""
import asyncio
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_migrations():
    """Executar alembic migrations"""
    logger.info("📦 Executando migrations...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("✅ Migrations concluídas")
        if result.stdout:
            logger.info(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Erro nas migrations: {e}")
        logger.error(e.stderr)
        return False
    except FileNotFoundError:
        logger.warning("⚠️ Alembic não encontrado, pulando migrations")
        return True


async def run_seed():
    """Executar seed data"""
    logger.info("🌱 Executando seed data...")
    try:
        from seed_data import run_seed
        await run_seed()
        return True
    except Exception as e:
        logger.error(f"❌ Erro no seed: {e}")
        return False


async def init_database():
    """Inicialização completa do banco"""
    logger.info("🚀 Iniciando setup do banco de dados...")
    
    # Passo 1: Migrations
    migrations_ok = await run_migrations()
    if not migrations_ok:
        logger.error("Migrations falharam, tentando continuar...")
    
    # Passo 2: Seed data
    seed_ok = await run_seed()
    if not seed_ok:
        logger.error("Seed falhou")
        return False
    
    logger.info("✅ Setup do banco concluído!")
    return True


if __name__ == "__main__":
    success = asyncio.run(init_database())
    sys.exit(0 if success else 1)
