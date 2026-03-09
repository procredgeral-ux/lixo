"""
Script para ativar os 7 novos indicadores no banco de dados
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

def activate_new_indicators():
    """Ativar os 7 novos indicadores no banco de dados"""
    
    # Lista dos 7 novos indicadores
    new_indicators = [
        'awesome_oscillator',
        'detrended_price_oscillator', 
        'force_index',
        'klinger_oscillator',
        'mass_index',
        'true_strength_index',
        'ultimate_oscillator'
    ]
    
    # Nomes amigáveis para o banco de dados
    indicator_names = {
        'awesome_oscillator': 'Awesome Oscillator',
        'detrended_price_oscillator': 'Detrended Price Oscillator',
        'force_index': 'Force Index',
        'klinger_oscillator': 'Klinger Volume Oscillator',
        'mass_index': 'Mass Index',
        'true_strength_index': 'True Strength Index',
        'ultimate_oscillator': 'Ultimate Oscillator'
    }
    
    # Parâmetros padrão para cada indicador
    indicator_params = {
        'awesome_oscillator': '{"fast_period": 5, "slow_period": 34}',
        'detrended_price_oscillator': '{"period": 20}',
        'force_index': '{"period": 13}',
        'klinger_oscillator': '{"fast_period": 34, "slow_period": 55, "signal_period": 13}',
        'mass_index': '{"ema_period": 9, "double_ema_period": 25}',
        'true_strength_index': '{"long_period": 25, "short_period": 13, "signal_period": 7}',
        'ultimate_oscillator': '{"short_period": 7, "medium_period": 14, "long_period": 28}'
    }
    
    print("🔧 Ativando 7 novos indicadores no banco de dados...")
    print(f"📋 Indicadores a ativar: {len(new_indicators)}")
    
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
        
        # Verificar se os indicadores já existem (pelo type, não pelo name)
        check_sql = """
            SELECT LOWER(type), id FROM indicators 
            WHERE LOWER(type) = ANY(%s)
        """
        cursor.execute(check_sql, (new_indicators,))
        existing = {row[0]: row[1] for row in cursor.fetchall()}
        
        print(f"\n📊 Indicadores já existentes: {len(existing)}")
        
        # Inserir novos indicadores
        insert_count = 0
        for ind_type in new_indicators:
            if ind_type in existing:
                # Atualizar se já existe
                update_sql = """
                    UPDATE indicators 
                    SET is_active = TRUE, 
                        is_default = TRUE,
                        updated_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(update_sql, (existing[ind_type],))
                print(f"   ✓ Atualizado: {indicator_names[ind_type]}")
            else:
                # Inserir novo
                insert_sql = """
                    INSERT INTO indicators (id, name, type, description, parameters, is_active, is_default, created_at, updated_at)
                    VALUES (
                        gen_random_uuid()::text, 
                        %s, 
                        %s, 
                        %s, 
                        %s::jsonb, 
                        TRUE, 
                        TRUE, 
                        NOW(), 
                        NOW()
                    )
                """
                description = f"{indicator_names[ind_type]} - Technical Indicator"
                cursor.execute(insert_sql, (
                    indicator_names[ind_type],
                    ind_type,
                    description,
                    indicator_params[ind_type]
                ))
                insert_count += 1
                print(f"   ✓ Inserido: {indicator_names[ind_type]}")
        
        conn.commit()
        
        print(f"\n✅ Total de indicadores inseridos: {insert_count}")
        print(f"✅ Total de indicadores atualizados: {len(existing)}")
        
        # Verificar status final
        check_final_sql = """
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active
            FROM indicators
        """
        cursor.execute(check_final_sql)
        total_result = cursor.fetchone()
        print(f"\n📊 Status final:")
        print(f"   Total de indicadores: {total_result[0]}")
        print(f"   Indicadores ativos: {total_result[1]}")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Novos indicadores ativados com sucesso!")
        print("🔄 Reinicie o sistema para carregar os novos indicadores.")
        
    except Exception as e:
        print(f"\n❌ Erro ao ativar indicadores: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    activate_new_indicators()
