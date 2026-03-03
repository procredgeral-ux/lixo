"""
Script simplificado: Clona dados do PostgreSQL local para Railway
USANDO Base.metadata.create_all() do SQLAlchemy (mais confiável)
"""
import asyncio
import sys
import json
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings
from core.database import Base
import models  # Importa todos os modelos para registrar no metadata

# URLs
LOCAL_URL = settings.DATABASE_URL
RAILWAY_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"


async def drop_all_railway():
    """Dropa todas as tabelas no Railway"""
    print("\n🗑️  Limpando Railway...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.begin() as conn:
        # Desabilitar FK checks
        await conn.execute(text("SET session_replication_role = 'replica';"))
        
        # Dropar todas as tabelas
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'public'
        """))
        tables = [row[0] for row in result.fetchall()]
        
        for table in tables:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
            print(f"   ✅ Dropped: {table}")
        
        await conn.execute(text("SET session_replication_role = 'origin';"))
    
    await engine.dispose()


async def create_schema():
    """Cria schema usando SQLAlchemy (já sabe criar enums, sequences, etc.)"""
    print("\n🏗️  Criando schema...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    print("   ✅ Schema criado")


async def get_tables_local():
    """Lista tabelas do local"""
    engine = create_async_engine(LOCAL_URL, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public' ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
    await engine.dispose()
    return tables


async def get_columns(engine, table):
    """Pega colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table}' AND table_schema = 'public'
        """))
        return [row[0] for row in result.fetchall()]


# Tabelas de sistema para ignorar
SKIP_TABLES = ['alembic_version', 'aggregation_job_log']


async def migrate_table(table_name):
    """Migra uma tabela: exporta do local, importa para Railway"""
    if table_name in SKIP_TABLES:
        print(f"   • {table_name}: ignorada (tabela de sistema)")
        return 0
    
    # Engines
    local_engine = create_async_engine(LOCAL_URL, echo=False)
    railway_engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    try:
        # Pegar colunas de ambos
        local_cols = await get_columns(local_engine, table_name)
        railway_cols = await get_columns(railway_engine, table_name)
        
        # Debug
        if not railway_cols:
            print(f"   • {table_name}: tabela nao existe no Railway")
            return 0
        
        # Colunas comuns
        common_cols = [c for c in local_cols if c in railway_cols]
        if not common_cols:
            print(f"   • {table_name}: pulando (local: {len(local_cols)}, railway: {len(railway_cols)})")
            return 0
        
        # Exportar do local
        async with local_engine.connect() as conn:
            col_str = ', '.join([f'"{c}"' for c in common_cols])
            result = await conn.execute(text(f'SELECT {col_str} FROM "{table_name}"'))
            rows = result.fetchall()
        
        if not rows:
            print(f"   • {table_name}: vazia")
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
        
        # Importar para Railway - uma transacao por tabela
        col_names = ', '.join([f'"{c}"' for c in common_cols])
        placeholders = ', '.join([f':{c}' for c in common_cols])
        
        inserted = 0
        for row in data:
            try:
                async with railway_engine.begin() as conn:
                    # Converter datetime strings de volta
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
            except Exception as e:
                # Mostrar primeiros erros para debug
                if inserted == 0 and len(str(e)) > 0:
                    print(f"   ⚠️  Erro: {str(e)[:80]}")
                pass
        
        print(f"   • {table_name}: {inserted}/{len(data)} registros")
        return inserted
        
    finally:
        await local_engine.dispose()
        await railway_engine.dispose()


async def verify():
    """Mostra resumo"""
    print("\n🔍 Verificando...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
        
        print(f"\n📊 {len(tables)} tabelas no Railway:")
        for table in tables:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            count = result.scalar()
            print(f"   • {table}: {count} registros")
    
    await engine.dispose()


async def main():
    """Processo completo"""
    print("=" * 60)
    print("🚀 CLONE: Local → Railway")
    print("=" * 60)
    
    if input("\n⚠️  Isso APAGA o Railway. Continuar? (yes/no): ") != "yes":
        print("❌ Cancelado")
        return
    
    try:
        # 1. Drop
        await drop_all_railway()
        
        # 2. Criar schema (SQLAlchemy cria tudo: enums, sequences, tabelas)
        await create_schema()
        
        # 3. Pegar tabelas do local
        tables = await get_tables_local()
        print(f"\n📋 {len(tables)} tabelas para migrar")
        
        # 4. Migrar dados
        print("\n📤 Migrando...")
        
        # Desabilitar FK checks
        engine_fk = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
        async with engine_fk.begin() as conn:
            await conn.execute(text("SET session_replication_role = 'replica';"))
        await engine_fk.dispose()
        
        total = 0
        for table in tables:
            count = await migrate_table(table)
            total += count
        
        # Reabilitar FK checks
        engine_fk = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
        async with engine_fk.begin() as conn:
            await conn.execute(text("SET session_replication_role = 'origin';"))
        await engine_fk.dispose()
        
        # 5. Verificar
        await verify()
        
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
