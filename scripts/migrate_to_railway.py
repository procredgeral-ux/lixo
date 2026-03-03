#!/usr/bin/env python3
"""Migrar dados das tabelas monitoring e accounts do PostgreSQL local para o Railway"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from sqlalchemy import text
from core.database import get_db_context
from core.config import settings

# URLs dos bancos
LOCAL_DB = "postgresql://postgres:root@localhost:5432/tunestrade"
# Railway DB - vamos pegar do .env ou usar variável
def get_railway_db_url():
    """Pegar URL do Railway das variáveis de ambiente ou input"""
    import os
    url = os.getenv("RAILWAY_DATABASE_URL")
    if not url:
        print("Digite a DATABASE_URL do Railway (copie do dashboard do Railway):")
        print("Formato: postgresql://user:pass@host:port/database")
        url = input("> ").strip()
    return url

async def export_from_local():
    """Exportar dados do PostgreSQL local"""
    print("📤 Exportando dados do PostgreSQL local...")
    
    conn = await asyncpg.connect(LOCAL_DB)
    
    try:
        # Exportar accounts
        accounts = await conn.fetch("SELECT * FROM accounts")
        print(f"   ✅ {len(accounts)} accounts encontradas")
        
        # Exportar monitoring (se existir)
        try:
            monitoring = await conn.fetch("SELECT * FROM monitoring")
            print(f"   ✅ {len(monitoring)} registros de monitoring encontrados")
        except:
            monitoring = []
            print("   ⚠️  Tabela monitoring não encontrada ou vazia")
        
        return accounts, monitoring
        
    finally:
        await conn.close()

async def import_to_railway(accounts, monitoring):
    """Importar dados no Railway"""
    railway_db = get_railway_db_url()
    
    print(f"\n📥 Conectando ao Railway...")
    conn = await asyncpg.connect(railway_db)
    
    inserted_accounts = 0
    inserted_monitoring = 0
    
    try:
        # Limpar tabelas primeiro (opcional - comentar se quiser manter dados existentes)
        print("\n🧹 Limpando tabelas no Railway...")
        await conn.execute("DELETE FROM monitoring")
        await conn.execute("DELETE FROM accounts")
        print("   ✅ Tabelas limpas")
        
        # Importar accounts
        print(f"\n📥 Importando {len(accounts)} accounts...")
        for acc in accounts:
            try:
                columns = list(acc.keys())
                values = list(acc.values())
                
                # Converter datetime para string ISO
                values = [
                    v.isoformat() if isinstance(v, datetime) else v
                    for v in values
                ]
                
                placeholders = ", ".join([f"${i+1}" for i in range(len(values))])
                columns_str = ", ".join(columns)
                
                await conn.execute(
                    f"INSERT INTO accounts ({columns_str}) VALUES ({placeholders})",
                    *values
                )
                inserted_accounts += 1
            except Exception as e:
                print(f"   ❌ Erro ao inserir account {acc.get('id', '?')}: {e}")
        
        print(f"   ✅ {inserted_accounts} accounts inseridas")
        
        # Importar monitoring
        if monitoring:
            print(f"\n📥 Importando {len(monitoring)} registros de monitoring...")
            for mon in monitoring:
                try:
                    columns = list(mon.keys())
                    values = list(mon.values())
                    
                    # Converter datetime para string ISO
                    values = [
                        v.isoformat() if isinstance(v, datetime) else v
                        for v in values
                    ]
                    
                    placeholders = ", ".join([f"${i+1}" for i in range(len(values))])
                    columns_str = ", ".join(columns)
                    
                    await conn.execute(
                        f"INSERT INTO monitoring ({columns_str}) VALUES ({placeholders})",
                        *values
                    )
                    inserted_monitoring += 1
                except Exception as e:
                    print(f"   ❌ Erro ao inserir monitoring {mon.get('id', '?')}: {e}")
            
            print(f"   ✅ {inserted_monitoring} registros de monitoring inseridos")
        
    finally:
        await conn.close()
    
    return inserted_accounts, inserted_monitoring

async def main():
    print("=" * 60)
    print("MIGRAÇÃO DE DADOS - Local → Railway")
    print("=" * 60)
    print(f"\nBanco local: {LOCAL_DB}")
    
    try:
        # Exportar
        accounts, monitoring = await export_from_local()
        
        if not accounts:
            print("\n⚠️  Nenhuma account encontrada no banco local!")
            return
        
        # Confirmar
        print(f"\n📊 Resumo da exportação:")
        print(f"   Accounts: {len(accounts)}")
        print(f"   Monitoring: {len(monitoring)}")
        
        confirm = input("\n⚠️  Isso vai APAGAR os dados existentes no Railway e importar os novos. Continuar? (s/N): ")
        if confirm.lower() != 's':
            print("❌ Cancelado pelo usuário")
            return
        
        # Importar
        inserted_acc, inserted_mon = await import_to_railway(accounts, monitoring)
        
        print("\n" + "=" * 60)
        print("✅ MIGRAÇÃO CONCLUÍDA!")
        print("=" * 60)
        print(f"📈 Accounts migradas: {inserted_acc}/{len(accounts)}")
        print(f"📈 Monitoring migrados: {inserted_mon}/{len(monitoring)}")
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
    input("\nPressione Enter para sair...")
