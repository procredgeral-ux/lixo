#!/usr/bin/env python3
"""Exportar users, accounts e monitoring_accounts do PostgreSQL local"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

LOCAL_DB = "postgresql://postgres:root@localhost:5432/tunestrade"

async def export_all():
    conn = await asyncpg.connect(LOCAL_DB)
    
    try:
        # Exportar users
        rows = await conn.fetch("SELECT * FROM users")
        users_data = [dict(row) for row in rows]
        for user in users_data:
            for k, v in user.items():
                if hasattr(v, 'isoformat'):
                    user[k] = v.isoformat()
        print(f"✅ {len(users_data)} users exportados")
        
        # Exportar accounts
        rows = await conn.fetch("SELECT * FROM accounts")
        accounts_data = [dict(row) for row in rows]
        for acc in accounts_data:
            for k, v in acc.items():
                if hasattr(v, 'isoformat'):
                    acc[k] = v.isoformat()
        print(f"✅ {len(accounts_data)} accounts exportadas")
        
        # Exportar monitoring_accounts
        rows = await conn.fetch("SELECT * FROM monitoring_accounts")
        monitoring_data = [dict(row) for row in rows]
        for mon in monitoring_data:
            for k, v in mon.items():
                if hasattr(v, 'isoformat'):
                    mon[k] = v.isoformat()
        print(f"✅ {len(monitoring_data)} monitoring_accounts exportados")
        
        # Salvar
        data = {
            'users': users_data,
            'accounts': accounts_data,
            'monitoring_accounts': monitoring_data
        }
        output_file = Path(__file__).parent / 'migration_all_data.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n📁 Dados salvos em: {output_file}")
        print(f"   Total: {len(users_data)} users, {len(accounts_data)} accounts, {len(monitoring_data)} monitoring")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(export_all())
