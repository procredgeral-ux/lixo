#!/usr/bin/env python3
"""Gerar SQL para importar dados no Railway"""
import json
from pathlib import Path

# Ler dados exportados
json_file = Path(__file__).parent / 'migration_data.json'
with open(json_file, 'r') as f:
    data = json.load(f)

accounts = data.get('accounts', [])
monitoring = data.get('monitoring', [])

sql_lines = [
    "-- Migração de dados PostgreSQL Local → Railway",
    "-- Gerado automaticamente",
    "",
    "BEGIN;",
    "",
    "-- Limpar tabelas existentes",
    "DELETE FROM monitoring_accounts;",
    "DELETE FROM accounts;",
    "",
    f"-- Inserindo {len(accounts)} accounts",
]

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
            # Escape single quotes
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
sql_lines.append("COMMIT;")

# Salvar SQL
sql_file = Path(__file__).parent / 'import_to_railway.sql'
with open(sql_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(sql_lines))

print("=" * 60)
print("✅ SQL GERADO!")
print("=" * 60)
print(f"\n📁 Arquivo: {sql_file}")
print(f"   Accounts: {len(accounts)}")
print(f"   Monitoring: {len(monitoring)}")
print(f"\n📝 COMO IMPORTAR NO RAILWAY:")
print(f"   1. Copie o conteúdo do arquivo SQL acima")
print(f"   2. Conecte ao PostgreSQL do Railway via Railway CLI:")
print(f"      railway connect postgres")
print(f"   3. Cole o SQL e execute")
print(f"\n   OU use o dashboard do Railway:")
print(f"   - Vá em PostgreSQL → Query")
print(f"   - Cole o SQL e execute")
print(f"\n⚠️  ATENÇÃO: Isso vai APAGAR os dados existentes e inserir os novos!")

# Mostrar as primeiras linhas
print(f"\n" + "=" * 60)
print("PRIMEIRAS 30 LINHAS DO SQL:")
print("=" * 60)
for line in sql_lines[:30]:
    print(line)
if len(sql_lines) > 30:
    print(f"... ({len(sql_lines) - 30} linhas restantes)")
