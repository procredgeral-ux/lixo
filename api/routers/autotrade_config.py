"""AutoTrade config router"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel
from loguru import logger

from core.database import get_db
from core.security import get_current_active_user
from models import User, AutoTradeConfig, Account, Strategy
from schemas import (
    AutoTradeConfigCreate,
    AutoTradeConfigUpdate,
    AutoTradeConfigResponse,
    MessageResponse
)

router = APIRouter()


class AvailableTimeframesResponse(BaseModel):
    """Response schema for available timeframes"""
    available_timeframes: List[dict]

@router.get("/available-timeframes", response_model=AvailableTimeframesResponse)
async def get_available_timeframes(
    current_user: User = Depends(get_current_active_user)
):
    """Retorna quais timeframes têm dados suficientes para análise"""
    try:
        from services.data_collector.realtime import data_collector
        
        # Lista padrão de todos os timeframes disponíveis na corretora
        all_timeframes = [
            {"value": 3, "label": "3s"},
            {"value": 5, "label": "5s"},
            {"value": 30, "label": "30s"},
            {"value": 60, "label": "1min"},
            {"value": 300, "label": "5min"},
            {"value": 900, "label": "15min"},
            {"value": 3600, "label": "1h"},
            {"value": 14400, "label": "4h"},
        ]
        
        if not data_collector:
            # Se data_collector não está disponível, retorna todos os timeframes
            # para permitir que o usuário possa configurar mesmo sem dados ainda
            logger.warning("Data collector não disponível, retornando todos os timeframes padrão")
            return AvailableTimeframesResponse(available_timeframes=all_timeframes)
        
        # Verificar cada timeframe
        available_timeframes = []
        
        for timeframe in all_timeframes:
            # Verificar se há dados suficientes para este timeframe
            has_sufficient_data = False
            
            # Verificar buffers de todos os ativos
            if hasattr(data_collector, '_candle_buffers') and data_collector._candle_buffers:
                for asset, buffers in data_collector._candle_buffers.items():
                    buffer = buffers.get(timeframe["value"], [])
                    if len(buffer) >= 20:  # Mínimo de 20 candles
                        has_sufficient_data = True
                        break
            
            # 🚨 CORREÇÃO: Incluir timeframe se tiver dados OU se for um timeframe padrão
            # Os timeframes 3s, 5s, 30s, 60s, 300s, 900s, 3600s e 14400s sempre estão disponíveis
            # na PocketOption, mesmo que ainda não tenhamos dados coletados
            is_common_timeframe = timeframe["value"] in [3, 5, 30, 60, 300, 900, 3600, 14400]
            
            if has_sufficient_data or is_common_timeframe:
                available_timeframes.append(timeframe)
        
        return AvailableTimeframesResponse(available_timeframes=available_timeframes)
        
    except Exception as e:
        logger.error(f"Erro ao obter timeframes disponíveis: {e}")
        # 🚨 CORREÇÃO: Em caso de erro, retornar os timeframes padrão para não bloquear o usuário
        fallback_timeframes = [
            {"value": 3, "label": "3s"},
            {"value": 5, "label": "5s"},
            {"value": 30, "label": "30s"},
            {"value": 60, "label": "1min"},
            {"value": 300, "label": "5min"},
            {"value": 900, "label": "15min"},
            {"value": 3600, "label": "1h"},
        ]
        return AvailableTimeframesResponse(available_timeframes=fallback_timeframes)


@router.post("", response_model=AutoTradeConfigResponse)
async def create_autotrade_config(
    config_data: AutoTradeConfigCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create auto trade configuration"""
    logger.info(f"📥 Recebendo config_data: {config_data}")
    logger.info(f"📥 execute_all_signals recebido: {getattr(config_data, 'execute_all_signals', 'NÃO ENCONTRADO')}")
    logger.info(f"📥 config_data.model_dump(): {config_data.model_dump()}")
    logger.info(f"📥 config_data.model_dump(exclude_unset=True): {config_data.model_dump(exclude_unset=True)}")

    # Verify account ownership
    account_result = await db.execute(
        select(Account).where(
            Account.id == config_data.account_id,
            Account.user_id == current_user.id
        )
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    # Verify strategy ownership if provided
    if config_data.strategy_id:
        strategy_result = await db.execute(
            select(Strategy).where(
                Strategy.id == config_data.strategy_id,
                Strategy.user_id == current_user.id
            )
        )
        strategy = strategy_result.scalar_one_or_none()

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )

    # Check if config already exists for this account AND strategy
    legacy_configs: List[AutoTradeConfig] = []
    if config_data.strategy_id:
        existing_query = select(AutoTradeConfig).where(
            AutoTradeConfig.account_id == config_data.account_id,
            AutoTradeConfig.strategy_id == config_data.strategy_id
        )
        existing_result = await db.execute(
            existing_query.order_by(AutoTradeConfig.updated_at.desc(), AutoTradeConfig.created_at.desc())
        )
        existing_configs = existing_result.scalars().all()

        # Buscar configs legadas sem strategy_id para eliminar duplicatas
        legacy_result = await db.execute(
            select(AutoTradeConfig).where(
                AutoTradeConfig.account_id == config_data.account_id,
                AutoTradeConfig.strategy_id == None
            ).order_by(AutoTradeConfig.updated_at.desc(), AutoTradeConfig.created_at.desc())
        )
        legacy_configs = legacy_result.scalars().all()

        # Fallback: reutilizar config legado sem strategy_id, se existir
        if not existing_configs and legacy_configs:
            existing_configs = legacy_configs
            legacy_configs = []
    else:
        existing_query = select(AutoTradeConfig).where(
            AutoTradeConfig.account_id == config_data.account_id,
            AutoTradeConfig.strategy_id == None
        )
        existing_result = await db.execute(
            existing_query.order_by(AutoTradeConfig.updated_at.desc(), AutoTradeConfig.created_at.desc())
        )
        existing_configs = existing_result.scalars().all()
    existing = existing_configs[0] if existing_configs else None

    if existing:
        # Update existing config
        update_payload = config_data.model_dump(exclude_unset=True)
        if update_payload.get("strategy_id") is None:
            update_payload.pop("strategy_id", None)
        logger.info(f"📝 Payload de atualização: {update_payload}")
        logger.info(f"📝 Campos existentes antes: timeframe={existing.timeframe}, amount={existing.amount}")
        reset_consecutive = False
        if "stop1" in update_payload and update_payload["stop1"] != existing.stop1:
            reset_consecutive = True
        if "stop2" in update_payload and update_payload["stop2"] != existing.stop2:
            reset_consecutive = True
        if (
            "no_hibernate_on_consecutive_stop" in update_payload
            and update_payload["no_hibernate_on_consecutive_stop"] != existing.no_hibernate_on_consecutive_stop
        ):
            reset_consecutive = True
        if "is_active" in update_payload and update_payload["is_active"] and not existing.is_active:
            reset_consecutive = True

        for key, value in update_payload.items():
            setattr(existing, key, value)

        logger.info(f"📝 Campos existentes depois: timeframe={existing.timeframe}, amount={existing.amount}")

        if reset_consecutive:
            existing.win_consecutive = 0
            existing.loss_consecutive = 0
            existing.total_wins = 0
            existing.total_losses = 0
            existing.soros_level = 0
            existing.soros_amount = 0.0
            existing.martingale_level = 0
            existing.martingale_amount = 0.0
            existing.highest_balance = None
            existing.initial_balance = None
            # Resetar contadores da Redução Inteligente (incluindo cascata)
            existing.smart_reduction_loss_count = 0
            existing.smart_reduction_win_count = 0
            existing.smart_reduction_cascade_level = 0
            existing.smart_reduction_active = False
            existing.smart_reduction_base_amount = 0.0
            logger.info(
                f"AutoTrade config {existing.id} contadores consecutivos, totais, balances e redução inteligente resetados após atualização"
            )
        if existing.is_active:
            existing.last_activity_timestamp = datetime.utcnow()
        existing.updated_at = datetime.utcnow()

        duplicates = existing_configs[1:] + legacy_configs
        if duplicates:
            for duplicate in duplicates:
                await db.delete(duplicate)
            logger.warning(
                f"⚠️ {len(duplicates) + 1} configs duplicadas para conta {config_data.account_id}. Mantendo {existing.id}."
            )
        await db.commit()
        await db.refresh(existing)
        logger.info(f"AutoTrade config updated for account {config_data.account_id}")

        try:
            from services.data_collector.realtime import data_collector
            if data_collector:
                data_collector.invalidate_autotrade_configs_cache()
                logger.info("✓ Cache de configs invalidado após atualização de autotrade")
        except Exception as e:
            logger.error(f"Erro ao invalidar cache de configs (autotrade): {e}")

        return existing

    # Create new config
    config = AutoTradeConfig(**config_data.model_dump())
    db.add(config)
    await db.commit()
    await db.refresh(config)

    logger.info(f"AutoTrade config created for account {config_data.account_id}")

    try:
        from services.data_collector.realtime import data_collector
        if data_collector:
            data_collector.invalidate_autotrade_configs_cache()
            logger.info("✓ Cache de configs invalidado após criação de autotrade")
    except Exception as e:
        logger.error(f"Erro ao invalidar cache de configs (autotrade): {e}")

    return config


@router.get("", response_model=List[AutoTradeConfigResponse])
async def get_autotrade_configs(
    account_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get auto trade configurations"""
    query = select(AutoTradeConfig).join(Account).where(Account.user_id == current_user.id)
    
    if account_id:
        query = query.where(AutoTradeConfig.account_id == account_id)
    
    if strategy_id:
        query = query.where(AutoTradeConfig.strategy_id == strategy_id)
    
    if is_active is not None:
        query = query.where(AutoTradeConfig.is_active == is_active)
    
    result = await db.execute(query)
    configs = result.scalars().all()
    
    return configs


@router.get("/{config_id}", response_model=AutoTradeConfigResponse)
async def get_autotrade_config(
    config_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get auto trade configuration by ID"""
    result = await db.execute(
        select(AutoTradeConfig).join(Account).where(
            AutoTradeConfig.id == config_id,
            Account.user_id == current_user.id
        )
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AutoTrade config not found"
        )
    
    return config


@router.put("/{config_id}", response_model=AutoTradeConfigResponse)
async def update_autotrade_config(
    config_id: str,
    config_data: AutoTradeConfigUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update auto trade configuration"""
    result = await db.execute(
        select(AutoTradeConfig).join(Account).where(
            AutoTradeConfig.id == config_id,
            Account.user_id == current_user.id
        )
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AutoTrade config not found"
        )
    
    # Update fields
    update_payload = config_data.model_dump(exclude_unset=True)
    if update_payload.get("strategy_id") is None:
        update_payload.pop("strategy_id", None)
    reset_consecutive = False
    if "stop1" in update_payload and update_payload["stop1"] != config.stop1:
        reset_consecutive = True
    if "stop2" in update_payload and update_payload["stop2"] != config.stop2:
        reset_consecutive = True
    if (
        "no_hibernate_on_consecutive_stop" in update_payload
        and update_payload["no_hibernate_on_consecutive_stop"] != config.no_hibernate_on_consecutive_stop
    ):
        reset_consecutive = True
    if "is_active" in update_payload and update_payload["is_active"] and not config.is_active:
        reset_consecutive = True

    for key, value in update_payload.items():
        setattr(config, key, value)

    if reset_consecutive:
        config.win_consecutive = 0
        config.loss_consecutive = 0
        config.total_wins = 0
        config.total_losses = 0
        config.soros_level = 0
        config.soros_amount = 0.0
        config.martingale_level = 0
        config.martingale_amount = 0.0
        config.highest_balance = None
        config.initial_balance = None
        # Resetar contadores da Redução Inteligente (incluindo cascata)
        config.smart_reduction_loss_count = 0
        config.smart_reduction_win_count = 0
        config.smart_reduction_cascade_level = 0
        config.smart_reduction_active = False
        config.smart_reduction_base_amount = 0.0
        logger.info(
            f"AutoTrade config {config_id} contadores consecutivos, totais, balances e redução inteligente resetados após atualização"
        )
    
    if config.is_active:
        config.last_activity_timestamp = datetime.utcnow()
    config.updated_at = datetime.utcnow()

    # Remover duplicatas para a mesma conta/estratégia (inclui configs legadas sem strategy_id)
    if config.strategy_id:
        duplicate_query = select(AutoTradeConfig).where(
            AutoTradeConfig.account_id == config.account_id,
            AutoTradeConfig.id != config.id,
            or_(
                AutoTradeConfig.strategy_id == config.strategy_id,
                AutoTradeConfig.strategy_id == None
            )
        )
    else:
        duplicate_query = select(AutoTradeConfig).where(
            AutoTradeConfig.account_id == config.account_id,
            AutoTradeConfig.strategy_id == None,
            AutoTradeConfig.id != config.id
        )
    duplicates_result = await db.execute(duplicate_query)
    duplicates = duplicates_result.scalars().all()
    if duplicates:
        for duplicate in duplicates:
            await db.delete(duplicate)
        logger.warning(
            f"⚠️ {len(duplicates) + 1} configs duplicadas para conta {config.account_id}. Mantendo {config.id}."
        )
    await db.commit()
    await db.refresh(config)
    
    logger.info(f"AutoTrade config {config_id} updated")

    try:
        from services.data_collector.realtime import data_collector
        if data_collector:
            data_collector.invalidate_autotrade_configs_cache()
            logger.info("✓ Cache de configs invalidado após atualização de autotrade")
    except Exception as e:
        logger.error(f"Erro ao invalidar cache de configs (autotrade): {e}")

    return config


@router.delete("/{config_id}", response_model=MessageResponse)
async def delete_autotrade_config(
    config_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete auto trade configuration"""
    result = await db.execute(
        select(AutoTradeConfig).join(Account).where(
            AutoTradeConfig.id == config_id,
            Account.user_id == current_user.id
        )
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AutoTrade config not found"
        )
    
    await db.delete(config)
    await db.commit()
    
    logger.info(f"AutoTrade config {config_id} deleted")
    return MessageResponse(message="AutoTrade config deleted successfully")
