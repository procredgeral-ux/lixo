"""
Script para ativar indicadores inativos no banco de dados
Correção Prioridade 1: Ativar indicadores com is_active=NULL
"""
import os
import sys
import psycopg2
from urllib.parse import urlparse

# Carregar variáveis do .env manualmente
def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip().strip('"\'')

def get_database_url():
    """Get DATABASE_URL from environment"""
    url = os.getenv('DATABASE_URL')
    if not url:
        raise ValueError("DATABASE_URL não configurada!")
    return url

def activate_inactive_indicators():
    """Ativar indicadores inativos no banco de dados"""
    
    # Lista de indicadores que devem ser ativados
    inactive_indicators = [
        'parabolic_sar',
        'ichimoku_cloud',
        'money_flow_index',
        'average_directional_index',
        'adx',
        'keltner_channels',
        'donchian_channels',
        'heiken_ashi',
        'pivot_points',
        'supertrend',
        'fibonacci_retracement',
        'vwap',
        'obv'
    ]
    
    print("🔧 Ativando indicadores inativos no banco de dados...")
    print(f"📋 Total de indicadores a ativar: {len(inactive_indicators)}")
    
    try:
        # Carregar .env
        load_env()
        
        # Conectar ao banco
        db_url = get_database_url()
        result = urlparse(db_url)
        
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port or 5432,
            database=result.path.lstrip('/'),
            user=result.username,
            password=result.password
        )
        cursor = conn.cursor()
        
        # SQL para ativar indicadores pelo nome
        update_sql = """
            UPDATE indicators 
            SET is_active = TRUE, 
                is_default = TRUE,
                updated_at = NOW()
            WHERE LOWER(name) = ANY(%s)
            OR LOWER(type) = ANY(%s)
        """
        
        cursor.execute(update_sql, (inactive_indicators, inactive_indicators))
        conn.commit()
        
        print(f"✅ Indicadores ativados: {cursor.rowcount}")
        
        # Verificar status atual
        check_sql = """
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active,
                COUNT(CASE WHEN is_active IS NULL OR is_active = FALSE THEN 1 END) as inactive
            FROM indicators
        """
        
        cursor.execute(check_sql)
        check_result = cursor.fetchone()
        print(f"\n📊 Status dos Indicadores:")
        print(f"   Total: {check_result[0]}")
        print(f"   Ativos: {check_result[1]}")
        print(f"   Inativos: {check_result[2]}")
        
        # Listar indicadores ainda inativos
        if check_result[2] > 0:
            list_sql = """
                SELECT name, type, is_active, is_default
                FROM indicators
                WHERE is_active IS NULL OR is_active = FALSE
                ORDER BY name
            """
            cursor.execute(list_sql)
            inactive = cursor.fetchall()
            print(f"\n⚠️  Indicadores ainda inativos:")
            for ind in inactive:
                print(f"   - {ind[0]} (type={ind[1]}, is_active={ind[2]})")
        
        # Listar indicadores agora ativos
        list_active_sql = """
            SELECT name, type, is_active
            FROM indicators
            WHERE is_active = TRUE
            ORDER BY name
        """
        cursor.execute(list_active_sql)
        active = cursor.fetchall()
        print(f"\n✅ Indicadores ativos ({len(active)}):")
        for ind in active:
            print(f"   ✓ {ind[0]} (type={ind[1]})")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Correção de indicadores inativos concluída!")
        
    except Exception as e:
        print(f"\n❌ Erro ao ativar indicadores: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    activate_inactive_indicators()
