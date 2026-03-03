"""
Script completo: Clona schema + dados do PostgreSQL local para Railway
1. Dropa todas as tabelas no Railway
2. Recria schema IDENTICO ao local (usando pg_dump/pg_restore ou SQL)
3. Migra todos os dados
"""
import asyncio
import sys
import json
import subprocess
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings

# URLs
LOCAL_DATABASE_URL = settings.DATABASE_URL
RAILWAY_DATABASE_URL = "postgresql://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"


async def get_tables_local():
    """Listar tabelas do banco local"""
    engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
    await engine.dispose()
    return tables


async def get_table_schema(table_name):
    """Obter schema CREATE TABLE de uma tabela do local"""
    engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
    
    async with engine.connect() as conn:
        # Pegar definicao da tabela
        result = await conn.execute(text(f"""
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' AND table_schema = 'public'
            ORDER BY ordinal_position
        """))
        columns = result.fetchall()
        
        # Pegar constraints
        result = await conn.execute(text(f"""
            SELECT 
                tc.constraint_name,
                tc.constraint_type,
                kcu.column_name
            FROM information_schema.table_constraints tc
            LEFT JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = '{table_name}' AND tc.table_schema = 'public'
        """))
        constraints = result.fetchall()
        
    await engine.dispose()
    return columns, constraints


async def drop_all_tables_railway():
    """Dropa todas as tabelas no Railway"""
    print("\n🗑️  Dropando tabelas no Railway...")
    
    engine = create_async_engine(
        RAILWAY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        connect_args={"ssl": False}
    )
    
    async with engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = 'replica';"))
        
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """))
        tables = [row[0] for row in result.fetchall()]
        
        for table in tables:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
            print(f"   ✅ Dropped: {table}")
        
        await conn.execute(text("SET session_replication_role = 'origin';"))
    
    await engine.dispose()
    print("   ✅ Todas as tabelas removidas")


async def get_create_table_sql(table_name):
    """Gerar CREATE TABLE SQL a partir do banco local"""
    engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
    
    async with engine.connect() as conn:
        # Pegar colunas
        result = await conn.execute(text(f"""
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' AND table_schema = 'public'
            ORDER BY ordinal_position
        """))
        columns = result.fetchall()
        
        # Gerar SQL de CREATE TABLE
        col_defs = []
        for col in columns:
            col_name, data_type, is_nullable, default, char_len, num_prec, num_scale = col
            
            # Mapear tipos
            type_str = data_type
            if data_type == 'character varying' and char_len:
                type_str = f'VARCHAR({char_len})'
            elif data_type == 'numeric' and num_prec:
                type_str = f'NUMERIC({num_prec},{num_scale or 0})'
            elif data_type == 'ARRAY':
                type_str = 'JSON'  # Converter ARRAY para JSON
            
            # Construir definicao
            col_def = f'"{col_name}" {type_str}'
            
            if is_nullable == 'NO':
                col_def += ' NOT NULL'
            
            if default:
                col_def += f' DEFAULT {default}'
            
            col_defs.append(col_def)
        
        # Pegar PRIMARY KEY
        result = await conn.execute(text(f"""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = '{table_name}' 
                AND tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = 'public'
        """))
        pk_cols = [row[0] for row in result.fetchall()]
        
        if pk_cols:
            col_defs.append(f'PRIMARY KEY ({", ".join([f"\"{c}\"" for c in pk_cols])})')
        
    await engine.dispose()
    
    create_sql = f'CREATE TABLE "{table_name}" (' + ', '.join(col_defs) + ')'
    return create_sql


async def create_tables_from_local():
    """Cria tabelas no Railway com mesmo schema do local"""
    print("\n🏗️  Criando tabelas identicas ao local...")
    
    tables = await get_tables_local()
    
    engine = create_async_engine(
        RAILWAY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        connect_args={"ssl": False}
    )
    
    async with engine.begin() as conn:
        for table in tables:
            try:
                create_sql = await get_create_table_sql(table)
                await conn.execute(text(create_sql))
                print(f"   ✅ Created: {table}")
            except Exception as e:
                print(f"   ❌ Erro em {table}: {e}")
    
    await engine.dispose()
    print("   ✅ Schema criado no Railway")
    return True


async def export_data_simple(table_name):
    """Exportar dados usando pg_dump para CSV/INSERT"""
    print(f"   📥 {table_name}...")
    
    try:
        # Usar COPY TO para exportar dados
        engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
        
        async with engine.connect() as conn:
            result = await conn.execute(text(f'SELECT * FROM "{table_name}"'))
            rows = result.fetchall()
            columns = result.keys()
        
        await engine.dispose()
        
        # Converter para dicionarios
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                if isinstance(value, (datetime, date)):
                    row_dict[col] = value.isoformat() if value else None
                elif isinstance(value, Decimal):
                    row_dict[col] = float(value)
                elif isinstance(value, (list, dict)):
                    row_dict[col] = json.dumps(value) if value else None
                else:
                    row_dict[col] = value
            data.append(row_dict)
        
        return data, list(columns)
        
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        return [], []


async def import_data_simple(table_name, data, columns):
    """Importar dados para Railway"""
    if not data:
        return 0
    
    engine = create_async_engine(
        RAILWAY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        connect_args={"ssl": False}
    )
    
    col_names = ', '.join([f'"{c}"' for c in columns])
    placeholders = ', '.join([f':{c}' for c in columns])
    
    inserted = 0
    
    async with engine.begin() as conn:
        for row in data:
            try:
                # Converter strings ISO de volta para datetime
                processed_row = {}
                for k, v in row.items():
                    if v and isinstance(v, str):
                        if 'T' in v and len(v) > 10:
                            try:
                                processed_row[k] = datetime.fromisoformat(v.replace('Z', ''))
                            except:
                                processed_row[k] = v
                        elif len(v) == 10 and v.count('-') == 2:
                            try:
                                processed_row[k] = date.fromisoformat(v)
                            except:
                                processed_row[k] = v
                        else:
                            processed_row[k] = v
                    else:
                        processed_row[k] = v
                
                await conn.execute(
                    text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'),
                    processed_row
                )
                inserted += 1
            except Exception as e:
                # Silencioso para nao poluir output
                pass
    
    await engine.dispose()
    return inserted


async def clone_database():
    """Processo completo de clonagem"""
    print("=" * 60)
    print("🚀 CLONAGEM COMPLETA: Local → Railway")
    print("=" * 60)
    
    confirm = input("\n⚠️  Isso vai APAGAR todo o Railway e recriar do zero. Continuar? (yes/no): ")
    if confirm != "yes":
        print("❌ Cancelado.")
        return
    
    try:
        # 1. Listar tabelas locais
        print("\n📋 Analisando banco local...")
        tables = await get_tables_local()
        print(f"   {len(tables)} tabelas encontradas: {', '.join(tables)}")
        
        # 2. Drop todas as tabelas no Railway
        await drop_all_tables_railway()
        
        # 3. Criar schema identico
        success = await create_tables_from_local()
        if not success:
            print("\n❌ Falha ao criar schema. Abortando.")
            return
        
        # 4. Migrar dados
        print("\n📤 Migrando dados...")
        total = 0
        
        for table in tables:
            data, columns = await export_data_simple(table)
            if data:
                inserted = await import_data_simple(table, data, columns)
                total += inserted
                print(f"   • {table}: {inserted}/{len(data)} registros")
            else:
                print(f"   • {table}: vazia")
        
        print("\n" + "=" * 60)
        print(f"✅ CLONAGEM CONCLUÍDA!")
        print(f"   Total: {total} registros migrados")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    asyncio.run(clone_database())
