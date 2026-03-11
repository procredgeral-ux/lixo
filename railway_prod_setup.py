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

async def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database"""
    result = await conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = :table_name
        )
    """), {"table_name": table_name})
    return result.scalar()

async def setup_database():
    """Create tables and seed initial data"""
    logger.info("🚀 Setting up Railway production database...")
    logger.info(f"📍 Using database: {DATABASE_URL.split('@')[0]}@...")
    
    # Ensure we're using asyncpg driver
    db_url = DATABASE_URL
    if db_url.startswith('postgresql://') and not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')
        logger.info("🔄 Converted URL to use asyncpg driver")
    
    engine = create_async_engine(db_url, echo=False)
    
    try:
        async with engine.begin() as conn:
            # Check which tables exist
            tables_to_check = ['users', 'monitoring_accounts', 'trades', 'indicators', 'strategy_indicators', 'strategies']
            existing_tables = []
            for table in tables_to_check:
                if await table_exists(conn, table):
                    existing_tables.append(table)
            
            if existing_tables:
                logger.info(f"📋 Existing tables found: {', '.join(existing_tables)}")
            
            # Create users table if not exists
            if not await table_exists(conn, 'users'):
                logger.info("📦 Creating users table...")
                await conn.execute(text("""
                    CREATE TABLE users (
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
                logger.info("✅ users table created")
            else:
                logger.info("📋 users table already exists")
            
            # Create monitoring_accounts table if not exists
            if not await table_exists(conn, 'monitoring_accounts'):
                logger.info("📦 Creating monitoring_accounts table...")
                await conn.execute(text("""
                    CREATE TABLE monitoring_accounts (
                        id SERIAL PRIMARY KEY,
                        ssid VARCHAR(255) NOT NULL,
                        account_type VARCHAR(50) NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                logger.info("✅ monitoring_accounts table created")
            else:
                logger.info("📋 monitoring_accounts table already exists")
            
            # Create trades table if not exists
            if not await table_exists(conn, 'trades'):
                logger.info("📦 Creating trades table...")
                await conn.execute(text("""
                    CREATE TABLE trades (
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
                logger.info("✅ trades table created")
            else:
                logger.info("📋 trades table already exists")
            
            # Create indicators table if not exists
            if not await table_exists(conn, 'indicators'):
                logger.info("📦 Creating indicators table...")
                await conn.execute(text("""
                    CREATE TABLE indicators (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) UNIQUE NOT NULL,
                        type VARCHAR(50) NOT NULL,
                        description TEXT,
                        parameters JSONB DEFAULT '{}',
                        is_active BOOLEAN DEFAULT TRUE,
                        is_default BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                logger.info("✅ indicators table created")
            else:
                logger.info("📋 indicators table already exists")
            
            # Create strategies table if not exists (needed for FK)
            if not await table_exists(conn, 'strategies'):
                logger.info("📦 Creating strategies table...")
                await conn.execute(text("""
                    CREATE TABLE strategies (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) UNIQUE NOT NULL,
                        description TEXT,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                logger.info("✅ strategies table created")
            else:
                logger.info("📋 strategies table already exists")
            
            # Create strategy_indicators table if not exists
            if not await table_exists(conn, 'strategy_indicators'):
                logger.info("📦 Creating strategy_indicators table...")
                await conn.execute(text("""
                    CREATE TABLE strategy_indicators (
                        id SERIAL PRIMARY KEY,
                        strategy_id INTEGER REFERENCES strategies(id) ON DELETE CASCADE,
                        indicator_id INTEGER REFERENCES indicators(id) ON DELETE CASCADE,
                        parameters JSONB DEFAULT '{}',
                        weight FLOAT DEFAULT 1.0,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                logger.info("✅ strategy_indicators table created")
            else:
                logger.info("📋 strategy_indicators table already exists")
            
            await conn.commit()
            logger.info("✅ All tables created/verified successfully")
        
        # Seed initial data
        logger.info("🌱 Starting seed process...")
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
            
            await session.commit()
            logger.info("✅ Session committed after admin")
            
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
            logger.info("✅ Session committed after monitoring accounts")
            
            # Seed default indicators
            result = await session.execute(text("SELECT COUNT(*) FROM indicators WHERE is_default = TRUE"))
            ind_count = result.scalar()
            
            if ind_count == 0:
                logger.info("📊 Seeding default indicators...")
                default_indicators = [
                    ('RSI', 'oscillator', 'Relative Strength Index', {'period': 14, 'overbought': 70, 'oversold': 30}, True),
                    ('MACD', 'trend', 'Moving Average Convergence Divergence', {'fast': 12, 'slow': 26, 'signal': 9}, True),
                    ('Bollinger Bands', 'volatility', 'Bollinger Bands', {'period': 20, 'std_dev': 2}, True),
                    ('Moving Average', 'trend', 'Simple Moving Average', {'period': 20}, True),
                    ('Stochastic', 'oscillator', 'Stochastic Oscillator', {'k_period': 14, 'd_period': 3}, True),
                    ('ATR', 'volatility', 'Average True Range', {'period': 14}, True),
                    ('ADX', 'trend', 'Average Directional Index', {'period': 14}, True),
                ]
                for name, type_, desc, params, is_def in default_indicators:
                    await session.execute(text("""
                        INSERT INTO indicators (name, type, description, parameters, is_active, is_default)
                        VALUES (:name, :type, :desc, :params, TRUE, :is_def)
                    """), {'name': name, 'type': type_, 'desc': desc, 'params': str(params), 'is_def': is_def})
                logger.info(f"✅ {len(default_indicators)} default indicators created")
            else:
                logger.info(f"📊 {ind_count} indicators already exist")
            
            await session.commit()
            logger.info("✅ Session committed after indicators")
        
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
