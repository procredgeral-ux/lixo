"""Seed data para inicialização do banco"""
import asyncio
from datetime import datetime
from sqlalchemy import select
from core.database import get_db_context
from core.security import get_password_hash
from models import User, Account, Strategy
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_admin_and_account():
    """Criar usuário admin padrão e sua account"""
    async with get_db_context() as db:
        # Verificar se admin já existe
        result = await db.execute(
            select(User).where(User.email == "admin@gmail.com")
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            logger.info("Usuário admin já existe")
            # Verificar se tem account
            result = await db.execute(
                select(Account).where(Account.user_id == existing_user.id)
            )
            existing_account = result.scalar_one_or_none()
            if existing_account:
                logger.info("Account do admin já existe")
                return existing_user.id, existing_account.id
            # Criar account para admin existente
            account = Account(
                user_id=existing_user.id,
                name="Conta Principal",
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.add(account)
            await db.commit()
            logger.info("✅ Account criada para admin existente")
            return existing_user.id, account.id
        
        # Criar admin
        admin = User(
            email="admin@gmail.com",
            name="Administrador",
            hashed_password=get_password_hash("@Leandro1228"),
            role="admin",
            is_active=True,
            is_superuser=True,
            created_at=datetime.utcnow()
        )
        
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        logger.info("✅ Usuário admin criado: admin@gmail.com")
        
        # Criar account para o admin
        account = Account(
            user_id=admin.id,
            name="Conta Principal",
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        logger.info("✅ Account criada para admin")
        
        return admin.id, account.id


async def seed_strategies(user_id: str, account_id: str):
    """Criar strategies padrão do sistema"""
    async with get_db_context() as db:
        strategies_data = [
            {
                "name": "Confluence",
                "description": "Estratégia de confluência multi-indicadores",
                "type": "confluence",
                "is_active": True,
                "parameters": {
                    "rsi_period": 14,
                    "rsi_overbought": 70,
                    "rsi_oversold": 30,
                    "ema_fast": 9,
                    "ema_slow": 21,
                    "confidence_threshold": 0.7
                }
            },
            {
                "name": "EMA Cross",
                "description": "Cruzamento de médias móveis exponenciais",
                "type": "ema_cross",
                "is_active": True,
                "parameters": {
                    "fast_period": 9,
                    "slow_period": 21,
                    "signal_period": 5
                }
            },
            {
                "name": "RSI Divergence",
                "description": "Divergência no indicador RSI",
                "type": "rsi_divergence",
                "is_active": True,
                "parameters": {
                    "period": 14,
                    "overbought": 70,
                    "oversold": 30
                }
            },
            {
                "name": "Support Resistance",
                "description": "Trading em níveis de suporte e resistência",
                "type": "support_resistance",
                "is_active": True,
                "parameters": {
                    "lookback_period": 20,
                    "touch_threshold": 0.02
                }
            },
            {
                "name": "Breakout",
                "description": "Estratégia de breakout de volatilidade",
                "type": "breakout",
                "is_active": True,
                "parameters": {
                    "atr_period": 14,
                    "multiplier": 1.5
                }
            },
            {
                "name": "Trend Following",
                "description": "Seguimento de tendência com ADX",
                "type": "trend_following",
                "is_active": True,
                "parameters": {
                    "adx_period": 14,
                    "adx_threshold": 25,
                    "di_period": 14
                }
            },
            {
                "name": "Volatility Squeeze",
                "description": "Squeeze de volatilidade (Bollinger + Keltner)",
                "type": "volatility_squeeze",
                "is_active": True,
                "parameters": {
                    "bb_period": 20,
                    "bb_std": 2.0,
                    "kc_period": 20,
                    "kc_multiplier": 1.5
                }
            },
            {
                "name": "Volume Profile",
                "description": "Análise de perfil de volume",
                "type": "volume_profile",
                "is_active": True,
                "parameters": {
                    "lookback": 20,
                    "volume_threshold": 1.5
                }
            }
        ]
        
        for strategy_data in strategies_data:
            # Verificar se já existe
            result = await db.execute(
                select(Strategy).where(Strategy.name == strategy_data["name"])
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.info(f"Strategy '{strategy_data['name']}' já existe")
                continue
            
            # Criar strategy
            strategy = Strategy(
                name=strategy_data["name"],
                description=strategy_data["description"],
                type=strategy_data["type"],
                is_active=strategy_data["is_active"],
                user_id=user_id,
                account_id=account_id,
                assets=[],
                parameters=strategy_data["parameters"],
                created_at=datetime.utcnow()
            )
            
            db.add(strategy)
            logger.info(f"✅ Strategy criada: {strategy_data['name']}")
        
        await db.commit()


async def run_seed():
    """Executar todos os seeds"""
    logger.info("🌱 Iniciando seed de dados...")
    
    try:
        # Criar/obter admin e sua account
        user_id, account_id = await seed_admin_and_account()
        logger.info(f"Using user_id: {user_id}, account_id: {account_id}")
        
        # Criar strategies
        await seed_strategies(user_id, account_id)
        logger.info("✅ Seed concluído com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro durante seed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_seed())
