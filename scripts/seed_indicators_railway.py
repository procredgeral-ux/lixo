#!/usr/bin/env python3
"""Script para cadastrar indicadores padrão no Railway via API"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from core.database import get_db_context
from api.routers.indicators import seed_default_indicators

async def run_seed():
    """Executar seed de indicadores"""
    print("🌱 Iniciando seed de indicadores...")
    
    async with get_db_context() as db:
        result = await seed_default_indicators(db)
        print(f"✅ {result.message}")

if __name__ == "__main__":
    asyncio.run(run_seed())
