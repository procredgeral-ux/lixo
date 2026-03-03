"""
Migração ESSENCIAL: Apenas tabelas principais do sistema
"""
import asyncio
import json
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings
from core.database import Base
import models

LOCAL_URL = settings.DATABASE_URL
RAILWAY_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"

# Tabelas essenciais (ordem importante: pais primeiro)
ESSENTIAL_TABLES = [
    'users',              # pai
    'accounts',           # filho de users
    'strategies',         # filho de accounts
    'indicators',         # independente
    'monitoring_accounts', # independente
    'autotrade_configs',  # filho de accounts e strategies
]


async def reset_railway():
    """Dropa tudo no Railway"""
    print("🗑️  Limpando Railway...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = 'replica';"))
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'public'
        """))
        tables = [row[0] for row in result.fetchall()]
        for table in tables:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
        await conn.execute(text("SET session_replication_role = 'origin';"))
    
    await engine.dispose()
    print(f"   ✅ {len(tables)} tabelas removidas")


async def create_schema():
    """Cria tabelas usando SQLAlchemy"""
    print("🏗️  Criando schema...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("   ✅ Tabelas criadas")


async def get_columns(engine, table):
    """Pega colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table}' AND table_schema = 'public'
        """))
        return [row[0] for row in result.fetchall()]


async def migrate_table(table_name):
    """Migra uma tabela"""
    print(f"   📥 {table_name}...", end=" ")
    
    local_engine = create_async_engine(LOCAL_URL, echo=False)
    railway_engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    try:
        # Pegar colunas
        local_cols = await get_columns(local_engine, table_name)
        railway_cols = await get_columns(railway_engine, table_name)
        common_cols = [c for c in local_cols if c in railway_cols]
        
        if not common_cols:
            print("pulando (sem colunas)")
            return 0
        
        # Exportar do local
        async with local_engine.connect() as conn:
            col_str = ', '.join([f'"{c}"' for c in common_cols])
            result = await conn.execute(text(f'SELECT {col_str} FROM "{table_name}"'))
            rows = result.fetchall()
        
        if not rows:
            print("vazia")
            return 0
        
        # Converter dados
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(common_cols):
                val = row[i]
                if isinstance(val, (datetime, date)):
                    row_dict[col] = val.isoformat() if val else None
                elif isinstance(val, Decimal):
                    row_dict[col] = float(val)
                elif isinstance(val, (list, dict)):
                    row_dict[col] = json.dumps(val) if val else None
                else:
                    row_dict[col] = val
            data.append(row_dict)
        
        # Importar para Railway
        col_names = ', '.join([f'"{c}"' for c in common_cols])
        placeholders = ', '.join([f':{c}' for c in common_cols])
        
        inserted = 0
        async with railway_engine.begin() as conn:
            # Desabilitar triggers
            await conn.execute(text(f'ALTER TABLE "{table_name}" DISABLE TRIGGER ALL;'))
            
            for row in data:
                try:
                    # Converter datetime de volta
                    processed = {}
                    for k, v in row.items():
                        if v and isinstance(v, str) and 'T' in v:
                            try:
                                processed[k] = datetime.fromisoformat(v.replace('Z', ''))
                            except:
                                processed[k] = v
                        elif v and isinstance(v, str) and len(v) == 10 and v.count('-') == 2:
                            try:
                                processed[k] = date.fromisoformat(v)
                            except:
                                processed[k] = v
                        else:
                            processed[k] = v
                    
                    await conn.execute(
                        text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'),
                        processed
                    )
                    inserted += 1
                except Exception:
                    pass  # Ignora erros individuais
            
            # Reabilitar triggers
            await conn.execute(text(f'ALTER TABLE "{table_name}" ENABLE TRIGGER ALL;'))
        
        print(f"{inserted}/{len(data)} registros")
        return inserted
        
    except Exception as e:
        print(f"erro: {str(e)[:50]}")
        return 0
    finally:
        await local_engine.dispose()
        await railway_engine.dispose()


async def main():
    print("=" * 60)
    print("🚀 MIGRAÇÃO ESSENCIAL: Local → Railway")
    print("=" * 60)
    
    if input("\n⚠️  Isso APAGA o Railway. Continuar? (yes/no): ") != "yes":
        print("❌ Cancelado")
        return
    
    try:
        # 1. Reset
        await reset_railway()
        
        # 2. Criar schema
        await create_schema()
        
        # 3. Migrar tabelas essenciais
        print(f"\n📤 Migrando {len(ESSENTIAL_TABLES)} tabelas essenciais...")
        total = 0
        
        for table in ESSENTIAL_TABLES:
            count = await migrate_table(table)
            total += count
        
        print(f"\n{'=' * 60}")
        print(f"✅ CONCLUÍDO! Total: {total} registros")
        print(f"{'=' * 60}")
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    asyncio.run(main())
