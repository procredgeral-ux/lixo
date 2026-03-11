"""Grant permissions to tunestrade user"""
import asyncio
import asyncpg

async def grant_permissions():
    # Connect as postgres (superuser)
    conn = await asyncpg.connect(
        host='127.0.0.1',
        port=5432,
        database='tunestrade',
        user='postgres',
        password='root',
        timeout=5
    )
    
    try:
        # Grant all privileges on database
        await conn.execute("GRANT ALL PRIVILEGES ON DATABASE tunestrade TO tunestrade")
        print("✓ Granted privileges on database")
        
        # Grant schema usage
        await conn.execute("GRANT USAGE ON SCHEMA public TO tunestrade")
        print("✓ Granted schema usage")
        
        # Grant all on all tables in public schema
        await conn.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO tunestrade")
        print("✓ Granted table privileges")
        
        # Grant sequence privileges
        await conn.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO tunestrade")
        print("✓ Granted sequence privileges")
        
        # Set default privileges for future tables
        await conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO tunestrade")
        print("✓ Set default table privileges")
        
        await conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO tunestrade")
        print("✓ Set default sequence privileges")
        
        # Make tunestrade the owner of the database
        await conn.execute("ALTER DATABASE tunestrade OWNER TO tunestrade")
        print("✓ Changed database owner to tunestrade")
        
        print("\n✓✓✓ All permissions granted!")
        
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(grant_permissions())
