"""
Script para corrigir duplicidades na tabela de indicadores
Remove indicadores duplicados mantendo o registro mais antigo
"""
import os
import sys
import psycopg2
from urllib.parse import urlparse

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip().strip('"\'')

def get_database_url():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise ValueError("DATABASE_URL não configurada!")
    return url

def fix_duplicate_indicators():
    """Corrige duplicidades na tabela indicators"""
    
    print("🔧 Corrigindo duplicidades na tabela indicators...")
    
    try:
        load_env()
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
        
        # 1. Buscar todos os indicadores ordenados por tipo e data de criação
        cursor.execute("""
            SELECT id, name, type, created_at 
            FROM indicators 
            ORDER BY LOWER(type), created_at ASC
        """)
        all_indicators = cursor.fetchall()
        
        print(f"📊 Total de indicadores encontrados: {len(all_indicators)}")
        
        # 2. Agrupar por tipo (lowercase) para identificar duplicados
        from collections import defaultdict
        by_type = defaultdict(list)
        
        for row in all_indicators:
            ind_id, name, ind_type, created_at = row
            by_type[ind_type.lower()].append({
                'id': ind_id,
                'name': name,
                'type': ind_type,
                'created_at': created_at
            })
        
        # 3. Identificar duplicados por tipo
        duplicates = []
        to_delete = []
        
        for ind_type, indicators in by_type.items():
            if len(indicators) > 1:
                duplicates.append(indicators)
                # Manter o primeiro (mais antigo), marcar os outros para exclusão
                for ind in indicators[1:]:
                    to_delete.append(ind)
        
        print(f"\n📋 Grupos com duplicados encontrados: {len(duplicates)}")
        
        for group in duplicates:
            print(f"\n   Tipo '{group[0]['type']}':")
            for i, ind in enumerate(group):
                marker = " (MANTER)" if i == 0 else " (REMOVER)"
                print(f"      - {ind['name']} ({ind['id'][:8]}...){marker}")
        
        # 4. Remover duplicados
        if to_delete:
            print(f"\n🗑️  Removendo {len(to_delete)} indicadores duplicados...")
            
            for ind in to_delete:
                # Primeiro remover referências na tabela strategy_indicators
                cursor.execute("""
                    DELETE FROM strategy_indicators WHERE indicator_id = %s
                """, (ind['id'],))
                
                # Depois remover o indicador
                cursor.execute("""
                    DELETE FROM indicators WHERE id = %s
                """, (ind['id'],))
                
                print(f"   ✓ Removido: {ind['name']} ({ind['id'][:8]}...)")
            
            conn.commit()
            print(f"\n✅ {len(to_delete)} duplicatas removidas com sucesso!")
        else:
            print("\n✅ Nenhuma duplicidade encontrada!")
        
        # 5. Verificar duplicidade por nome também (diferentes tipos, mesmo nome)
        cursor.execute("""
            SELECT name, COUNT(*) as count 
            FROM indicators 
            GROUP BY name 
            HAVING COUNT(*) > 1
        """)
        name_duplicates = cursor.fetchall()
        
        if name_duplicates:
            print(f"\n⚠️  Encontrados {len(name_duplicates)} nomes duplicados:")
            for name, count in name_duplicates:
                print(f"   - '{name}': {count} ocorrências")
        
        # 6. Resumo final
        cursor.execute("SELECT COUNT(*) FROM indicators")
        final_count = cursor.fetchone()[0]
        
        print(f"\n📊 Resumo:")
        print(f"   Total inicial: {len(all_indicators)}")
        print(f"   Total final: {final_count}")
        print(f"   Removidos: {len(to_delete)}")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Correção de duplicidades concluída!")
        
    except Exception as e:
        print(f"\n❌ Erro ao corrigir duplicidades: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    fix_duplicate_indicators()
