#!/usr/bin/env python3
"""Migrar dados do PostgreSQL local para Railway usando SQLAlchemy"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select
from models import Account, MonitoringAccount, Base

# Banco local (usando asyncpg)
LOCAL_DB_URL = "postgresql+asyncpg://postgres:root@localhost:5432/tunestrade"

async def get_local_session():
    """Criar sessão para banco local"""
    engine = create_async_engine(LOCAL_DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()

async def export_accounts_local():
    """Exportar accounts do banco local"""
    print("📤 Exportando accounts do PostgreSQL local...")
    
    try:
        from core.database import get_db_context
        async with get_db_context() as db:
            result = await db.execute(select(Account))
            accounts = result.scalars().all()
            
            # Converter para dicionários
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
                    'balance_demo': acc.balance_demo,
                    'balance_real': acc.balance_real,
                    'currency': acc.currency,
                    'is_active': acc.is_active,
                    'last_connected': acc.last_connected.isoformat() if acc.last_connected else None,
                    'created_at': acc.created_at.isoformat() if acc.created_at else None,
                    'updated_at': acc.updated_at.isoformat() if acc.updated_at else None,
                })
            
            print(f"   ✅ {len(accounts_data)} accounts exportadas")
            return accounts_data
            
    except Exception as e:
        print(f"   ❌ Erro ao exportar accounts: {e}")
        return []

async def export_monitoring_local():
    """Exportar monitoring_accounts do banco local"""
    print("📤 Exportando monitoring_accounts do PostgreSQL local...")
    
    try:
        from core.database import get_db_context
        async with get_db_context() as db:
            result = await db.execute(select(MonitoringAccount))
            monitoring_records = result.scalars().all()
            
            # Converter para dicionários
            monitoring_data = []
            for mon in monitoring_records:
                monitoring_data.append({
                    'id': mon.id,
                    'ssid': mon.ssid,
                    'account_type': mon.account_type.value if mon.account_type else None,
                    'name': mon.name,
                    'is_active': mon.is_active,
                    'uid': mon.uid,
                    'platform': mon.platform,
                    'created_at': mon.created_at.isoformat() if mon.created_at else None,
                    'updated_at': mon.updated_at.isoformat() if mon.updated_at else None,
                })
            
            print(f"   ✅ {len(monitoring_data)} registros de monitoring_accounts exportados")
            return monitoring_data
            
    except Exception as e:
        print(f"   ❌ Erro ao exportar monitoring_accounts: {e}")
        return []

async def import_to_railway(accounts_data, monitoring_data):
    """Importar dados no Railway via API REST"""
    import requests
    
    API_URL = "https://web-production-640f.up.railway.app/api/v1"
    
    print("\n📥 Importando dados no Railway...")
    print(f"   URL: {API_URL}")
    
    # Pedir token se necessário
    token = input("\nDigite seu token JWT (ou Enter se não precisar): ").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    # Inserir accounts
    inserted_acc = 0
    if accounts_data:
        print(f"\n📥 Inserindo {len(accounts_data)} accounts...")
        for acc in accounts_data:
            try:
                # Remover campos que podem dar problema
                acc_clean = {k: v for k, v in acc.items() if v is not None}
                
                response = requests.post(
                    f"{API_URL}/accounts",
                    json=acc_clean,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code in (201, 200):
                    inserted_acc += 1
                    print(f"   ✅ Account {acc.get('id', '?')[:8]}... inserida")
                elif response.status_code == 400:
                    # Já existe ou erro de validação
                    print(f"   ⚠️  Account {acc.get('id', '?')[:8]}...: {response.json().get('detail', 'Erro')[:50]}")
                else:
                    print(f"   ❌ Account {acc.get('id', '?')[:8]}...: {response.status_code}")
                    
            except Exception as e:
                print(f"   ❌ Erro ao inserir account: {e}")
    
    print(f"\n   ✅ Total accounts inseridas: {inserted_acc}/{len(accounts_data)}")
    
    return inserted_acc, 0

async def main():
    print("=" * 60)
    print("MIGRAÇÃO LOCAL → RAILWAY")
    print("=" * 60)
    
    # Exportar dados
    accounts = await export_accounts_local()
    monitoring = await export_monitoring_local()
    
    if not accounts:
        print("\n⚠️  Nenhuma account encontrada para migrar!")
        return
    
    # Confirmar
    print(f"\n📊 Dados encontrados:")
    print(f"   Accounts: {len(accounts)}")
    print(f"   Monitoring: {len(monitoring)}")
    
    confirm = input("\nDeseja migrar esses dados para o Railway? (s/N): ")
    if confirm.lower() != 's':
        print("❌ Cancelado")
        return
    
    # Importar
    inserted_acc, inserted_mon = await import_to_railway(accounts, monitoring)
    
    print("\n" + "=" * 60)
    print("✅ MIGRAÇÃO CONCLUÍDA!")
    print("=" * 60)
    print(f"📈 Accounts: {inserted_acc}/{len(accounts)}")
    print(f"📈 Monitoring: {inserted_mon}/{len(monitoring)}")

if __name__ == "__main__":
    asyncio.run(main())
    input("\nPressione Enter para sair...")
