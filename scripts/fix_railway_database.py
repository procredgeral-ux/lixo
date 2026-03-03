#!/usr/bin/env python3
"""
Script para executar correções no banco do Railway
Usa as variáveis de ambiente do Railway PostgreSQL
"""
import asyncio
import sys
import uuid
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

# 23 Indicadores padrão do sistema
DEFAULT_INDICATORS = [
    {
        "name": "RSI - Relative Strength Index",
        "type": "rsi",
        "description": "Índice de Força Relativa - identifica condições de sobrecompra/sobrevenda",
        "parameters": {"period": 14, "overbought": 70, "oversold": 30},
    },
    {
        "name": "MACD - Moving Average Convergence Divergence",
        "type": "macd",
        "description": "Convergência/Divergência de Médias Móveis - identifica tendências e reversões",
        "parameters": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    },
    {
        "name": "Bollinger Bands",
        "type": "bollinger_bands",
        "description": "Bandas de Bollinger - identifica volatilidade e reversões de preço",
        "parameters": {"period": 20, "std_dev": 2},
    },
    {
        "name": "SMA - Simple Moving Average",
        "type": "sma",
        "description": "Média Móvel Simples - identifica tendência de longo prazo",
        "parameters": {"period": 50},
    },
    {
        "name": "EMA - Exponential Moving Average",
        "type": "ema",
        "description": "Média Móvel Exponencial - identifica tendência de curto prazo",
        "parameters": {"period": 20},
    },
    {
        "name": "Stochastic Oscillator",
        "type": "stochastic",
        "description": "Oscilador Estocástico - identifica momentum e reversões",
        "parameters": {"k_period": 14, "d_period": 3, "slowing": 3, "overbought": 80, "oversold": 20},
    },
    {
        "name": "ATR - Average True Range",
        "type": "atr",
        "description": "Average True Range - mede volatilidade do mercado",
        "parameters": {"period": 14},
    },
    {
        "name": "CCI - Commodity Channel Index",
        "type": "cci",
        "description": "Identifica ciclos de preço e condições de sobrecompra/sobrevenda",
        "parameters": {"period": 20, "overbought": 100, "oversold": -100},
    },
    {
        "name": "Williams %R",
        "type": "williams_r",
        "description": "Oscilador de momentum que mede níveis de sobrecompra/sobrevenda",
        "parameters": {"period": 14, "overbought": -20, "oversold": -80},
    },
    {
        "name": "ROC - Rate of Change",
        "type": "roc",
        "description": "Mede a velocidade de mudança do preço em um período",
        "parameters": {"period": 12, "overbought": 5, "oversold": -5},
    },
    {
        "name": "VWAP - Volume Weighted Average Price",
        "type": "vwap",
        "description": "Preço médio ponderado pelo volume, usado como suporte/resistência",
        "parameters": {"period": 14, "std_dev_multiplier": 1.0},
    },
    {
        "name": "OBV - On Balance Volume",
        "type": "obv",
        "description": "Indicador de fluxo de volume que relaciona volume com mudança de preço",
        "parameters": {"signal_period": 9},
    },
    {
        "name": "Parabolic SAR",
        "type": "parabolic_sar",
        "description": "Parabolic Stop and Reverse - trend reversal indicator",
        "parameters": {"initial_af": 0.02, "max_af": 0.2, "step_af": 0.02},
    },
    {
        "name": "Ichimoku Cloud",
        "type": "ichimoku_cloud",
        "description": "Ichimoku Kinko Hyo - comprehensive trend indicator",
        "parameters": {"tenkan_period": 9, "kijun_period": 26, "senkou_span_b_period": 52, "chikou_shift": 26},
    },
    {
        "name": "MFI - Money Flow Index",
        "type": "money_flow_index",
        "description": "MFI - momentum indicator with volume",
        "parameters": {"period": 14},
    },
    {
        "name": "ADX - Average Directional Index",
        "type": "average_directional_index",
        "description": "Average Directional Index - trend strength indicator",
        "parameters": {"period": 14},
    },
    {
        "name": "Keltner Channels",
        "type": "keltner_channels",
        "description": "Keltner Channels - volatility bands",
        "parameters": {"ema_period": 20, "atr_period": 20, "multiplier": 2.0},
    },
    {
        "name": "Donchian Channels",
        "type": "donchian_channels",
        "description": "Donchian Channels - price channel indicator",
        "parameters": {"period": 20},
    },
    {
        "name": "Heiken Ashi",
        "type": "heiken_ashi",
        "description": "Heiken Ashi - filtered price candles",
        "parameters": {},
    },
    {
        "name": "Pivot Points",
        "type": "pivot_points",
        "description": "Pivot Points - support and resistance levels",
        "parameters": {},
    },
    {
        "name": "Supertrend",
        "type": "supertrend",
        "description": "Supertrend - trend following indicator",
        "parameters": {"atr_period": 10, "multiplier": 3.0},
    },
    {
        "name": "Fibonacci Retracement",
        "type": "fibonacci_retracement",
        "description": "Fibonacci Retracement - support/resistance levels",
        "parameters": {"lookback": 50},
    },
    {
        "name": "Zonas de Suporte/Resistência",
        "type": "zonas",
        "description": "Identifica zonas de suporte e resistência baseadas em máximas e mínimas históricas",
        "parameters": {"lookback_periods": 20, "zone_merge_distance": 0.001},
    },
]


async def populate_indicators(conn):
    """Popula a tabela indicators com os 23 indicadores padrão"""
    print("\n" + "=" * 60)
    print("POPULANDO TABELA 'indicators' COM 23 INDICADORES PADRÃO")
    print("=" * 60)
    
    added = 0
    updated = 0
    
    for indicator in DEFAULT_INDICATORS:
        # Verificar se já existe por tipo
        row = await conn.fetchrow(
            "SELECT id FROM indicators WHERE type = $1",
            indicator["type"]
        )
        
        if row:
            # Atualizar para garantir is_default = true
            await conn.execute(
                """
                UPDATE indicators 
                SET is_default = true, 
                    is_active = true,
                    name = $1,
                    description = $2,
                    parameters = $3,
                    updated_at = $4
                WHERE type = $5
                """,
                indicator["name"],
                indicator["description"],
                json.dumps(indicator["parameters"]),
                datetime.utcnow(),
                indicator["type"]
            )
            print(f"   🔄 Atualizado: {indicator['name']}")
            updated += 1
        else:
            # Inserir novo
            ind_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO indicators 
                (id, name, type, description, parameters, is_active, is_default, version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, true, true, '1.0', $6, $6)
                """,
                ind_id,
                indicator["name"],
                indicator["type"],
                indicator["description"],
                json.dumps(indicator["parameters"]),
                datetime.utcnow()
            )
            print(f"   ✅ Inserido: {indicator['name']}")
            added += 1
    
    print(f"\n📈 Novos indicadores: {added}")
    print(f"🔄 Atualizados: {updated}")


async def clean_strategies(conn):
    """Limpa todas as estratégias do banco"""
    print("\n" + "=" * 60)
    print("LIMPANDO TABELA 'strategies'")
    print("=" * 60)
    
    # Verificar o que existe antes
    row = await conn.fetchrow("SELECT COUNT(*) FROM strategies")
    strategy_count = row['count']
    
    row = await conn.fetchrow("SELECT COUNT(*) FROM strategy_indicators")
    link_count = row['count']
    
    print(f"📊 Estratégias encontradas: {strategy_count}")
    print(f"📊 Ligações strategy_indicators: {link_count}")
    
    if strategy_count == 0 and link_count == 0:
        print("\n✅ Tabelas já estão vazias. Nada a fazer.")
        return
    
    # Listar estratégias que serão removidas
    if strategy_count > 0:
        print("\nEstratégias que serão removidas:")
        rows = await conn.fetch("SELECT name, type, user_id FROM strategies ORDER BY name")
        for row in rows:
            user_short = row['user_id'][:8] + "..." if row['user_id'] else "NULL"
            print(f"   ❌ {row['name']} (type={row['type']}, user={user_short})")
    
    # Remover ligações primeiro (foreign key constraint)
    print("\nExecutando limpeza...")
    
    if link_count > 0:
        await conn.execute("DELETE FROM strategy_indicators")
        print(f"   ✅ Removidas {link_count} ligações")
    
    if strategy_count > 0:
        await conn.execute("DELETE FROM strategies")
        print(f"   ✅ Removidas {strategy_count} estratégias")
    
    print("\n✅ Limpeza concluída!")


async def main():
    # Dados da conexão Railway PostgreSQL
    host = "tramway.proxy.rlwy.net"  # RAILWAY_TCP_PROXY_DOMAIN
    port = 25313  # RAILWAY_TCP_PROXY_PORT
    user = "postgres"
    password = "lGQYDSYZCSbyZHFRNbYOWAjGKefFtpeE"
    database = "railway"
    
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    
    print("=" * 60)
    print("CONECTANDO AO BANCO RAILWAY")
    print(f"Host: {host}:{port}")
    print(f"Database: {database}")
    print("=" * 60)
    
    try:
        conn = await asyncpg.connect(dsn, ssl='require')
        print("✅ Conectado com sucesso!")
        
        # Executar correções
        await populate_indicators(conn)
        await clean_strategies(conn)
        
        # Resumo final
        print("\n" + "=" * 60)
        print("RESUMO FINAL")
        print("=" * 60)
        
        row = await conn.fetchrow("SELECT COUNT(*) FROM indicators WHERE is_default = true")
        print(f"📊 Indicadores padrão: {row['count']}")
        
        row = await conn.fetchrow("SELECT COUNT(*) FROM strategies")
        print(f"📊 Estratégias: {row['count']}")
        
        await conn.close()
        print("\n✅ Concluído!")
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
