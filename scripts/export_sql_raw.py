#!/usr/bin/env python3
"""Exportar dados via SQL direto (sem ORM)"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

LOCAL_DB = "postgresql://postgres:root@localhost:5432/tunestrade"

async def export():
    conn = await asyncpg.connect(LOCAL_DB)
    
    try:
        # Exportar accounts
        rows = await conn.fetch("SELECT * FROM accounts")
        accounts_data = [dict(row) for row in rows]
        
        # Converter datetime para string
        for acc in accounts_data:
            for k, v in acc.items():
                if hasattr(v, 'isoformat'):
                    acc[k] = v.isoformat()
        
        print(f"✅ {len(accounts_data)} accounts exportadas")
        
        # Exportar monitoring_accounts
        rows = await conn.fetch("SELECT * FROM monitoring_accounts")
        monitoring_data = [dict(row) for row in rows]
        
        # Converter datetime para string
        for mon in monitoring_data:
            for k, v in mon.items():
                if hasattr(v, 'isoformat'):
                    mon[k] = v.isoformat()
        
        print(f"✅ {len(monitoring_data)} monitoring_accounts exportados")
        
        # Salvar
        data = {'accounts': accounts_data, 'monitoring': monitoring_data}
        output_file = Path(__file__).parent / 'migration_data.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n📁 Dados salvos em: {output_file}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(export())
