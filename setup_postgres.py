"""Setup PostgreSQL - create user and database"""
import asyncio
import asyncpg
import sys

# Conectar como postgres (superuser) para criar o database e usuário
async def setup_database():
    # Primeiro tentar conectar ao database 'postgres' como superuser
    superuser_configs = [
        {"host": "localhost", "port": 5432, "database": "postgres", "user": "postgres", "password": "postgres"},
        {"host": "localhost", "port": 5432, "database": "postgres", "user": "postgres", "password": "root"},
        {"host": "localhost", "port": 5432, "database": "postgres", "user": "postgres"},  # sem senha
    ]
    
    conn = None
    for i, config in enumerate(superuser_configs, 1):
        try:
            print(f"[SETUP] Tentando conectar como postgres (tentativa {i})...")
            conn = await asyncpg.connect(**config, timeout=5)
            print(f"[SETUP] ✓ Conectado como postgres com: {config.get('password', 'no password')}")
            break
        except Exception as e:
            print(f"[SETUP] ✗ Falhou: {e}")
    
    if not conn:
        print("[SETUP] ✗ Não foi possível conectar como superuser!")
        print("[SETUP] Verifique se o PostgreSQL está rodando e se as credenciais do postgres estão corretas.")
        return False
    
    try:
        # Verificar se usuário tunestrade existe
        user_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'tunestrade'"
        )
        
        if not user_exists:
            print("[SETUP] Criando usuário 'tunestrade'...")
            await conn.execute("CREATE USER tunestrade WITH PASSWORD 'tunestrade' CREATEDB")
            print("[SETUP] ✓ Usuário 'tunestrade' criado")
        else:
            print("[SETUP] Usuário 'tunestrade' já existe")
        
        # Verificar se database tunestrade existe
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'tunestrade'"
        )
        
        if not db_exists:
            print("[SETUP] Criando database 'tunestrade'...")
            await conn.execute("CREATE DATABASE tunestrade OWNER tunestrade")
            print("[SETUP] ✓ Database 'tunestrade' criado")
        else:
            print("[SETUP] Database 'tunestrade' já existe")
        
        # Garantir privilégios
        await conn.execute("GRANT ALL PRIVILEGES ON DATABASE tunestrade TO tunestrade")
        print("[SETUP] ✓ Privilégios concedidos")
        
        await conn.close()
        
        # Testar conexão com o novo usuário
        print("[SETUP] Testando conexão com usuário 'tunestrade'...")
        test_conn = await asyncpg.connect(
            host="localhost",
            port=5432,
            database="tunestrade",
            user="tunestrade",
            password="tunestrade",
            timeout=5
        )
        result = await test_conn.fetch("SELECT 1 as test")
        print(f"[SETUP] ✓ Conexão com 'tunestrade' funcionou: {result}")
        await test_conn.close()
        
        print("\n[SETUP] ✓✓✓ Setup completo! O banco de dados está pronto.")
        return True
        
    except Exception as e:
        print(f"[SETUP] ✗ Erro durante setup: {e}")
        if conn:
            await conn.close()
        return False

if __name__ == "__main__":
    success = asyncio.run(setup_database())
    sys.exit(0 if success else 1)
