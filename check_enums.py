"""
Verifica enums no Railway
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

RAILWAY_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"

async def check_enums():
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.connect() as conn:
        # Listar todos os enums
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
    
    await engine.dispose()

asyncio.run(check_enums())
