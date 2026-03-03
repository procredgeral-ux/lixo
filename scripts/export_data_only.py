#!/usr/bin/env python3
"""Exportar dados do PostgreSQL local para JSON"""
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
        
        # Salvar em arquivo
        output_file = Path(__file__).parent / 'migration_data.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Dados exportados para: {output_file}")
        print(f"   Accounts: {len(accounts_data)}")
        print(f"   Monitoring: {len(monitoring_data)}")

if __name__ == "__main__":
    asyncio.run(export())
