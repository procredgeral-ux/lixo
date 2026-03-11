"""Railway production database setup - Creates tables and seeds data"""
import asyncio
import os
import sys

# Ensure production environment
os.environ['ENVIRONMENT'] = 'production'

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from core.config import settings
from loguru import logger

# Get database URL - remove sslmode if present for asyncpg
DATABASE_URL = settings.DATABASE_URL
if 'sslmode=' in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split('?')[0]
    logger.info("Removed sslmode from URL for asyncpg compatibility")

async def setup_database():
    """Create tables and seed initial data"""
    logger.info("🚀 Setting up Railway production database...")
    logger.info(f"📍 Using database: {DATABASE_URL.split('@')[0]}@...")
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        async with engine.begin() as conn:
            # Create users table
            logger.info("📦 Creating users table...")
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
            
            # Create monitoring_accounts table
            logger.info("📦 Creating monitoring_accounts table...")
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS monitoring_accounts (
                    id SERIAL PRIMARY KEY,
                    ssid VARCHAR(255) NOT NULL,
                    account_type VARCHAR(50) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Create trades table
            logger.info("📦 Creating trades table...")
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
            
            logger.info("✅ Tables created successfully")
        
        # Seed initial data
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            logger.info("🌱 Seeding initial data...")
            
            # Check if admin exists
            result = await session.execute(text("SELECT id FROM users WHERE username = 'admin'"))
            admin = result.scalar()
            
            if not admin:
                # Create admin user (password: admin123) - bcrypt hash
                await session.execute(text("""
                    INSERT INTO users (username, email, password_hash, is_superuser, is_active)
                    VALUES ('admin', 'admin@autotrade.com', 
                            '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1.', 
                            TRUE, TRUE)
                """))
                logger.info("👤 Admin user created (username: admin, password: admin123)")
            else:
                logger.info("👤 Admin user already exists")
            
            # Check if monitoring accounts exist
            result = await session.execute(text("SELECT COUNT(*) FROM monitoring_accounts WHERE is_active = TRUE"))
            count = result.scalar()
            
            if count == 0:
                # Add sample PAYOUT monitoring account
                await session.execute(text("""
                    INSERT INTO monitoring_accounts (ssid, account_type, is_active)
                    VALUES ('42["auth",{"session":"demo-payout-session-placeholder"}]', 'PAYOUT', TRUE)
                """))
                logger.info("📡 Sample PAYOUT monitoring account created")
                
                # Add sample ATIVOS account
                await session.execute(text("""
                    INSERT INTO monitoring_accounts (ssid, account_type, is_active)
                    VALUES ('42["auth",{"session":"demo-ativos-session-placeholder"}]', 'ATIVOS', TRUE)
                """))
                logger.info("📡 Sample ATIVOS monitoring account created")
            else:
                logger.info(f"📡 {count} monitoring accounts already exist")
            
            await session.commit()
            logger.info("✅ Data seeded successfully")
        
        logger.info("🎉 Railway production database setup complete!")
        logger.info("📝 You can now login with: admin / admin123")
        
    except Exception as e:
        logger.error(f"❌ Database setup failed: {e}")
        raise
    finally:
        await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(setup_database())
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)
