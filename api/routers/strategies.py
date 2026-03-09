"""API router for strategies management"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
from loguru import logger

# Função helper para garantir datetime sem timezone (offset-naive)
def naive_utcnow():
    """Retorna datetime.utcnow() garantindo que seja offset-naive"""
    dt = datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt

from core.database import get_db
from core.security import get_current_active_user
from models import User, Strategy, Signal, Indicator, strategy_indicators
from services.strategy_performance import get_strategy_performance_snapshot
from api.decorators import cache_response
from schemas import (
    StrategyResponse,
    StrategyCreate,
    StrategyUpdate,
    StrategyWithPerformance,
    StrategyPerformance,
    StrategyPerformanceSnapshotResponse
)

router = APIRouter()


async def _get_strategy_indicators_with_params(
    db: AsyncSession,
    strategy_id: str
) -> List[dict]:
    """Fetch indicators linked to a strategy with their saved parameters."""
    result = await db.execute(
        select(Indicator, strategy_indicators.c.parameters)
        .join(strategy_indicators, Indicator.id == strategy_indicators.c.indicator_id)
        .where(strategy_indicators.c.strategy_id == strategy_id)
    )

    indicators = []
    for indicator_obj, params in result.all():
        indicators.append({
            'id': indicator_obj.id,
            'name': indicator_obj.name,
            'type': indicator_obj.type,
            'description': indicator_obj.description,
            'parameters': params if params is not None else (indicator_obj.parameters or {})
        })

    return indicators


async def _build_strategy_response(strategy: Strategy, db: AsyncSession) -> StrategyResponse:
    """Build StrategyResponse including indicators with saved params."""
    indicators = await _get_strategy_indicators_with_params(db, strategy.id)
    return StrategyResponse(
        id=strategy.id,
        user_id=strategy.user_id,
        account_id=strategy.account_id,
        name=strategy.name,
        description=strategy.description,
        type=strategy.type,
        parameters=strategy.parameters,
        assets=strategy.assets,
        indicators=indicators,
        is_active=strategy.is_active,
        total_trades=strategy.total_trades,
        winning_trades=strategy.winning_trades,
        losing_trades=strategy.losing_trades,
        total_profit=strategy.total_profit,
        total_loss=strategy.total_loss,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        last_executed=strategy.last_executed
    )


@router.get("", response_model=List[StrategyResponse])
async def get_strategies(
    user_id: Optional[str] = None,  # Permitir admin filtrar por usuário específico
    active: bool = None,
    strategy_type: str = None,
    limit: int = 100,  # Paginação padrão
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all strategies for current user with pagination. Admin can filter by user_id."""
    from models import AutoTradeConfig

    # Determinar qual user_id usar
    target_user_id = current_user.id
    if user_id and current_user.is_superuser:
        # Admin pode ver estratégias de qualquer usuário
        target_user_id = user_id
        logger.info(f"[ADMIN] Superusuário {current_user.email} buscando estratégias do usuário {user_id}")

    # Query otimizada com join para evitar N+1
    query = (
        select(Strategy, AutoTradeConfig.is_active.label('autotrade_active'))
        .outerjoin(AutoTradeConfig, Strategy.id == AutoTradeConfig.strategy_id)
        .options(selectinload(Strategy.indicators))
        .where(Strategy.user_id == target_user_id)
    )

    if active is not None:
        query = query.where(Strategy.is_active == active)

    if strategy_type:
        query = query.where(Strategy.type == strategy_type)
    
    # Adicionar paginação
    query = query.limit(limit).offset(offset)
    
    # Ordernar por mais recente
    query = query.order_by(Strategy.created_at.desc())

    result = await db.execute(query)
    rows = result.all()

    responses = []
    for row in rows:
        strategy = row.Strategy
        autotrade_active = row.autotrade_active
        
        # Usar autotrade_config.is_active se existir, senão strategy.is_active
        actual_is_active = autotrade_active if autotrade_active is not None else strategy.is_active

        responses.append(
            StrategyResponse(
                id=strategy.id,
                user_id=strategy.user_id,
                account_id=strategy.account_id,
                name=strategy.name,
                description=strategy.description,
                type=strategy.type,
                parameters=strategy.parameters,
                assets=strategy.assets,
                indicators=[{
                    'id': ind.id,
                    'name': ind.name,
                    'type': ind.type
                } for ind in strategy.indicators] if strategy.indicators else [],
                is_active=actual_is_active,
                total_trades=strategy.total_trades,
                winning_trades=strategy.winning_trades,
                losing_trades=strategy.losing_trades,
                total_profit=strategy.total_profit,
                total_loss=strategy.total_loss,
                created_at=strategy.created_at,
                updated_at=strategy.updated_at,
                last_executed=strategy.last_executed
            )
        )

    return responses


@router.get("/performance", response_model=List[StrategyPerformanceSnapshotResponse])
@cache_response(ttl=300, key_prefix="strategies:performance")  # Cache aumentado para 5 min
async def get_strategy_performance(
    strategy_id: Optional[str] = None,
    period: str = "30d",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get cached strategy performance metrics"""
    query = select(Strategy).where(Strategy.user_id == current_user.id)

    if strategy_id:
        query = query.where(Strategy.id == strategy_id)

    result = await db.execute(query)
    strategies = result.scalars().all()

    if strategy_id and not strategies:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    responses: List[StrategyPerformanceSnapshotResponse] = []
    for strategy in strategies:
        try:
            snapshot = await get_strategy_performance_snapshot(
                db=db,
                user_id=current_user.id,
                strategy_id=strategy.id,
                period=period
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid period"
            )

        monthly_returns = snapshot.monthly_returns or []
        if len(monthly_returns) < 12:
            monthly_returns = monthly_returns + [0.0] * (12 - len(monthly_returns))

        performance = StrategyPerformance(
            total_trades=snapshot.total_trades,
            winning_trades=snapshot.winning_trades,
            losing_trades=snapshot.losing_trades,
            win_rate=snapshot.win_rate,
            total_profit=snapshot.total_profit,
            total_loss=snapshot.total_loss,
            net_profit=snapshot.net_profit,
            profit_factor=snapshot.profit_factor,
            max_drawdown=snapshot.max_drawdown,
            sharpe_ratio=snapshot.sharpe_ratio,
            avg_win=snapshot.avg_win,
            avg_loss=snapshot.avg_loss,
            largest_win=snapshot.largest_win,
            largest_loss=snapshot.largest_loss,
            consecutive_wins=snapshot.consecutive_wins,
            consecutive_losses=snapshot.consecutive_losses,
            monthly_returns=monthly_returns
        )

        responses.append(
            StrategyPerformanceSnapshotResponse(
                strategy_id=strategy.id,
                strategy_name=strategy.name,
                performance=performance,
                snapshot_date=snapshot.end_date
            )
        )

    return responses


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    strategy_data: StrategyCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new strategy"""
    strategy = Strategy(
        user_id=current_user.id,
        account_id=strategy_data.account_id,
        name=strategy_data.name,
        description=strategy_data.description,
        type=strategy_data.type,
        parameters=strategy_data.parameters,
        assets=strategy_data.assets,
        is_active=False  # Estratégias criadas devem vir desligadas por padrão
    )

    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)

    # Associar indicadores à estratégia
    if strategy_data.indicators:
        for indicator_data in strategy_data.indicators:
            # Buscar indicador por ID
            result = await db.execute(
                select(Indicator).where(Indicator.id == indicator_data['id'])
            )
            indicator = result.scalar_one_or_none()
            
            if indicator:
                # Inserir na tabela de associação
                await db.execute(
                    strategy_indicators.insert().values(
                        strategy_id=strategy.id,
                        indicator_id=indicator.id,
                        parameters=indicator_data.get('parameters', {})
                    )
                )
        
        await db.commit()

    # Criar AutoTradeConfig padrão para a estratégia
    from models import AutoTradeConfig
    from datetime import datetime
    
    autotrade_config = AutoTradeConfig(
        account_id=strategy.account_id,
        strategy_id=strategy.id,
        amount=1.0,
        stop1=3,
        stop2=5,
        soros=0,
        martingale=0,
        timeframe=5,
        min_confidence=0.7,
        is_active=False,
        last_activity_timestamp=naive_utcnow(),
        created_at=naive_utcnow(),
        updated_at=naive_utcnow()
    )
    db.add(autotrade_config)
    await db.commit()
    await db.refresh(autotrade_config)
    
    logger.info(f"AutoTrade config criado para estratégia {strategy.id}")

    return StrategyResponse(
        id=strategy.id,
        user_id=strategy.user_id,
        account_id=strategy.account_id,
        name=strategy.name,
        type=strategy.type,
        parameters=strategy.parameters,
        assets=strategy.assets,
        is_active=strategy.is_active,
        total_trades=strategy.total_trades,
        winning_trades=strategy.winning_trades,
        losing_trades=strategy.losing_trades,
        total_profit=strategy.total_profit,
        total_loss=strategy.total_loss,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        last_executed=strategy.last_executed
    )


@router.get("/{strategy_id}", response_model=StrategyWithPerformance)
async def get_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get strategy details with performance. Admin can view any strategy."""
    # Construir query base
    query = select(Strategy).options(selectinload(Strategy.indicators)).where(
        Strategy.id == strategy_id
    )
    
    # Se não for superusuário, filtrar apenas estratégias do próprio usuário
    if not current_user.is_superuser:
        query = query.where(Strategy.user_id == current_user.id)
    
    result = await db.execute(query)
    strategy = result.scalar_one_or_none()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    # Calculate performance metrics
    total_trades = strategy.total_trades
    win_rate = (strategy.winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    net_profit = strategy.total_profit - strategy.total_loss
    profit_factor = (strategy.total_profit / strategy.total_loss) if strategy.total_loss > 0 else (float('inf') if strategy.total_profit > 0 else 0.0)

    performance = StrategyPerformance(
        total_trades=total_trades,
        winning_trades=strategy.winning_trades,
        losing_trades=strategy.losing_trades,
        win_rate=win_rate,
        total_profit=strategy.total_profit,
        total_loss=strategy.total_loss,
        net_profit=net_profit,
        profit_factor=profit_factor
    )

    indicators_list = await _get_strategy_indicators_with_params(db, strategy.id)
    
    return StrategyWithPerformance(
        id=strategy.id,
        user_id=strategy.user_id,
        account_id=strategy.account_id,
        name=strategy.name,
        description=strategy.description,
        type=strategy.type,
        parameters=strategy.parameters,
        assets=strategy.assets,
        indicators=indicators_list,
        is_active=strategy.is_active,
        total_trades=strategy.total_trades,
        winning_trades=strategy.winning_trades,
        losing_trades=strategy.losing_trades,
        total_profit=strategy.total_profit,
        total_loss=strategy.total_loss,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        last_executed=strategy.last_executed,
        performance=performance
    )


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: str,
    strategy_update: StrategyUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update strategy. Admin can edit any strategy."""
    # Construir query base
    query = select(Strategy).where(Strategy.id == strategy_id)
    
    # Se não for superusuário, filtrar apenas estratégias do próprio usuário
    if not current_user.is_superuser:
        query = query.where(Strategy.user_id == current_user.id)
    
    result = await db.execute(query)
    strategy = result.scalar_one_or_none()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    if strategy_update.name is not None:
        strategy.name = strategy_update.name
    
    if strategy_update.description is not None:
        strategy.description = strategy_update.description

    if strategy_update.is_active is not None:
        strategy.is_active = strategy_update.is_active
        
        # Atualizar também o autotrade_config vinculado à estratégia
        from models import AutoTradeConfig, Account
        autotrade_config_result = await db.execute(
            select(AutoTradeConfig).where(AutoTradeConfig.strategy_id == strategy_id)
        )
        autotrade_config = autotrade_config_result.scalar_one_or_none()
        
        if autotrade_config:
            account_result = await db.execute(
                select(Account).where(Account.id == autotrade_config.account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Account not found"
                )

            if strategy_update.is_active:
                connection_type = None
                ssid = None

                # Verificar se há SSID cadastrado (mesmo que o modo não esteja ativo)
                # Priorizar demo, depois real
                if account.ssid_demo:
                    connection_type = 'demo'
                    ssid = account.ssid_demo
                    # Extrair apenas o session ID do SSID completo se necessário
                    if ssid and ssid.startswith('42['):
                        try:
                            import json
                            json_start = ssid.find("{")
                            json_end = ssid.rfind("}") + 1
                            if json_start != -1 and json_end > json_start:
                                json_part = ssid[json_start:json_end]
                                data = json.loads(json_part)
                                ssid = data.get("session", ssid)
                        except:
                            pass
                    # Reativar modo demo se não estiver ativo
                    if not account.autotrade_demo:
                        account.autotrade_demo = True
                        logger.info(f"Modo demo reativado automaticamente para conta {account.id}")
                elif account.ssid_real:
                    connection_type = 'real'
                    ssid = account.ssid_real
                    # Extrair apenas o session ID do SSID completo se necessário
                    if ssid and ssid.startswith('42['):
                        try:
                            import json
                            json_start = ssid.find("{")
                            json_end = ssid.rfind("}") + 1
                            if json_start != -1 and json_end > json_start:
                                json_part = ssid[json_start:json_end]
                                data = json.loads(json_part)
                                ssid = data.get("session", ssid)
                        except:
                            pass
                    # Reativar modo real se não estiver ativo
                    if not account.autotrade_real:
                        account.autotrade_real = True
                        logger.info(f"Modo real reativado automaticamente para conta {account.id}")
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Nenhum SSID cadastrado. Configure o SSID demo ou real antes de ligar a estratégia."
                    )
                
                if not ssid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"SSID {connection_type} não cadastrado para esta conta"
                    )

                from services.data_collector.realtime import data_collector
                if data_collector:
                    connected = await data_collector.connection_manager.ensure_connection(
                        account.id,
                        connection_type,
                        ssid
                    )
                    if not connected:
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Não foi possível conectar ao WebSocket"
                        )
                else:
                    logger.warning("DataCollector não disponível para conectar websocket")

            # Enviar notificação se autotrade foi reabilitado ou desativado
            if strategy_update.is_active != autotrade_config.is_active:
                try:
                    from services.notifications.telegram import telegram_service

                    # Buscar chat_id do usuário (usando contexto assíncrono existente)
                    result = await db.execute(
                        select(Account).join(User, Account.user_id == User.id).where(Account.id == autotrade_config.account_id)
                    )
                    account_with_user = result.scalar_one_or_none()
                    if account_with_user and account_with_user.user:
                        user_chat_id = account_with_user.user.telegram_chat_id
                        if user_chat_id:
                            # Determinar tipo de conta (demo/real)
                            account_type = None
                            if account_with_user.autotrade_demo:
                                account_type = 'demo'
                            elif account_with_user.autotrade_real:
                                account_type = 'real'
                            
                            if strategy_update.is_active:
                                # Autotrade foi reabilitado - resetar contadores consecutivos e totais
                                autotrade_config.win_consecutive = 0
                                autotrade_config.loss_consecutive = 0
                                autotrade_config.total_wins = 0
                                autotrade_config.total_losses = 0
                                autotrade_config.soros_level = 0
                                autotrade_config.soros_amount = 0.0
                                autotrade_config.martingale_level = 0
                                autotrade_config.martingale_amount = 0.0
                                autotrade_config.highest_balance = None
                                autotrade_config.initial_balance = None
                                logger.info(f"✓ Contadores consecutivos, totais e balances resetados ao reativar autotrade na estratégia {strategy_id}")
                                
                                await telegram_service.send_message(
                                    f"""
🔄 <b>AUTOTRADE REABILITADO!</b>

📊 Estratégia: {strategy.name}
👤 Conta: {account_with_user.name}
🏷️ Tipo: {account_type.upper() if account_type else 'N/A'}
⚡ Autotrade foi reativado

⏰ {(datetime.utcnow() - timedelta(hours=3)).strftime('%H:%M:%S')}
""",
                                    chat_id=user_chat_id
                                )
                            else:
                                # Autotrade foi desativado
                                await telegram_service.send_message(
                                    f"""
⏸️ <b>AUTOTRADE DESATIVADO!</b>

📊 Estratégia: {strategy.name}
👤 Conta: {account_with_user.name}
🏷️ Tipo: {account_type.upper() if account_type else 'N/A'}
🛑 Autotrade foi desativado

⏰ {(datetime.utcnow() - timedelta(hours=3)).strftime('%H:%M:%S')}
""",
                                    chat_id=user_chat_id
                                )
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação de autotrade: {e}")
            
            autotrade_config.is_active = strategy_update.is_active
            autotrade_config.updated_at = naive_utcnow()
            # Atualizar last_activity_timestamp quando estratégia é ativada
            if strategy_update.is_active:
                autotrade_config.last_activity_timestamp = naive_utcnow()
            logger.info(f"AutoTrade config is_active atualizado para {strategy_update.is_active} na estratégia {strategy_id}")
            
            await db.commit()
            autotrade_config.updated_at = naive_utcnow()
            logger.info(f"AutoTrade config is_active atualizado para {strategy_update.is_active} na estratégia {strategy_id}")
            
            # Invalidar cache de configs no data_collector
            from services.data_collector.realtime import data_collector
            if data_collector:
                await data_collector.invalidate_autotrade_configs_cache()
                logger.info(f"✓ Cache de configs invalidado após alteração de is_active")
    
    if strategy_update.parameters is not None:
        strategy.parameters = strategy_update.parameters
    
    if strategy_update.assets is not None:
        strategy.assets = strategy_update.assets
    
    # Atualizar indicadores se fornecidos
    if strategy_update.indicators is not None:
        # Deletar indicadores existentes
        await db.execute(
            delete(strategy_indicators).where(strategy_indicators.c.strategy_id == strategy_id)
        )
        
        # Adicionar novos indicadores
        for indicator_data in strategy_update.indicators:
            result = await db.execute(
                select(Indicator).where(Indicator.id == indicator_data['id'])
            )
            indicator = result.scalar_one_or_none()
            
            if indicator:
                await db.execute(
                    strategy_indicators.insert().values(
                        strategy_id=strategy_id,
                        indicator_id=indicator.id,
                        parameters=indicator_data.get('parameters', {})
                    )
                )

    strategy.updated_at = naive_utcnow()
    
    await db.commit()
    await db.refresh(strategy)

    if strategy_update.parameters is not None or strategy_update.indicators is not None:
        # Invalidar cache de configs no data_collector
        from services.data_collector.realtime import data_collector
        if data_collector:
            await data_collector.invalidate_autotrade_configs_cache()
            logger.info("✓ Cache de configs invalidado após alteração de parâmetros/indicadores")

    return await _build_strategy_response(strategy, db)


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete strategy - Admin can delete any strategy, users only their own"""
    # Construir query base
    query = select(Strategy).where(Strategy.id == strategy_id)
    
    # Se não for superusuário, filtrar apenas estratégias do próprio usuário
    if not current_user.is_superuser:
        query = query.where(Strategy.user_id == current_user.id)
    
    result = await db.execute(query)
    strategy = result.scalar_one_or_none()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    # Otimização: DELETE em batch em vez de loop um por um
    from sqlalchemy import delete
    from models import AutoTradeConfig, Trade, strategy_indicators
    
    # Delete autotrade configs em batch
    await db.execute(
        delete(AutoTradeConfig).where(AutoTradeConfig.strategy_id == strategy_id)
    )

    # Delete trades em batch
    await db.execute(
        delete(Trade).where(Trade.strategy_id == strategy_id)
    )

    # Delete strategy indicators (association table) em batch
    await db.execute(
        delete(strategy_indicators).where(strategy_indicators.c.strategy_id == strategy_id)
    )

    # Now delete the strategy
    await db.delete(strategy)
    await db.commit()

    # Invalidar cache de configs no data_collector
    from services.data_collector.realtime import data_collector
    if data_collector:
        data_collector._autotrade_configs = None
        data_collector._configs_cache_last_updated = 0
        data_collector._configured_timeframes = None
        data_collector._configured_timeframe = None
        data_collector._config_last_updated = 0
        logger.info("✓ Cache de configs invalidado após exclusão de estratégia")


