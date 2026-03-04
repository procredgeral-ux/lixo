"""Users router"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
from datetime import datetime, timedelta
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.database import get_db
from core.security import get_current_active_user
from models import User, Trade, Account, Strategy, AutoTradeConfig
from schemas import UserResponse, UserUpdate, UserStats, MessageResponse
from services.notifications.telegram import telegram_service
from api.decorators import cache_response
from pydantic import validator


class TelegramLinkResponse(BaseModel):
    """Response schema for Telegram link"""
    message: str
    telegram_username: str
    telegram_chat_id: int


class LinkTelegramRequest(BaseModel):
    telegram_username: str
    
    @validator('telegram_username')
    def validate_telegram_username(cls, v):
        """Valida formato do username do Telegram"""
        if v:
            # Remove @ se presente
            username = v.lstrip('@')
            # Validar formato: 5-32 caracteres alfanuméricos e underscore
            if not (5 <= len(username) <= 32):
                raise ValueError('Username deve ter entre 5 e 32 caracteres')
            if not username.replace('_', '').isalnum():
                raise ValueError('Username deve conter apenas letras, números e underscore')
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    
    @validator('new_password')
    def validate_password_strength(cls, v):
        """Valida força da senha"""
        if len(v) < 8:
            raise ValueError('A senha deve ter pelo menos 8 caracteres')
        if v == cls.current_password:
            raise ValueError('A nova senha deve ser diferente da senha atual')
        return v


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """Get current user information"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        telegram_chat_id=current_user.telegram_chat_id,
        telegram_username=current_user.telegram_username,
        role=current_user.role or 'free',
        vip_start_date=current_user.vip_start_date,
        vip_end_date=current_user.vip_end_date
    )


@router.get("/me/stats", response_model=UserStats)
@cache_response(ttl=120, key_prefix="users:stats")
async def get_user_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user statistics including demo and real account stats"""
    # Get user's accounts
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    accounts = result.scalars().all()
    
    # Calculate demo stats
    demo_account = next((acc for acc in accounts if acc.ssid_demo is not None), None)
    demo_balance = demo_account.balance_demo if demo_account else 0.0
    
    # Get demo trades
    demo_trades_result = await db.execute(
        select(Trade)
        .join(Account)
        .where(
            Account.user_id == current_user.id,
            Trade.connection_type == 'demo'
        )
    )
    demo_trades = demo_trades_result.scalars().all()
    
    demo_total_trades = len(demo_trades)
    demo_trades_with_profit = sum(1 for t in demo_trades if t.profit is not None)
    demo_winning_trades = sum(1 for t in demo_trades if t.profit and t.profit > 0)
    demo_losing_trades = sum(1 for t in demo_trades if t.profit and t.profit < 0)
    demo_win_rate = (demo_winning_trades / demo_trades_with_profit * 100) if demo_trades_with_profit > 0 else 0
    demo_loss_rate = (demo_losing_trades / demo_trades_with_profit * 100) if demo_trades_with_profit > 0 else 0
    
    # Calculate real stats
    real_account = next((acc for acc in accounts if acc.ssid_real is not None), None)
    real_balance = real_account.balance_real if real_account else 0.0
    
    # Get real trades
    real_trades_result = await db.execute(
        select(Trade)
        .join(Account)
        .where(
            Account.user_id == current_user.id,
            Trade.connection_type == 'real'
        )
    )
    real_trades = real_trades_result.scalars().all()
    
    real_total_trades = len(real_trades)
    real_trades_with_profit = sum(1 for t in real_trades if t.profit is not None)
    real_winning_trades = sum(1 for t in real_trades if t.profit and t.profit > 0)
    real_losing_trades = sum(1 for t in real_trades if t.profit and t.profit < 0)
    real_win_rate = (real_winning_trades / real_trades_with_profit * 100) if real_trades_with_profit > 0 else 0
    real_loss_rate = (real_losing_trades / real_trades_with_profit * 100) if real_trades_with_profit > 0 else 0
    
    # Calcular campos adicionais para dashboard usando histórico real do usuário
    all_trades = demo_trades + real_trades
    
    # Filtrar apenas trades com status win ou loss (trades finalizados)
    completed_trades = [t for t in all_trades if t.status in ['win', 'loss']]
    
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    
    # Calcular lucro de hoje (apenas trades finalizados com profit definido)
    trades_today = [t for t in completed_trades if t.placed_at and t.placed_at >= today_start and t.profit is not None]
    lucro_hoje = sum(t.profit for t in trades_today)
    
    # Calcular lucro da semana (apenas trades finalizados com profit definido)
    trades_week = [t for t in completed_trades if t.placed_at and t.placed_at >= week_start and t.profit is not None]
    lucro_semana = sum(t.profit for t in trades_week)
    
    # Calcular trades de hoje (apenas trades finalizados)
    trades_hoje = len(trades_today)
    
    # Calcular maior ganho e maior perda (apenas trades finalizados)
    profits = [t.profit for t in completed_trades if t.profit is not None]
    maior_ganho = max(profits) if profits else 0.0
    maior_perda = min(profits) if profits else 0.0
    
    # Calcular taxa de sucesso (win rate geral - apenas trades finalizados)
    total_winning = sum(1 for t in completed_trades if t.profit and t.profit > 0)
    total_with_profit = sum(1 for t in completed_trades if t.profit is not None)
    taxa_sucesso = (total_winning / total_with_profit * 100) if total_with_profit > 0 else 0.0
    
    # Calcular melhor estratégia (estratégia com maior win rate - apenas trades finalizados)
    strategy_stats = {}
    strategy_ids = set()
    for trade in completed_trades:
        if trade.strategy_id:
            if trade.strategy_id not in strategy_stats:
                strategy_stats[trade.strategy_id] = {'wins': 0, 'total': 0}
            strategy_stats[trade.strategy_id]['total'] += 1
            if trade.profit and trade.profit > 0:
                strategy_stats[trade.strategy_id]['wins'] += 1
            strategy_ids.add(trade.strategy_id)
    
    melhor_estrategia = "N/A"
    melhor_win_rate = 0
    
    # Buscar todas as estratégias de uma vez para evitar N+1 queries
    if strategy_ids:
        strategies_result = await db.execute(
            select(Strategy).where(Strategy.id.in_(list(strategy_ids)))
        )
        strategies_map = {s.id: s.name for s in strategies_result.scalars().all()}
        
        for strategy_id, stats in strategy_stats.items():
            if stats['total'] > 0:
                win_rate = (stats['wins'] / stats['total'] * 100)
                if win_rate > melhor_win_rate:
                    melhor_win_rate = win_rate
                    melhor_estrategia = strategies_map.get(strategy_id, "N/A")
    
    # Calcular tempo ativo (soma de durações de trades finalizados)
    total_seconds = sum(t.duration for t in completed_trades if t.duration)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    tempo_ativo = f"{hours}h {minutes}m"
    
    # Calcular highest_balance (maior saldo máximo entre todas as configs do usuário)
    highest_balance = None
    if accounts:
        account_ids = [acc.id for acc in accounts]
        autotrade_result = await db.execute(
            select(AutoTradeConfig.highest_balance)
            .where(AutoTradeConfig.account_id.in_(account_ids))
            .where(AutoTradeConfig.highest_balance.isnot(None))
            .order_by(AutoTradeConfig.highest_balance.desc())
        )
        highest_balance_row = autotrade_result.first()
        if highest_balance_row:
            highest_balance = highest_balance_row[0]
    
    return UserStats(
        balance_demo=demo_balance,
        balance_real=real_balance,
        win_rate_demo=demo_win_rate,
        win_rate_real=real_win_rate,
        loss_rate_demo=demo_loss_rate,
        loss_rate_real=real_loss_rate,
        total_trades_demo=demo_total_trades,
        total_trades_real=real_total_trades,
        # Campos adicionais para dashboard
        lucro_hoje=lucro_hoje,
        lucro_semana=lucro_semana,
        melhor_estrategia=melhor_estrategia,
        taxa_sucesso=taxa_sucesso,
        trades_hoje=trades_hoje,
        maior_ganho=maior_ganho,
        maior_perda=maior_perda,
        tempo_ativo=tempo_ativo,
        highest_balance=highest_balance,
    )


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user information"""
    # Update fields if provided
    if user_update.name is not None:
        current_user.name = user_update.name
    
    if user_update.email is not None:
        # Check if email already exists
        result = await db.execute(
            select(User).where(
                User.email == user_update.email,
                User.id != current_user.id
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        current_user.email = user_update.email

    current_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(current_user)

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        telegram_chat_id=current_user.telegram_chat_id,
        telegram_username=current_user.telegram_username,
        role=current_user.role or 'free',
        vip_start_date=current_user.vip_start_date,
        vip_end_date=current_user.vip_end_date
    )


@router.post("/me/link-telegram", response_model=TelegramLinkResponse)
@limiter.limit("3/minute")
async def link_telegram(
    request: Request,
    link_request: LinkTelegramRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Vincular Telegram à conta do usuário usando username"""
    # Capturar Chat IDs de usuários que enviaram mensagens para o bot
    await telegram_service.capture_chat_id_from_message()
    
    # Buscar Chat ID do Telegram a partir do username
    normalized_username = link_request.telegram_username.lstrip('@')
    chat_id = await telegram_service.get_chat_id_from_username(normalized_username)
    
    if not chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username não encontrado ou usuário não iniciou conversa com o bot. Por favor, envie uma mensagem para @tunestrade_bot antes de vincular."
        )
    
    # Impedir duplicidade de chat_id/username entre usuários
    existing_user_result = await db.execute(
        select(User).where(
            User.id != current_user.id,
            ((User.telegram_chat_id == chat_id) | (User.telegram_username == normalized_username))
        )
    )
    existing_user = existing_user_result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este Telegram já está vinculado a outra conta. Desvincule antes de continuar."
        )

    # Salvar telegram_chat_id e telegram_username
    current_user.telegram_chat_id = chat_id
    current_user.telegram_username = normalized_username
    current_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(current_user)
    
    return TelegramLinkResponse(
        message="Telegram vinculado com sucesso",
        telegram_username=current_user.telegram_username,
        telegram_chat_id=chat_id
    )


@router.post("/me/change-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    change_request: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Alterar senha do usuário"""
    from core.security import verify_password, get_password_hash
    
    # Verificar senha atual
    if not verify_password(change_request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta"
        )
    
    # Verificar se a nova senha é diferente da atual
    if verify_password(change_request.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nova senha deve ser diferente da senha atual"
        )
    
    # Atualizar senha
    current_user.hashed_password = get_password_hash(change_request.new_password)
    current_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(current_user)
    
    return MessageResponse(message="Senha alterada com sucesso")


@router.delete("/me/unlink-telegram", response_model=MessageResponse)
async def unlink_telegram(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Desvincular Telegram da conta do usuário"""
    current_user.telegram_chat_id = None
    current_user.telegram_username = None
    current_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(current_user)
    
    return MessageResponse(message="Telegram desvinculado com sucesso")
