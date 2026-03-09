"""Script para limpar dados de backtest do banco usando SQLAlchemy"""
import asyncio
import sys
sys.path.insert(0, r'c:\Users\SOUZAS\Desktop\tunestrade')

from sqlalchemy import text
from core.database import get_db_context

async def clean_backtest_data():
    """Remove todos os dados relacionados a backtest do banco"""
    print("🗄️ Iniciando limpeza do banco de dados...")
    
    async with get_db_context() as db:
        # Verificar quantos registros existem
        result = await db.execute(text("""
            SELECT 
                (SELECT COUNT(*) FROM strategies WHERE name ILIKE '%backtest%' OR id ILIKE '%backtest%') as strategies,
                (SELECT COUNT(*) FROM trades WHERE strategy_id ILIKE '%backtest%') as trades,
                (SELECT COUNT(*) FROM signals WHERE strategy_id ILIKE '%backtest%') as signals
        """))
        row = result.fetchone()
        print(f"📊 Encontrados:")
        print(f"   - Estratégias com backtest: {row.strategies}")
        print(f"   - Trades com backtest: {row.trades}")
        print(f"   - Signals com backtest: {row.signals}")
        
        # Remover trades
        result = await db.execute(text("""
            DELETE FROM trades WHERE strategy_id ILIKE '%backtest%'
        """))
        print(f"✅ Trades removidos: {result.rowcount}")
        
        # Remover signals
        result = await db.execute(text("""
            DELETE FROM signals WHERE strategy_id ILIKE '%backtest%'
        """))
        print(f"✅ Signals removidos: {result.rowcount}")
        
        # Remover estratégias
        result = await db.execute(text("""
            DELETE FROM strategies WHERE name ILIKE '%backtest%' OR id ILIKE '%backtest%'
        """))
        print(f"✅ Estratégias removidas: {result.rowcount}")
        
        # Remover configs órfãs
        result = await db.execute(text("""
            DELETE FROM autotrade_configs 
            WHERE strategy_id NOT IN (SELECT id FROM strategies)
        """))
        print(f"✅ Configurações órfãs removidas: {result.rowcount}")
        
        await db.commit()
        print("\n✅ Limpeza concluída com sucesso!")

if __name__ == "__main__":
    asyncio.run(clean_backtest_data())
