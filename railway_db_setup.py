"""Railway database setup script - Create tables and seed data"""
import asyncio
import os
import sys

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from core.config import settings

# Get database URL
DATABASE_URL = settings.DATABASE_URL

# Remove sslmode from URL for asyncpg compatibility
if 'sslmode=' in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split('?')[0]
    print(f"📍 Cleaned database URL (removed sslmode)")

async def setup_database():
    """Create tables and seed initial data"""
    print("🚀 Setting up Railway database...")
    print(f"📍 Database: {DATABASE_URL.split('@')[0]}@...")
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        # Create essential tables
        print("📦 Creating tables...")
        
        # Users table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                is_superuser BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Monitoring accounts table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS monitoring_accounts (
                id SERIAL PRIMARY KEY,
                ssid VARCHAR(255) NOT NULL,
                account_type VARCHAR(50) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Trades table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                asset VARCHAR(50) NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                direction VARCHAR(10) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """))
        
        print("✅ Tables created")
    
    # Seed initial data
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        print("🌱 Seeding initial data...")
        
        # Check if admin exists
        result = await session.execute(text("SELECT id FROM users WHERE username = 'admin'"))
        admin = result.scalar()
        
        if not admin:
            # Create admin user (password: admin123)
            await session.execute(text("""
                INSERT INTO users (username, email, password_hash, is_superuser)
                VALUES ('admin', 'admin@autotrade.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1.', TRUE)
            """))
            print("👤 Admin user created (admin/admin123)")
        
        # Check if monitoring accounts exist
        result = await session.execute(text("SELECT COUNT(*) FROM monitoring_accounts WHERE is_active = TRUE"))
        count = result.scalar()
        
        if count == 0:
            # Add sample monitoring account (PAYOUT type)
            await session.execute(text("""
                INSERT INTO monitoring_accounts (ssid, account_type, is_active)
                VALUES ('42["auth",{"session":"demo-session-placeholder"}]', 'PAYOUT', TRUE)
            """))
            print("📡 Sample PAYOUT monitoring account created")
            
            # Add sample ATIVOS account
            await session.execute(text("""
                INSERT INTO monitoring_accounts (ssid, account_type, is_active)
                VALUES ('42["auth",{"session":"demo-ativos-placeholder"}]', 'ATIVOS', TRUE)
            """))
            print("📡 Sample ATIVOS monitoring account created")
        
        await session.commit()
        print("✅ Data seeded successfully")
    
    await engine.dispose()
    print("🎉 Railway database setup complete!")

if __name__ == "__main__":
    asyncio.run(setup_database())
