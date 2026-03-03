#!/usr/bin/env python3
"""Importar dados para Railway (automático com credenciais)"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

# Credenciais do Railway
DB_URL = "postgresql://postgres:lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE@interchange.proxy.rlwy.net:17755/railway"

print("=" * 60)
print("IMPORTAÇÃO AUTOMÁTICA PARA RAILWAY")
print("=" * 60)

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

async def import_data():
    print(f"\n🔗 Conectando ao Railway PostgreSQL...")
    
    try:
        conn = await asyncpg.connect(DB_URL, ssl='require')
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return
    
    try:
        # Limpar tabelas em ordem (filhos primeiro)
        print("🧹 Limpando tabelas...")
        await conn.execute("DELETE FROM autotrade_configs")
        await conn.execute("DELETE FROM strategy_indicators")
        await conn.execute("DELETE FROM strategies")
        await conn.execute("DELETE FROM monitoring_accounts")
        await conn.execute("DELETE FROM accounts")
        await conn.execute("DELETE FROM users")
        print("   ✅ Tabelas limpas")
        
        # Inserir users
        print(f"\n📥 Inserindo {len(users)} users...")
        for user in users:
            try:
                # Remover campos que podem não existir no Railway
                user_clean = {k: v for k, v in user.items() if v is not None and k not in ['last_activity_timestamp']}
                
                cols = list(user_clean.keys())
                vals = list(user_clean.values())
                
                # Converter datas e números
                from datetime import datetime
                for i, v in enumerate(vals):
                    if isinstance(v, str) and 'T' in v:
                        try:
                            vals[i] = datetime.fromisoformat(v)
                        except:
                            pass
                    # Converter campos numéricos
                    if cols[i] in ['balance_demo', 'balance_real']:
                        try:
                            vals[i] = float(v)
                        except:
                            vals[i] = 0.0
                    if cols[i] in ['uid', 'platform']:
                        try:
                            vals[i] = int(v)
                        except:
                            vals[i] = 0
                
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
            except Exception as e:
                print(f"   ❌ Erro no user {user.get('email', '?')}: {e}")
        print(f"   ✅ Users inseridos")
        
        # Inserir accounts
        print(f"\n📥 Inserindo {len(accounts)} accounts...")
        inserted_acc = 0
        for acc in accounts:
            try:
                # Remover campos que podem não existir no Railway
                acc_clean = {k: v for k, v in acc.items() if v is not None and k not in ['last_activity_timestamp']}
                
                cols = list(acc_clean.keys())
                vals = list(acc_clean.values())
                
                # Converter datas e números
                from datetime import datetime
                for i, v in enumerate(vals):
                    if isinstance(v, str) and 'T' in v:
                        try:
                            vals[i] = datetime.fromisoformat(v)
                        except:
                            pass
                    # Converter campos numéricos de accounts
                    if cols[i] in ['balance_demo', 'balance_real']:
                        try:
                            vals[i] = float(v)
                        except:
                            vals[i] = 0.0
                    if cols[i] in ['uid', 'platform']:
                        try:
                            vals[i] = int(v)
                        except:
                            vals[i] = 0
                
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
                inserted_acc += 1
            except Exception as e:
                print(f"   ❌ Erro na account: {e}")
        print(f"   ✅ {inserted_acc} accounts inseridas")
        
        # Inserir monitoring
        print(f"\n📥 Inserindo {len(monitoring)} monitoring_accounts...")
        inserted_mon = 0
        for mon in monitoring:
            try:
                cols = [k for k, v in mon.items() if v is not None]
                vals = [v for k, v in mon.items() if v is not None]
                
                # Converter account_type para uppercase (PAYOUT, ATIVOS)
                for i, v in enumerate(vals):
                    if cols[i] == 'account_type':
                        vals[i] = v.upper()
                    elif isinstance(v, str) and 'T' in v:
                        try:
                            from datetime import datetime
                            vals[i] = datetime.fromisoformat(v)
                        except:
                            pass
                
                placeholders = ", ".join([f"${i+1}" for i in range(len(vals))])
                
                await conn.execute(
                    f"INSERT INTO monitoring_accounts ({', '.join(cols)}) VALUES ({placeholders})",
                    *vals
                )
                inserted_mon += 1
            except Exception as e:
                print(f"   ❌ Erro no monitoring: {e}")
        print(f"   ✅ {inserted_mon} monitoring_accounts inseridos")
        
        # Verificar
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        acc_count = await conn.fetchval("SELECT COUNT(*) FROM accounts")
        mon_count = await conn.fetchval("SELECT COUNT(*) FROM monitoring_accounts")
        
        print(f"\n" + "=" * 60)
        print("✅ IMPORTAÇÃO CONCLUÍDA!")
        print("=" * 60)
        print(f"📊 Total no Railway:")
        print(f"   👤 Users: {user_count}")
        print(f"   💼 Accounts: {acc_count}")
        print(f"   📡 Monitoring: {mon_count}")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(import_data())
