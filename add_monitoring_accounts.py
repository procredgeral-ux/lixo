"""
Script para cadastrar contas de monitoramento no banco de dados
"""
import asyncio
import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from core.database import get_db_context


async def add_monitoring_accounts():
    """Adicionar contas de monitoramento ATIVOS"""
    
    # Contas a serem adicionadas (tipo ATIVOS)
    accounts = [
        {
            "name": "ATIVOS Monitor 2",
            "account_type": "ATIVOS",
            "ssid": '42["auth",{"session":"dqp7bef64cr1am82nhgv0085lk","isDemo":1,"uid":126214401,"platform":2,"isFastHistory":true,"isOptimized":true}]',
        },
        {
            "name": "ATIVOS Monitor 3", 
            "account_type": "ATIVOS",
            "ssid": '42["auth",{"session":"cirekoo7bv1m5dmms1jfc0b7rp","isDemo":1,"uid":126214515,"platform":2,"isFastHistory":true,"isOptimized":true}]',
        }
    ]
    
    async with get_db_context() as db:
        try:
            for account in accounts:
                # Verificar se já existe uma conta com mesmo SSID
                check_result = await db.execute(
                    text("SELECT id FROM monitoring_accounts WHERE ssid = :ssid"),
                    {"ssid": account["ssid"]}
                )
                existing = check_result.fetchone()
                
                if existing:
                    print(f"⚠️ Conta '{account['name']}' já existe (ID: {existing[0]}). Pulando...")
                    continue
                
                # Inserir nova conta (estrutura simplificada)
                await db.execute(
                    text("""
                        INSERT INTO monitoring_accounts 
                        (name, account_type, ssid, is_active, created_at, updated_at)
                        VALUES 
                        (:name, :account_type, :ssid, TRUE, NOW(), NOW())
                    """),
                    {
                        "name": account["name"],
                        "account_type": account["account_type"],
                        "ssid": account["ssid"],
                    }
                )
                print(f"✅ Conta '{account['name']}' cadastrada com sucesso!")
                print(f"   - Type: {account['account_type']}")
                print(f"   - UID: {account['ssid'].split('uid":')[1].split(',')[0] if 'uid' in account['ssid'] else 'N/A'}")
            
            # Commit das alterações
            await db.commit()
            print("\n🎉 Todas as contas foram processadas!")
            
            # Listar todas as contas ATIVOS cadastradas
            result = await db.execute(
                text("SELECT id, name, account_type, is_active, created_at FROM monitoring_accounts WHERE UPPER(CAST(account_type AS TEXT)) = 'ATIVOS' ORDER BY created_at DESC")
            )
            rows = result.fetchall()
            
            print(f"\n📊 Total de contas ATIVOS cadastradas: {len(rows)}")
            for row in rows:
                print(f"   - ID {row[0]}: {row[1]} (ativo: {row[3]}, criado: {row[4]})")
                
        except Exception as e:
            print(f"❌ Erro ao cadastrar contas: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()


if __name__ == "__main__":
    print("🔧 Cadastrando contas de monitoramento...\n")
    asyncio.run(add_monitoring_accounts())
