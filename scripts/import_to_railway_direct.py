#!/usr/bin/env python3
"""Importar dados diretamente no Railway PostgreSQL"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

# Pegar DATABASE_URL do Railway
print("=" * 60)
print("IMPORTAÇÃO AUTOMÁTICA PARA RAILWAY")
print("=" * 60)
print("\nDigite a DATABASE_URL do Railway Postgres:")
print("(copie do Railway Dashboard → Postgres → Connect)")
print("Formato: postgresql://user:pass@host:port/database")
db_url = input("> ").strip()

if not db_url:
    print("❌ URL não fornecida. Cancelado.")
    sys.exit(1)

# Converter para asyncpg se necessário
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql://", 1)

# Ler dados
json_file = Path(__file__).parent / 'migration_all_data.json'
with open(json_file, 'r') as f:
    data = json.load(f)

users = data['users']
accounts = data['accounts']
monitoring = data['monitoring_accounts']

print(f"\n📊 Dados a importar:")
print(f"   Users: {len(users)}")
print(f"   Accounts: {len(accounts)}")
print(f"   Monitoring: {len(monitoring)}")

confirm = input(f"\n⚠️  Isso vai APAGAR dados existentes. Continuar? (s/N): ")
if confirm.lower() != 's':
    print("❌ Cancelado")
    sys.exit(0)

async def import_data():
    print(f"\n🔗 Conectando ao Railway...")
    
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return
    
    try:
        # Limpar tabelas
        print("🧹 Limpando tabelas...")
        await conn.execute("DELETE FROM monitoring_accounts")
        await conn.execute("DELETE FROM accounts")
        await conn.execute("DELETE FROM users")
        print("   ✅ Tabelas limpas")
        
        # Inserir users
        print(f"\n📥 Inserindo {len(users)} users...")
        for user in users:
            try:
                cols = [k for k, v in user.items() if v is not None]
                vals = [v for k, v in user.items() if v is not None]
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
            except Exception as e:
                print(f"   ❌ Erro no user {user.get('id', '?')[:8]}: {e}")
        
        # Inserir accounts
        print(f"\n📥 Inserindo {len(accounts)} accounts...")
        inserted_acc = 0
        for acc in accounts:
            try:
                cols = [k for k, v in acc.items() if v is not None]
                vals = [v for k, v in acc.items() if v is not None]
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
                inserted_acc += 1
            except Exception as e:
                print(f"   ❌ Erro na account {acc.get('id', '?')[:8]}: {e}")
        
        print(f"   ✅ {inserted_acc} accounts inseridas")
        
        # Inserir monitoring
        print(f"\n📥 Inserindo {len(monitoring)} monitoring_accounts...")
        inserted_mon = 0
        for mon in monitoring:
            try:
                cols = [k for k, v in mon.items() if v is not None]
                vals = [v for k, v in mon.items() if v is not None]
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO monitoring_accounts ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
                inserted_mon += 1
            except Exception as e:
                print(f"   ❌ Erro no monitoring {mon.get('id', '?')[:8]}: {e}")
        
        print(f"   ✅ {inserted_mon} monitoring_accounts inseridos")
        
        # Verificar
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        acc_count = await conn.fetchval("SELECT COUNT(*) FROM accounts")
        mon_count = await conn.fetchval("SELECT COUNT(*) FROM monitoring_accounts")
        
        print(f"\n" + "=" * 60)
        print("✅ IMPORTAÇÃO CONCLUÍDA!")
        print("=" * 60)
        print(f"📊 Total no Railway:")
        print(f"   Users: {user_count}")
        print(f"   Accounts: {acc_count}")
        print(f"   Monitoring: {mon_count}")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(import_data())
    input("\nPressione Enter para sair...")
