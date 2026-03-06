"""Accounts router"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from typing import List, Optional
from datetime import datetime, timedelta
from loguru import logger

from core.database import get_db
from core.security import get_current_active_user
from models import User, Account
from schemas import AccountResponse, AccountUpdate
from pydantic import BaseModel

class ModeUpdate(BaseModel):
    autotrade_demo: bool
    autotrade_real: bool

class AccountCreate(BaseModel):
    """Account creation schema"""
    name: str
    autotrade_demo: bool = True
    autotrade_real: bool = False
    ssid_demo: Optional[str] = None
    ssid_real: Optional[str] = None

router = APIRouter()


@router.get("", response_model=List[AccountResponse])
async def get_accounts(
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all accounts for current user (or for another user if admin)"""
    # Se user_id fornecido e usuário é admin, buscar contas desse usuário
    target_user_id = user_id if (user_id and current_user.is_superuser) else current_user.id
    is_admin = user_id is not None and current_user.is_superuser
    
    result = await db.execute(
        select(Account).where(Account.user_id == target_user_id)
    )
    accounts = result.scalars().all()
    
    # Se admin está consultando e usuário não tem conta, criar uma automaticamente
    if is_admin and not accounts:
        # Buscar dados do usuário alvo
        from models import User
        target_user_result = await db.execute(
            select(User).where(User.id == target_user_id)
        )
        target_user = target_user_result.scalar_one_or_none()
        
        if target_user:
            logger.info(f"[ADMIN] Criando conta automaticamente para usuário {target_user_id}")
            new_account = Account(
                user_id=target_user_id,
                name=f"Conta de {target_user.name}",
                autotrade_demo=True,
                autotrade_real=False,
                uid=0,
                platform=0
            )
            db.add(new_account)
            await db.commit()
            await db.refresh(new_account)
            accounts = [new_account]
    
    return [
        AccountResponse(
            id=account.id,
            user_id=account.user_id,
            ssid_demo=account.ssid_demo,
            ssid_real=account.ssid_real,
            name=account.name,
            autotrade_demo=account.autotrade_demo,
            autotrade_real=account.autotrade_real,
            uid=account.uid,
            platform=account.platform,
            balance_demo=account.balance_demo,
            balance_real=account.balance_real,
            currency=account.currency,
            is_active=account.is_active,
            last_connected=account.last_connected,
            created_at=account.created_at,
            updated_at=account.updated_at
        )
        for account in accounts
    ]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new trading account"""
    account = Account(
        user_id=current_user.id,
        name=account_data.name,
        autotrade_demo=account_data.autotrade_demo,
        autotrade_real=account_data.autotrade_real,
        ssid_demo=account_data.ssid_demo,
        ssid_real=account_data.ssid_real
    )
    
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        ssid_demo=account.ssid_demo,
        ssid_real=account.ssid_real,
        name=account.name,
        autotrade_demo=account.autotrade_demo,
        autotrade_real=account.autotrade_real,
        uid=account.uid,
        platform=account.platform,
        balance_demo=account.balance_demo,
        balance_real=account.balance_real,
        currency=account.currency,
        is_active=account.is_active,
        last_connected=account.last_connected,
        created_at=account.created_at,
        updated_at=account.updated_at
    )


@router.put("/me", response_model=AccountResponse)
async def update_my_account(
    mode_update: ModeUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user's account mode (demo/real)"""
    result = await db.execute(
        select(Account).where(
            Account.user_id == current_user.id
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        # Criar conta automaticamente se não existir
        account = Account(
            user_id=current_user.id,
            name=f"Conta de {current_user.name}",
            autotrade_demo=True,
            autotrade_real=False,
            uid=0,
            platform=0
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

    # Detectar mudança de modo para desconectar conexão anterior
    old_demo = account.autotrade_demo
    old_real = account.autotrade_real

    logger.info(f"🔄 [update_my_account] Atualizando conta: old_demo={old_demo}, old_real={old_real}", extra={
        "user_name": current_user.name if current_user else "",
        "account_id": account.id[:8] if account else "",
        "account_type": "demo" if account and account.autotrade_demo else "real"
    })
    logger.info(f"🔄 [update_my_account] Recebido: autotrade_demo={mode_update.autotrade_demo}, autotrade_real={mode_update.autotrade_real}", extra={
        "user_name": current_user.name if current_user else "",
        "account_id": account.id[:8] if account else "",
        "account_type": "demo" if account and account.autotrade_demo else "real"
    })

    # Alternar corretamente autotrade_demo e autotrade_real
    # Nunca ambos devem ser 1
    # Garantir que pelo menos um seja 1 (usuário sempre tem uma conexão ativa)
    # Verificar se o usuário está tentando definir um modo específico
    if mode_update.autotrade_demo is True and mode_update.autotrade_real is False:
        # Usuário quer demo
        account.autotrade_demo = True
        account.autotrade_real = False
        logger.info(f"🔄 [update_my_account] Definindo conta como DEMO", extra={
            "user_name": current_user.name if current_user else "",
            "account_id": account.id[:8] if account else "",
            "account_type": "demo"
        })
    elif mode_update.autotrade_real is True and mode_update.autotrade_demo is False:
        # Usuário quer real
        account.autotrade_demo = False
        account.autotrade_real = True
        logger.info(f"🔄 [update_my_account] Definindo conta como REAL", extra={
            "user_name": current_user.name if current_user else "",
            "account_id": account.id[:8] if account else "",
            "account_type": "real"
        })
    else:
        # Se ambos são True ou ambos são False, manter valores atuais ou definir demo como True por padrão
        if not account.autotrade_demo and not account.autotrade_real:
            account.autotrade_demo = True
            account.autotrade_real = False
            logger.info(f"🔄 [update_my_account] Definindo conta como DEMO (padrão)", extra={
                "user_name": current_user.name if current_user else "",
                "account_id": account.id[:8] if account else "",
                "account_type": "demo"
            })
        else:
            logger.info(f"🔄 [update_my_account] Mantendo valores atuais: demo={account.autotrade_demo}, real={account.autotrade_real}", extra={
                "user_name": current_user.name if current_user else "",
                "account_id": account.id[:8] if account else "",
                "account_type": "demo" if account.autotrade_demo else "real"
            })

    account.updated_at = datetime.utcnow()

    logger.info(f"🔄 [update_my_account] Antes do commit: demo={account.autotrade_demo}, real={account.autotrade_real}", extra={
        "user_name": current_user.name if current_user else "",
        "account_id": account.id[:8] if account else "",
        "account_type": "demo" if account.autotrade_demo else "real"
    })

    await db.commit()
    await db.refresh(account)

    logger.info(f"🔄 [update_my_account] Após commit: demo={account.autotrade_demo}, real={account.autotrade_real}", extra={
        "user_name": current_user.name if current_user else "",
        "account_id": account.id[:8] if account else "",
        "account_type": "demo" if account.autotrade_demo else "real"
    })

    # Se o modo mudou, desconectar a conexão anterior e conectar a nova imediatamente
    if old_demo != account.autotrade_demo or old_real != account.autotrade_real:
        from services.data_collector.realtime import data_collector
        from models import Strategy, AutoTradeConfig
        from services.notifications.telegram import telegram_service

        # Buscar estratégias ativas antes de desativar (para notificação)
        strategies_result = await db.execute(
            select(Strategy).where(and_(
                Strategy.user_id == current_user.id,
                Strategy.is_active == True
            ))
        )
        active_strategies = strategies_result.scalars().all()
        strategy_names = [s.name for s in active_strategies]

        # Desativar todas as estratégias e configs de autotrade do usuário para evitar conflitos
        await db.execute(
            update(Strategy).where(Strategy.user_id == current_user.id).values(is_active=False)
        )
        # Usar subquery para desativar configs de autotrade (update não suporta join)
        from sqlalchemy import select as sql_select
        config_ids_result = await db.execute(
            sql_select(AutoTradeConfig.id).join(Account, AutoTradeConfig.account_id == Account.id)
            .where(Account.user_id == current_user.id)
        )
        config_ids = [row[0] for row in config_ids_result.fetchall()]
        if config_ids:
            await db.execute(
                update(AutoTradeConfig).where(AutoTradeConfig.id.in_(config_ids)).values(
                    is_active=False,
                    win_consecutive=0,
                    loss_consecutive=0,
                    total_wins=0,
                    total_losses=0,
                    soros_level=0,
                    soros_amount=0.0,
                    martingale_level=0,
                    martingale_amount=0.0
                )
            )
        await db.commit()
        logger.info(f" Todas as estratégias e configs de autotrade do usuário {current_user.id} foram desativadas e contadores resetados", extra={
            "user_name": current_user.name if current_user else "",
            "account_id": account.id[:8] if account else "",
            "account_type": "demo" if account and account.autotrade_demo else "real"
        })

        # Invalidar cache de configurações de autotrade para forçar recarga
        try:
            if hasattr(data_collector, 'invalidate_autotrade_configs_cache'):
                await data_collector.invalidate_autotrade_configs_cache()
                logger.info(f" Cache de configs invalidado após troca de conta", extra={
                    "user_name": current_user.name if current_user else "",
                    "account_id": account.id[:8] if account else "",
                    "account_type": "demo" if account and account.autotrade_demo else "real"
                })
        except Exception as e:
            logger.error(f"Erro ao invalidar cache de configs: {e}", extra={
                "user_name": current_user.name if current_user else "",
                "account_id": account.id[:8] if account else "",
                "account_type": "demo" if account and account.autotrade_demo else "real"
            })

        # Determinar de onde e para onde estamos mudando
        from_type = None
        to_type = None
        ssid = None

        if old_real and account.autotrade_demo:
            # Mudando de real para demo
            from_type = 'real'
            to_type = 'demo'
            ssid = account.ssid_demo
        elif old_demo and account.autotrade_real:
            # Mudando de demo para real
            from_type = 'demo'
            to_type = 'real'
            ssid = account.ssid_real

        # Se houve mudança e temos SSID para conectar
        if from_type and to_type and ssid:
            try:
                await data_collector.connection_manager.switch_connection(
                    account.id, from_type, to_type, ssid
                )
            except Exception as e:
                logger.error(f"Erro ao alternar conexão: {e}", extra={
                    "user_name": current_user.name if current_user else "",
                    "account_id": account.id[:8] if account else "",
                    "account_type": "demo" if account and account.autotrade_demo else "real"
                })

        # Enviar notificação da troca de conta
        try:
            user_chat_id = current_user.telegram_chat_id
            if user_chat_id and from_type and to_type:
                # Criar mensagem organizada
                message = f"""
🔄 <b>TROCA DE CONTA REALIZADA!</b>

📊 Conta: {account.name}
🔀 De: {from_type.upper()}
➡️ Para: {to_type.upper()}
"""
                if strategy_names:
                    message += f"""
📋 Estratégias desligadas:
"""
                    for name in strategy_names:
                        message += f"   • {name}\n"
                else:
                    message += """
📋 Nenhuma estratégia estava ativa
"""
                message += f"""
⏰ {(datetime.utcnow() - timedelta(hours=3)).strftime('%H:%M:%S')}
"""
                await telegram_service.send_message(message, chat_id=user_chat_id)
                logger.info(f"✓ Notificação de troca de conta enviada para usuário {current_user.id}", extra={
                    "user_name": current_user.name if current_user else "",
                    "account_id": account.id[:8] if account else "",
                    "account_type": "demo" if account and account.autotrade_demo else "real"
                })
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de troca de conta: {e}", extra={
                "user_name": current_user.name if current_user else "",
                "account_id": account.id[:8] if account else "",
                "account_type": "demo" if account and account.autotrade_demo else "real"
            })

    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        ssid_demo=account.ssid_demo,
        ssid_real=account.ssid_real,
        name=account.name,
        autotrade_demo=account.autotrade_demo,
        autotrade_real=account.autotrade_real,
        uid=account.uid,
        platform=account.platform,
        balance_demo=account.balance_demo,
        balance_real=account.balance_real,
        currency=account.currency,
        is_active=account.is_active,
        last_connected=account.last_connected,
        created_at=account.created_at,
        updated_at=account.updated_at
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get account details"""
    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == current_user.id
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        ssid_demo=account.ssid_demo,
        ssid_real=account.ssid_real,
        name=account.name,
        autotrade_demo=account.autotrade_demo,
        autotrade_real=account.autotrade_real,
        uid=account.uid,
        platform=account.platform,
        balance_demo=account.balance_demo,
        balance_real=account.balance_real,
        currency=account.currency,
        is_active=account.is_active,
        last_connected=account.last_connected,
        created_at=account.created_at,
        updated_at=account.updated_at
    )


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    account_update: AccountUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update account"""
    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == current_user.id
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    if account_update.name is not None:
        account.name = account_update.name
    
    if 'ssid_demo' in account_update.model_fields_set:
        account.ssid_demo = account_update.ssid_demo
    
    if 'ssid_real' in account_update.model_fields_set:
        account.ssid_real = account_update.ssid_real
    
    if account_update.is_active is not None:
        account.is_active = account_update.is_active

    account.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(account)

    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        ssid_demo=account.ssid_demo,
        ssid_real=account.ssid_real,
        name=account.name,
        autotrade_demo=account.autotrade_demo,
        autotrade_real=account.autotrade_real,
        uid=account.uid,
        platform=account.platform,
        balance_demo=account.balance_demo,
        balance_real=account.balance_real,
        currency=account.currency,
        is_active=account.is_active,
        last_connected=account.last_connected,
        created_at=account.created_at,
        updated_at=account.updated_at
    )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete account"""
    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == current_user.id
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    await db.delete(account)
    await db.commit()
