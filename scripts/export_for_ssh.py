#!/usr/bin/env python3
"""Migrar dados via Railway CLI + SSH no PostgreSQL"""

import json
import subprocess
import sys
import tempfile
import os

# Dados a serem migrados (vamos exportar primeiro)
print("=" * 60)
print("MIGRAÇÃO VIA RAILWAY SSH")
print("=" * 60)
print("\n⚠️  Este script requer:")
print("   1. Railway CLI instalado e logado")
print("   2. Acesso ao projeto Railway")
print("\nVamos exportar os dados do PostgreSQL local primeiro...")

input("\nPressione Enter quando estiver pronto...")

# Exportar via Python
export_script = '''
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import get_db_context
from sqlalchemy import select
from models import Account, MonitoringAccount

async def export():
    async with get_db_context() as db:
        # Exportar accounts
        result = await db.execute(select(Account))
        accounts = result.scalars().all()
        
        accounts_data = []
        for acc in accounts:
            accounts_data.append({
                'id': acc.id,
                'user_id': acc.user_id,
                'name': acc.name,
                'ssid_demo': acc.ssid_demo,
                'ssid_real': acc.ssid_real,
                'autotrade_demo': acc.autotrade_demo,
                'autotrade_real': acc.autotrade_real,
                'uid': acc.uid,
                'platform': acc.platform,
                'balance_demo': float(acc.balance_demo) if acc.balance_demo else 0,
                'balance_real': float(acc.balance_real) if acc.balance_real else 0,
                'currency': acc.currency,
                'is_active': acc.is_active,
                'last_connected': acc.last_connected.isoformat() if acc.last_connected else None,
                'created_at': acc.created_at.isoformat() if acc.created_at else None,
                'updated_at': acc.updated_at.isoformat() if acc.updated_at else None,
            })
        
        # Exportar monitoring_accounts
        result = await db.execute(select(MonitoringAccount))
        monitoring = result.scalars().all()
        
        monitoring_data = []
        for mon in monitoring:
            monitoring_data.append({
                'id': mon.id,
                'ssid': mon.ssid,
                'account_type': mon.account_type.value if mon.account_type else 'payout',
                'name': mon.name,
                'is_active': mon.is_active,
                'uid': mon.uid,
                'platform': mon.platform or 1,
                'created_at': mon.created_at.isoformat() if mon.created_at else None,
                'updated_at': mon.updated_at.isoformat() if mon.updated_at else None,
            })
        
        data = {'accounts': accounts_data, 'monitoring': monitoring_data}
        print(json.dumps(data, indent=2))

asyncio.run(export())
'''

print("\n📤 Exportando dados do PostgreSQL local...")
result = subprocess.run(
    [sys.executable, "-c", export_script],
    capture_output=True,
    text=True,
    cwd=r"c:\Users\SOUZAS\Desktop\tunestrade"
)

if result.returncode != 0:
    print(f"❌ Erro ao exportar: {result.stderr}")
    sys.exit(1)

try:
    data = json.loads(result.stdout)
except:
    print(f"❌ Erro ao parsear dados: {result.stdout[:500]}")
    sys.exit(1)

accounts = data.get('accounts', [])
monitoring = data.get('monitoring', [])

print(f"✅ {len(accounts)} accounts exportadas")
print(f"✅ {len(monitoring)} monitoring_accounts exportados")

if not accounts:
    print("\n⚠️  Nenhuma account para migrar!")
    sys.exit(0)

# Criar arquivo SQL
sql_lines = ["-- Migracao de dados do PostgreSQL local para Railway", "BEGIN;"]

# Limpar tabelas
sql_lines.append("DELETE FROM monitoring_accounts;")
sql_lines.append("DELETE FROM accounts;")

# Inserir accounts
for acc in accounts:
    cols = []
    vals = []
    for k, v in acc.items():
        if v is None:
            continue
        cols.append(k)
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

# Inserir monitoring
for mon in monitoring:
    cols = []
    vals = []
    for k, v in mon.items():
        if v is None:
            continue
        cols.append(k)
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

sql_lines.append("COMMIT;")

# Salvar SQL temporário
with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
    sql_file = f.name
    f.write('\n'.join(sql_lines))

print(f"\n📄 SQL gerado: {sql_file}")
print(f"   Linhas: {len(sql_lines)}")

print("\n" + "=" * 60)
print("PRÓXIMOS PASSOS:")
print("=" * 60)
print(f"\n1. Conecte ao PostgreSQL do Railway via SSH:")
print(f"   railway ssh --service=01a81f21-501d-4802-a0c5-2bf8f5f63f28")
print(f"\n2. Dentro do container, execute:")
print(f"   psql ${{Postgres.DATABASE_URL}} -f /tmp/migrate.sql")
print(f"\n3. Ou copie o conteúdo do arquivo e execute no psql")
print(f"\n4. Arquivo SQL está em: {sql_file}")

# Também mostrar o SQL
print("\n" + "=" * 60)
print("CONTEÚDO DO SQL (primeiras 50 linhas):")
print("=" * 60)
with open(sql_file, 'r') as f:
    lines = f.readlines()
    for line in lines[:50]:
        print(line.rstrip())
    if len(lines) > 50:
        print(f"... ({len(lines) - 50} linhas restantes)")

print(f"\n✅ Exportação concluída!")
print(f"📁 Arquivo SQL: {sql_file}")
input("\nPressione Enter para sair...")
