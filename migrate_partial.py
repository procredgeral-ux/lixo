"""
Migração PARCIAL: Apenas 6 tabelas essenciais (sem apagar nada)
Verifica se tabela está vazia e só migra se necessário
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

# Apenas 6 tabelas essenciais
ESSENTIAL_TABLES = [
    'users',
    'accounts',
    'strategies',
    'indicators',
    'monitoring_accounts',
    'autotrade_configs',
]


async def create_schema_if_missing():
    """Cria schema se não existir (sem apagar)"""
    print("🏗️  Verificando schema...")
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("   ✅ Schema verificado")


async def get_columns(engine, table):
    """Pega colunas de uma tabela"""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table}' AND table_schema = 'public'
        """))
        return [row[0] for row in result.fetchall()]


async def count_railway_table(table_name):
    """Conta registros no Railway"""
    engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            return result.scalar()
    except:
        return -1  # Tabela não existe
    finally:
        await engine.dispose()


async def migrate_table(table_name):
    """Migra uma tabela se estiver vazia"""
    print(f"   📥 {table_name}...", end=" ")
    
    # Verificar se já tem dados no Railway
    railway_count = await count_railway_table(table_name)
    if railway_count > 0:
        print(f"já tem {railway_count} registros (pulando)")
        return 0
    elif railway_count == -1:
        print("tabela não existe")
        return 0
    
    local_engine = create_async_engine(LOCAL_URL, echo=False)
    railway_engine = create_async_engine(RAILWAY_URL, echo=False, connect_args={"ssl": False})
    
    try:
        # Pegar colunas
        local_cols = await get_columns(local_engine, table_name)
        railway_cols = await get_columns(railway_engine, table_name)
        common_cols = [c for c in local_cols if c in railway_cols]
        
        if not common_cols:
            print("sem colunas compatíveis")
            return 0
        
        # Exportar do local
        async with local_engine.connect() as conn:
            col_str = ', '.join([f'"{c}"' for c in common_cols])
            result = await conn.execute(text(f'SELECT {col_str} FROM "{table_name}"'))
            rows = result.fetchall()
        
        if not rows:
            print("vazia")
            return 0
        
        # Converter dados (mapear tipos específicos)
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(common_cols):
                val = row[i]
                if isinstance(val, Decimal):
                    row_dict[col] = float(val)
                elif isinstance(val, (list, dict)):
                    row_dict[col] = json.dumps(val) if val else None
                elif col == 'cooldown_seconds':
                    # Railway espera string, não int
                    row_dict[col] = str(val) if val is not None else "0"
                elif col in ['last_executed', 'last_trade_time', 'last_activity_timestamp'] and isinstance(val, str):
                    # Converter string para datetime
                    try:
                        row_dict[col] = datetime.fromisoformat(val.replace(' ', 'T').replace('Z', ''))
                    except:
                        row_dict[col] = val
                elif col == 'last_trade_date' and isinstance(val, str):
                    # Converter string para date
                    try:
                        row_dict[col] = date.fromisoformat(val)
                    except:
                        row_dict[col] = val
                elif col == 'account_type' and table_name == 'monitoring_accounts':
                    # Mapear valores do enum - Railway espera maiusculo
                    val_str = str(val).upper() if val else 'PAYOUT'
                    if val_str in ['PAYOUT', 'ATIVOS']:
                        row_dict[col] = val_str
                    else:
                        row_dict[col] = 'PAYOUT'  # default
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
                    await conn.execute(
                        text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'),
                        row  # Passa dados direto, sem conversão
                    )
                    inserted += 1
                except Exception as e:
                    # Mostrar primeiro erro com detalhes
                    if inserted == 0:
                        print(f"\n   ⚠️  Erro: {str(e)[:120]}")
                        print(f"   📋 Dados: {list(row.keys())}")
                        # Mostrar tipos dos valores
                        for k, v in row.items():
                            print(f"      {k}: {type(v).__name__} = {str(v)[:40]}")
                    break  # Para no primeiro erro
            
            # Reabilitar triggers
            await conn.execute(text(f'ALTER TABLE "{table_name}" ENABLE TRIGGER ALL;'))
        
        print(f"{inserted}/{len(data)} registros migrados")
        return inserted
        
    except Exception as e:
        print(f"erro: {str(e)[:50]}")
        return 0
    finally:
        await local_engine.dispose()
        await railway_engine.dispose()


async def main():
    print("=" * 60)
    print("🚀 MIGRAÇÃO PARCIAL: Apenas tabelas vazias")
    print("=" * 60)
    
    try:
        # 1. Criar schema se não existir (sem apagar)
        await create_schema_if_missing()
        
        # 2. Migrar apenas tabelas vazias
        print(f"\n📤 Verificando {len(ESSENTIAL_TABLES)} tabelas...")
        total = 0
        
        for table in ESSENTIAL_TABLES:
            count = await migrate_table(table)
            total += count
        
        print(f"\n{'=' * 60}")
        print(f"✅ CONCLUÍDO! {total} novos registros migrados")
        print(f"{'=' * 60}")
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    asyncio.run(main())
