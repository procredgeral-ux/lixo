"""
Script final: Migração PostgreSQL usando COPY (mais rápido e confiável)
Exporta dados do local para CSV em memória e importa no Railway via COPY
"""
import asyncio
import io
import csv
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings
from core.database import Base
import models

LOCAL_URL = settings.DATABASE_URL
RAILWAY_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"

# Ordem de migração (tabelas pai primeiro)
TABLE_ORDER = [
    'users',
    'accounts', 
    'strategies',
    'indicators',
    'assets',
    'autotrade_configs',
    'strategy_indicators',
    'monitoring_accounts',
    'trades',
    'signals',
    'strategy_performance_snapshots',
    'daily_signal_summary',
]

SKIP_TABLES = ['alembic_version', 'aggregation_job_log']


async def reset_railway():
    """Dropa e recria schema no Railway"""
    print("🗑️  Resetando Railway...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        await conn.execute(text("CREATE SCHEMA public;"))
    
    await engine.dispose()
    print("   ✅ Railway limpo")


async def create_schema():
    """Cria tabelas usando SQLAlchemy"""
    print("🏗️  Criando schema...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    print("   ✅ Schema criado")


async def get_columns(engine, table):
    """Pega colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND table_schema = 'public'
            ORDER BY ordinal_position
        """))
        return {row[0]: row[1] for row in result.fetchall()}


async def export_to_csv(table_name):
    """Exporta tabela do local para CSV em memória"""
    engine = create_async_engine(LOCAL_URL, echo=False)
    
    async with engine.connect() as conn:
        result = await conn.execute(text(f'SELECT * FROM "{table_name}"'))
        rows = result.fetchall()
        columns = result.keys()
    
    await engine.dispose()
    
    if not rows:
        return None, None
    
    # Criar CSV em memória
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t', lineterminator='\n', 
                       quoting=csv.QUOTE_MINIMAL)
    
    # Header
    writer.writerow(columns)
    
    # Dados
    for row in rows:
        processed = []
        for val in row:
            if val is None:
                processed.append('\\N')  # NULL em PostgreSQL COPY
            elif isinstance(val, (datetime, date)):
                processed.append(val.isoformat())
            elif isinstance(val, (list, dict)):
                import json
                processed.append(json.dumps(val))
            elif isinstance(val, bool):
                processed.append('t' if val else 'f')
            else:
                processed.append(str(val).replace('\t', ' ').replace('\n', ' '))
        writer.writerow(processed)
    
    output.seek(0)
    return output.getvalue(), list(columns)


async def import_with_copy(table_name, csv_data, columns):
    """Importa dados via COPY FROM"""
    if not csv_data:
        return 0
    
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    try:
        # Pegar colunas existentes no Railway
        railway_cols = await get_columns(engine, table_name)
        
        # Filtrar apenas colunas que existem
        valid_cols = [c for c in columns if c in railway_cols]
        if not valid_cols:
            print(f"   • {table_name}: sem colunas compatíveis")
            return 0
        
        async with engine.begin() as conn:
            # Desabilitar triggers para esta tabela
            await conn.execute(text(f'ALTER TABLE "{table_name}" DISABLE TRIGGER ALL;'))
            
            # Fazer COPY
            result = await conn.execute(text(f"""
                COPY "{table_name}" ({', '.join(f'"{c}"' for c in valid_cols)})
                FROM STDIN WITH (FORMAT csv, DELIMITER '\t', NULL '\\N', HEADER true)
            """), {"data": csv_data})
            
            # Reabilitar triggers
            await conn.execute(text(f'ALTER TABLE "{table_name}" ENABLE TRIGGER ALL;'))
        
        # Contar linhas
        lines = csv_data.strip().split('\n')
        return len(lines) - 1  # -1 pelo header
        
    except Exception as e:
        print(f"   • {table_name}: erro - {str(e)[:60]}")
        return 0
    finally:
        await engine.dispose()


async def main():
    print("=" * 60)
    print("🚀 MIGRAÇÃO: Local → Railway (via COPY)")
    print("=" * 60)
    
    if input("\n⚠️  Isso APAGA o Railway. Continuar? (yes/no): ") != "yes":
        print("❌ Cancelado")
        return
    
    try:
        # 1. Reset
        await reset_railway()
        
        # 2. Criar schema
        await create_schema()
        
        # 3. Migrar na ordem
        print(f"\n📤 Migrando {len(TABLE_ORDER)} tabelas...")
        total = 0
        
        for table in TABLE_ORDER:
            csv_data, columns = await export_to_csv(table)
            if csv_data:
                count = await import_with_copy(table, csv_data, columns)
                total += count
                print(f"   • {table}: {count} registros")
            else:
                print(f"   • {table}: vazia")
        
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
