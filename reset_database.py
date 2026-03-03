"""
Script para consultar e resetar banco PostgreSQL no Railway
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from urllib.parse import urlparse


# URL do Railway (substitua pela sua DATABASE_URL do Railway)
RAILWAY_DATABASE_URL = "postgresql+asyncpg://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"


async def consultar_banco():
    """Consultar banco Railway - listar tabelas e dados"""
    print("=" * 60)
    print("� CONSULTANDO BANCO RAILWAY")
    print("=" * 60)
    print(f"Database: {RAILWAY_DATABASE_URL.replace(RAILWAY_DATABASE_URL.split(':')[2].split('@')[0], '***')}")
    print()
    
    try:
        engine = create_async_engine(
            RAILWAY_DATABASE_URL, 
            echo=False, 
            connect_args={"ssl": False}
        )
        
        async with engine.connect() as conn:
            # Listar tabelas
            print("📋 TABELAS ENCONTRADAS:")
            result = await conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result.fetchall()]
            
            if not tables:
                print("   ⚠️  Nenhuma tabela encontrada")
                return
            
            for table in tables:
                # Contar registros
                count_result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                count = count_result.scalar()
                print(f"   • {table}: {count} registros")
            
            print(f"\n📊 Total: {len(tables)} tabelas")
            
            # Mostrar alguns dados de tabelas importantes
            for table in ['users', 'accounts', 'trades', 'signals']:
                if table in tables:
                    print(f"\n📄 Últimos dados de '{table}':")
                    result = await conn.execute(text(f'SELECT * FROM "{table}" LIMIT 3'))
                    rows = result.fetchall()
                    for row in rows:
                        print(f"   {row}")
                        
        await engine.dispose()
        print("\n✅ Consulta concluída!")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()


async def resetar_banco():
    """Drop all tables no Railway"""
    print("\n" + "=" * 60)
    print("🗑️  RESETAR BANCO RAILWAY")
    print("=" * 60)
    
    response = input("⚠️  Digite 'RESET' para confirmar: ")
    if response != "RESET":
        print("❌ Cancelado.")
        return
    
    try:
        engine = create_async_engine(
            RAILWAY_DATABASE_URL, 
            echo=False, 
            connect_args={"ssl": False}
        )
        
        async with engine.begin() as conn:
            print("🗑️  Dropando tabelas...")
            
            # Desativar FK checks
            await conn.execute(text("SET session_replication_role = 'replica';"))
            
            # Pegar tabelas
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
        print("\n✅ Banco resetado! Execute init_database.py para recriar")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("=" * 60)
    print("RAILWAY DATABASE TOOL")
    print("=" * 60)
    print("1. Consultar banco (ver tabelas)")
    print("2. Resetar banco (APAGAR TUDO)")
    print("q. Sair")
    print("=" * 60)
    
    opcao = input("\nEscolha: ").strip()
    
    if opcao == "1":
        asyncio.run(consultar_banco())
    elif opcao == "2":
        asyncio.run(resetar_banco())
    else:
        print("Saindo...")
