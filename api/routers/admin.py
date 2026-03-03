from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel

from core.database import get_db
from models import User
from api.dependencies import get_current_active_user, get_current_superuser
from schemas import UserResponse

router = APIRouter(tags=["admin"])


class UserPlanResponse(BaseModel):
    """Response schema for user plan update"""
    role: str
    vip_start_date: datetime | None
    vip_end_date: datetime | None
    message: str


@router.get("/users")
async def list_all_users(
    search: str = Query(None, description="Buscar por nome, email, plano ou telegram username"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Listar todos os usuários (apenas superusuários)"""
    result = await db.execute(select(User))
    users = result.scalars().all()
    
    # Filtrar se houver termo de busca
    if search and search.strip():
        search_lower = search.lower().strip()
        users = [u for u in users if 
            (u.name and search_lower in u.name.lower()) or
            (u.email and search_lower in u.email.lower()) or
            (u.role and search_lower in u.role.lower()) or
            (u.telegram_username and search_lower in u.telegram_username.lower())
        ]
    
    return [
        UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
            telegram_chat_id=user.telegram_chat_id,
            telegram_username=user.telegram_username,
            role=user.role or 'free',
            vip_start_date=user.vip_start_date,
            vip_end_date=user.vip_end_date
        ) for user in users
    ]


@router.get("/users/search")
async def search_user_by_email(
    email: str = Query(..., description="Email do usuário a buscar"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Buscar usuário por email (apenas superusuários)"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
        role=user.role or 'free',
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date
    )


@router.put("/users/{user_id}/plan", response_model=UserPlanResponse)
async def update_user_plan_admin(
    user_id: str,
    role: str = Query(..., description="Plano do usuário: 'free', 'vip', 'vip_plus'"),
    duration_days: int = Query(7, description="Duração em dias para VIP/VIP+"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Atualizar plano do usuário (apenas superusuários)"""
    # Validar role
    valid_roles = ['free', 'vip', 'vip_plus']
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Role inválido. Valores válidos: {', '.join(valid_roles)}"
        )
    
    # Buscar usuário
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    # Calcular datas de VIP
    now = datetime.utcnow()
    vip_start_date = None
    vip_end_date = None
    
    if role in ['vip', 'vip_plus']:
        vip_start_date = now
        vip_end_date = now + timedelta(days=duration_days)
    elif role == 'free':
        # Para plano free, remover datas VIP
        vip_start_date = None
        vip_end_date = None
    
    # Atualizar usuário
    user.role = role
    user.vip_start_date = vip_start_date
    user.vip_end_date = vip_end_date
    user.updated_at = now
    
    await db.commit()
    await db.refresh(user)
    
    logger.info(f"✓ [ADMIN] Plano do usuário {user.email} atualizado para {role.upper()}")
    
    return UserPlanResponse(
        role=user.role,
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date,
        message=f"Plano atualizado para {role.upper()}"
    )
