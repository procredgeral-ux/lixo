"""
Script unificado: Cria tabelas no Railway + Migra dados do local
Faz TUDO automaticamente em uma execução
"""
import asyncio
import sys
import json
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable
from core.config import settings
from core.database import Base
import models  # Importar todos os modelos

# URL do banco LOCAL
LOCAL_DATABASE_URL = settings.DATABASE_URL

# URL do Railway
RAILWAY_DATABASE_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"


async def get_table_columns(engine, table_name):
    """Obter colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table_name}' AND table_schema = 'public'
            ORDER BY ordinal_position
        """))
        return [row[0] for row in result.fetchall()]


async def export_table_data(engine, table_name, columns):
    """Exportar dados de uma tabela (mantendo tipos originais)"""
    async with engine.connect() as conn:
        col_str = ', '.join([f'"{c}"' for c in columns])
        result = await conn.execute(text(f'SELECT {col_str} FROM "{table_name}"'))
        rows = result.fetchall()
        
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Manter datetime como string ISO para serialização JSON
                if isinstance(value, (datetime, date)):
                    row_dict[col] = value.isoformat() if value else None
                elif isinstance(value, Decimal):
                    row_dict[col] = float(value)
                elif isinstance(value, list) or isinstance(value, dict):
                    # JSON fields - manter como objeto, será serializado depois
                    row_dict[col] = json.dumps(value) if value else None
                else:
                    row_dict[col] = value
            data.append(row_dict)
        
        return data


async def import_table_data(engine, table_name, data, columns):
    """Importar dados para uma tabela"""
    if not data:
        return 0
    
    col_names = ', '.join([f'"{c}"' for c in columns])
    placeholders = ', '.join([f':{c}' for c in columns])
    
    inserted = 0
    errors = 0
    
    async with engine.begin() as conn:
        for row in data:
            try:
                # Filtrar apenas colunas que existem e converter tipos
                filtered_row = {}
                for k, v in row.items():
                    if k in columns:
                        # Converter strings ISO de volta para datetime
                        if v and isinstance(v, str) and ('T' in v or len(v) == 10):
                            try:
                                if 'T' in v:
                                    filtered_row[k] = datetime.fromisoformat(v.replace('Z', '+00:00').replace('+00:00', ''))
                                else:
                                    filtered_row[k] = date.fromisoformat(v)
                            except:
                                filtered_row[k] = v
                        else:
                            filtered_row[k] = v
                
                await conn.execute(
                    text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'),
                    filtered_row
                )
                inserted += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"   ⚠️  Erro: {str(e)[:100]}")
    
    if errors > 3:
        print(f"   ⚠️  ... e mais {errors-3} erros")
    
    return inserted


async def verify_migration():
    """Verificar dados migrados"""
    print("\n🔍 Verificando migração...")
    
    engine = create_async_engine(
        RAILWAY_DATABASE_URL, 
        echo=False, 
        connect_args={"ssl": False}
    )
    
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
        
        print("\n📊 Resumo do Railway:")
        for table in tables:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            count = result.scalar()
            print(f"   • {table}: {count} registros")
    
    await engine.dispose()


async def full_migration():
    """Execução completa: Criar tabelas + Migrar dados"""
    print("=" * 60)
    print("🚀 MIGRAÇÃO COMPLETA: Local → Railway")
    print("=" * 60)
    print(f"Origem: {LOCAL_DATABASE_URL}")
    print(f"Destino: {RAILWAY_DATABASE_URL.split('@')[1]}")
    print("=" * 60)
    
    # Confirmar
    response = input("\n⚠️  Isso vai APAGAR dados existentes no Railway e recriar tudo. Continuar? (yes/no): ")
    if response.lower() != "yes":
        print("❌ Cancelado.")
        return
    
    try:
        # Engines
        local_engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
        railway_engine = create_async_engine(
            RAILWAY_DATABASE_URL, 
            echo=False, 
            connect_args={"ssl": False}
        )
        
        # 1. Listar tabelas do local
        print("\n📋 Lendo tabelas do banco local...")
        async with local_engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result.fetchall()]
        
        print(f"   Encontradas {len(tables)} tabelas")
        
        # 2. Criar tabelas no Railway
        print("\n🏗️  Criando tabelas no Railway...")
        async with railway_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("   ✅ Tabelas criadas")
        
        # 3. Migrar dados tabela por tabela
        print("\n📤 Migrando dados...")
        total_imported = 0
        
        for table in tables:
            # Pegar colunas de ambos os bancos
            local_cols = await get_table_columns(local_engine, table)
            railway_cols = await get_table_columns(railway_engine, table)
            
            # Usar apenas colunas que existem em ambos
            common_cols = [c for c in local_cols if c in railway_cols]
            
            if not common_cols:
                print(f"   • {table}: pulando (sem colunas compatíveis)")
                continue
            
            # Exportar apenas colunas comuns
            data = await export_table_data(local_engine, table, common_cols)
            
            # Importar
            inserted = await import_table_data(railway_engine, table, data, common_cols)
            total_imported += inserted
            
            if len(data) > 0:
                print(f"   • {table}: {inserted}/{len(data)} registros ({len(common_cols)} colunas)")
        
        # 4. Verificar
        await verify_migration()
        
        print("\n" + "=" * 60)
        print(f"✅ MIGRAÇÃO CONCLUÍDA!")
        print(f"   Total: {total_imported} registros")
        print("=" * 60)
        
        await local_engine.dispose()
        await railway_engine.dispose()
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    asyncio.run(full_migration())
