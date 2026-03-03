"""
Script para migrar dados do PostgreSQL local para Railway
Exporta dados do local e importa no Railway
"""
import asyncio
import sys
import json
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text, inspect
from core.config import settings

# URL do banco LOCAL (ajuste se necessário)
LOCAL_DATABASE_URL = settings.DATABASE_URL

# URL do Railway (substitua pela sua)
RAILWAY_DATABASE_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"


class DateTimeEncoder(json.JSONEncoder):
    """Encoder para serializar datetime e Decimal"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


async def get_table_columns(engine, table_name):
    """Obter colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """))
        columns = [(row[0], row[1]) for row in result.fetchall()]
        return columns


async def export_table_data(engine, table_name):
    """Exportar dados de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f'SELECT * FROM "{table_name}"'))
        rows = result.fetchall()
        
        # Pegar nomes das colunas
        columns = result.keys()
        
        # Converter para lista de dicionários
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Converter tipos não serializáveis
                if isinstance(value, (datetime, date)):
                    row_dict[col] = value.isoformat()
                elif isinstance(value, Decimal):
                    row_dict[col] = float(value)
                else:
                    row_dict[col] = value
            data.append(row_dict)
        
        return data


async def import_table_data(engine, table_name, data):
    """Importar dados para uma tabela"""
    if not data:
        print(f"   ℹ️  {table_name}: sem dados para importar")
        return 0
    
    async with engine.begin() as conn:
        columns = list(data[0].keys())
        col_names = ', '.join([f'"{c}"' for c in columns])
        placeholders = ', '.join([f':{c}' for c in columns])
        
        inserted = 0
        for row in data:
            try:
                await conn.execute(
                    text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'),
                    row
                )
                inserted += 1
            except Exception as e:
                print(f"   ⚠️  Erro ao inserir em {table_name}: {e}")
        
        return inserted


async def migrate_data():
    """Migrar dados do local para Railway"""
    print("=" * 60)
    print("🔄 MIGRAÇÃO: Local → Railway")
    print("=" * 60)
    
    # Engines
    print("\n🔌 Conectando aos bancos...")
    local_engine = create_async_engine(LOCAL_DATABASE_URL, echo=False)
    railway_engine = create_async_engine(
        RAILWAY_DATABASE_URL, 
        echo=False, 
        connect_args={"ssl": False}
    )
    
    try:
        # Verificar se Railway está vazio
        async with railway_engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM pg_tables 
                WHERE schemaname = 'public'
            """))
            table_count = result.scalar()
            
            if table_count > 0:
                print(f"⚠️  Railway tem {table_count} tabelas. Execute reset_database.py primeiro!")
                return
        
        # Pegar tabelas do local
        print("\n📋 Lendo tabelas do banco local...")
        async with local_engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result.fetchall()]
        
        print(f"   Encontradas {len(tables)} tabelas: {', '.join(tables)}")
        
        # Primeiro: recriar tabelas no Railway usando init_database
        print("\n🏗️  Criando tabelas no Railway...")
        print("   Execute: python init_database.py")
        response = input("   Já executou init_database.py? (yes/no): ")
        if response.lower() != "yes":
            print("❌ Por favor, execute init_database.py primeiro para criar as tabelas.")
            return
        
        # Migrar dados
        print("\n📤 Migrando dados...")
        total_rows = 0
        
        for table in tables:
            print(f"\n📄 {table}:")
            
            # Exportar do local
            data = await export_table_data(local_engine, table)
            print(f"   📥 Exportado: {len(data)} registros do local")
            
            # Importar para Railway
            inserted = await import_table_data(railway_engine, table, data)
            print(f"   📤 Inserido: {inserted} registros no Railway")
            total_rows += inserted
        
        print("\n" + "=" * 60)
        print(f"✅ Migração concluída! Total: {total_rows} registros")
        print("=" * 60)
        
        # Verificação final
        print("\n🔍 Verificando dados no Railway...")
        async with railway_engine.connect() as conn:
            for table in tables[:5]:  # Primeiras 5 tabelas
                result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                count = result.scalar()
                print(f"   • {table}: {count} registros")
        
    except Exception as e:
        print(f"\n❌ Erro na migração: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await local_engine.dispose()
        await railway_engine.dispose()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("=" * 60)
    print("MIGRAÇÃO DE DADOS: Local → Railway")
    print("=" * 60)
    print(f"Local: {LOCAL_DATABASE_URL}")
    print(f"Railway: {RAILWAY_DATABASE_URL.replace(RAILWAY_DATABASE_URL.split(':')[2].split('@')[0], '***')}")
    print("=" * 60)
    
    response = input("\n⚠️  Isso vai copiar TODOS os dados do local para o Railway. Continuar? (yes/no): ")
    if response.lower() == "yes":
        asyncio.run(migrate_data())
    else:
        print("❌ Cancelado.")
