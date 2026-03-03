"""
Verifica enum trade_timing no Railway
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

RAILWAY_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"

async def check_enums():
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.connect() as conn:
        # Buscar todos os enums
        result = await conn.execute(text("""
            SELECT t.typname AS enum_name,
                   e.enumlabel AS enum_value
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            ORDER BY t.typname, e.enumsortorder
        """))
        enums = result.fetchall()
        
        print("📋 Enums no Railway:")
        current = None
        for enum_name, enum_value in enums:
            if enum_name != current:
                print(f"\n  {enum_name}:")
                current = enum_name
            print(f"    - {enum_value}")
        
        # Verificar colunas de autotrade_configs
        result = await conn.execute(text("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'autotrade_configs' AND table_schema = 'public'
            ORDER BY ordinal_position
        """))
        print("\n📋 Colunas de autotrade_configs:")
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]} (udt: {row[2]})")
    
    await engine.dispose()

asyncio.run(check_enums())
