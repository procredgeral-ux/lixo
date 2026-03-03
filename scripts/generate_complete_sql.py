#!/usr/bin/env python3
"""Gerar SQL para importar users, accounts e monitoring_accounts no Railway"""
import json
from pathlib import Path

# Ler dados exportados
json_file = Path(__file__).parent / 'migration_all_data.json'
with open(json_file, 'r') as f:
    data = json.load(f)

users = data.get('users', [])
accounts = data.get('accounts', [])
monitoring = data.get('monitoring_accounts', [])

sql_lines = [
    "-- Migração PostgreSQL Local → Railway",
    "-- Tabelas: users, accounts, monitoring_accounts",
    "",
    "BEGIN;",
    "",
    "-- Desativar triggers temporariamente (se houver)",
    "SET session_replication_role = replica;",
    "",
    "-- Limpar tabelas na ordem correta (filhos primeiro)",
    "DELETE FROM monitoring_accounts;",
    "DELETE FROM accounts;",
    "DELETE FROM users;",
    "",
    f"-- Inserindo {len(users)} users",
]

# Gerar INSERTs para users
for user in users:
    cols = []
    vals = []
    
    for k, v in user.items():
        if v is None:
            continue
        cols.append(f'"{k}"')
        
        if isinstance(v, bool):
            vals.append('true' if v else 'false')
        elif isinstance(v, (int, float)):
            vals.append(str(v))
        elif isinstance(v, str):
            safe_v = v.replace("'", "''")
            vals.append(f"'{safe_v}'")
        else:
            vals.append(f"'{str(v)}'")
    
    sql = f"INSERT INTO users ({', '.join(cols)}) VALUES ({', '.join(vals)});"
    sql_lines.append(sql)

sql_lines.append("")
sql_lines.append(f"-- Inserindo {len(accounts)} accounts")

# Gerar INSERTs para accounts
for acc in accounts:
    cols = []
    vals = []
    
    for k, v in acc.items():
        if v is None:
            continue
        cols.append(f'"{k}"')
        
        if isinstance(v, bool):
            vals.append('true' if v else 'false')
        elif isinstance(v, (int, float)):
            vals.append(str(v))
        elif isinstance(v, str):
            safe_v = v.replace("'", "''")
            vals.append(f"'{safe_v}'")
        else:
            vals.append(f"'{str(v)}'")
    
    sql = f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({', '.join(vals)});"
    sql_lines.append(sql)

sql_lines.append("")
sql_lines.append(f"-- Inserindo {len(monitoring)} monitoring_accounts")

# Gerar INSERTs para monitoring_accounts
for mon in monitoring:
    cols = []
    vals = []
    
    for k, v in mon.items():
        if v is None:
            continue
        cols.append(f'"{k}"')
        
        if isinstance(v, bool):
            vals.append('true' if v else 'false')
        elif isinstance(v, (int, float)):
            vals.append(str(v))
        elif isinstance(v, str):
            safe_v = v.replace("'", "''")
            vals.append(f"'{safe_v}'")
        else:
            vals.append(f"'{str(v)}'")
    
    sql = f"INSERT INTO monitoring_accounts ({', '.join(cols)}) VALUES ({', '.join(vals)});"
    sql_lines.append(sql)

sql_lines.append("")
sql_lines.append("-- Reativar triggers")
sql_lines.append("SET session_replication_role = DEFAULT;")
sql_lines.append("")
sql_lines.append("COMMIT;")

# Salvar SQL
sql_file = Path(__file__).parent / 'import_complete_to_railway.sql'
with open(sql_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(sql_lines))

print("=" * 60)
print("✅ SQL COMPLETO GERADO!")
print("=" * 60)
print(f"\n📁 Arquivo: {sql_file}")
print(f"\n📊 Dados a importar:")
print(f"   👤 Users: {len(users)}")
print(f"   💼 Accounts: {len(accounts)}")
print(f"   📡 Monitoring: {len(monitoring)}")
print(f"\n📝 COMO IMPORTAR NO RAILWAY:")
print(f"   1. Acesse: https://railway.app/dashboard")
print(f"   2. Projeto → PostgreSQL → Query")
print(f"   3. Cole o conteúdo do arquivo SQL")
print(f"   4. Execute")
print(f"\n⚠️  Isso vai SUBSTITUIR todos os dados existentes!")

# Mostrar resumo
print(f"\n" + "=" * 60)
print("PRIMEIRAS 20 LINHAS DO SQL:")
print("=" * 60)
for line in sql_lines[:20]:
    print(line)
if len(sql_lines) > 20:
    print(f"... ({len(sql_lines) - 20} linhas restantes)")
