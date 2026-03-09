"""Trades router"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from core.database import get_db
from core.security import get_current_active_user
from models import User, Trade, Account, Strategy
from schemas import TradeResponse, TradeCreate, TradesListResponse, IndicatorCombinationRanking, IndicatorRankingsResponse

router = APIRouter()


@router.get("", response_model=TradesListResponse)
async def get_trades(
    account_id: str = None,
    strategy_id: str = None,
    status: str = None,
    limit: int = Query(20, ge=1, le=100, description="Número de itens por página (1-100)"),
    offset: int = Query(0, ge=0, description="Número de itens a pular"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all trades for current user"""
    # Build query with eager loading to avoid N+1 queries
    query = (
        select(Trade)
        .options(
            selectinload(Trade.account),
            selectinload(Trade.strategy),
            selectinload(Trade.asset)
        )
        .join(Account)
        .where(Account.user_id == current_user.id)
    )

    if account_id:
        query = query.where(Trade.account_id == account_id)
    
    if strategy_id:
        query = query.where(Trade.strategy_id == strategy_id)
    
    if status:
        query = query.where(Trade.status == status)

    # Get total count
    count_query = query.alias("count")
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(count_query)
    )
    total = count_result.scalar()

    # Apply pagination
    query = query.order_by(Trade.placed_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    trades = result.scalars().all()

    return TradesListResponse(
        trades=[
            TradeResponse(
                id=trade.id,
                user_id=current_user.id,
                account_id=trade.account_id,
                asset_id=str(trade.asset_id),
                symbol=trade.asset.symbol if trade.asset else '',
                strategy_name=trade.strategy.name if trade.strategy else None,
                direction=trade.direction,
                amount=trade.amount,
                duration=trade.duration,
                entry_time=trade.placed_at,
                exit_time=trade.closed_at,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                profit=trade.profit,
                status=trade.status,
                signal_confidence=trade.signal_confidence,
                signal_indicators=trade.signal_indicators,
                created_at=trade.placed_at
            )
            for trade in trades
        ],
        total=total,
        page=1,
        page_size=limit
    )


@router.get("/indicator-rankings", response_model=IndicatorRankingsResponse)
async def get_indicator_rankings(
    limit: int = Query(10, ge=1, le=50, description="Número de combinações a retornar"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get ranking of best indicator combinations based on win rate and profit"""
    try:
        # Buscar todos os trades do usuário com indicadores e profit
        # Query simplificada - buscar trades diretamente
        query = (
            select(Trade)
            .join(Account)
            .where(
                Account.user_id == current_user.id,
                Trade.signal_indicators.isnot(None)
            )
        )

        result = await db.execute(query)
        trades = result.scalars().all()

        # Filtrar trades com profit não nulo
        trades = [t for t in trades if t.profit is not None]

        # Agrupar trades por combinação de indicadores
        combination_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0.0
        })

        for trade in trades:
            indicators = trade.signal_indicators

            # Extrair nomes dos indicadores - lógica mais flexível
            indicator_names = []
            
            if isinstance(indicators, list):
                # Lista de dicts com indicadores
                for ind in indicators:
                    if isinstance(ind, dict):
                        # Tenta pegar 'name' ou 'type' ou qualquer chave que não seja ML
                        name = ind.get('name') or ind.get('type') or ind.get('indicator')
                        if name:
                            indicator_names.append(str(name))
            elif isinstance(indicators, dict):
                # Dicionário com chaves de indicadores
                for key, value in indicators.items():
                    # Ignorar chaves de ML
                    if key not in ['ml_win_probability', 'ml_expected_movement', 'ml_sample_count', 'ml_pattern_id']:
                        # Se o valor for um dict, tenta pegar o nome dele
                        if isinstance(value, dict):
                            name = value.get('name') or value.get('type') or key
                        else:
                            name = key
                        if name:
                            indicator_names.append(str(name))

            if not indicator_names:
                continue

            # Ordenar e criar chave da combinação
            indicator_names.sort()
            combination_key = ', '.join(indicator_names)

            # Atualizar estatísticas
            combination_stats[combination_key]['total_trades'] += 1

            if trade.profit > 0:
                combination_stats[combination_key]['winning_trades'] += 1
            elif trade.profit < 0:
                combination_stats[combination_key]['losing_trades'] += 1

            combination_stats[combination_key]['total_profit'] += trade.profit or 0

        # Criar lista de rankings
        rankings = []
        for combination, stats in combination_stats.items():
            if stats['total_trades'] >= 3:  # Mínimo de 3 trades para exibir (reduzido de 10)
                winning_trades = stats['winning_trades']
                losing_trades = stats['losing_trades']
                total_trades = stats['total_trades']
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                avg_profit = stats['total_profit'] / total_trades if total_trades > 0 else 0

                rankings.append(IndicatorCombinationRanking(
                    combination=combination,
                    total_trades=total_trades,
                    winning_trades=winning_trades,
                    losing_trades=losing_trades,
                    win_rate=win_rate,
                    total_profit=stats['total_profit'],
                    avg_profit=avg_profit
                ))

        # Ordenar por win_rate (descendente) e depois por total_profit
        rankings.sort(key=lambda x: (x.win_rate, x.total_profit), reverse=True)

        return IndicatorRankingsResponse(
            rankings=rankings[:limit],
            total_combinations=len(rankings)
        )
    except Exception as e:
        # Logar erro e retornar lista vazia em vez de falhar
        import logging
        logging.error(f"Erro ao calcular rankings de indicadores: {e}", exc_info=True)
        return IndicatorRankingsResponse(rankings=[], total_combinations=0)


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get trade details"""
    result = await db.execute(
        select(Trade)
        .join(Account)
        .join(User)
        .where(
            Trade.id == trade_id,
            User.id == current_user.id
        )
    )
    trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found"
        )

    return TradeResponse(
        id=trade.id,
        user_id=current_user.id,
        account_id=trade.account_id,
        asset_id=str(trade.asset_id),
        symbol=trade.asset.symbol if trade.asset else '',
        strategy_name=trade.strategy.name if trade.strategy else None,
        direction=trade.direction,
        amount=trade.amount,
        duration=trade.duration,
        entry_time=trade.placed_at,
        exit_time=trade.closed_at,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        profit=trade.profit,
        status=trade.status,
        signal_confidence=trade.signal_confidence,
        signal_indicators=trade.signal_indicators,
        created_at=trade.placed_at
    )


@router.post("", response_model=TradeResponse, status_code=status.HTTP_201_CREATED)
async def create_trade(
    trade_data: TradeCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a manual trade (not recommended for automated trading)"""
    # Verify account ownership
    account_result = await db.execute(
        select(Account).where(
            Account.id == trade_data.asset_id,
            Account.user_id == current_user.id
        )
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    # Import PocketOption client
    from services.pocketoption.client import AsyncPocketOptionClient
    from services.pocketoption.constants import ASSETS
    from services.pocketoption.models import OrderDirection as PODirection

    # Find asset symbol
    symbol = None
    for sym, aid in ASSETS.items():
        if aid == trade_data.asset_id:
            symbol = sym
            break

    if not symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Asset ID {trade_data.asset_id} not found"
        )

    # Create client
    # Usar ssid_demo ou ssid_real baseado em autotrade_demo/autotrade_real
    ssid = None
    is_demo = account.is_demo
    
    if account.autotrade_demo and account.ssid_demo:
        ssid = account.ssid_demo
        is_demo = True
    elif account.autotrade_real and account.ssid_real:
        ssid = account.ssid_real
        is_demo = False
    
    if not ssid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSID não encontrado para esta conta"
        )
    
    client = AsyncPocketOptionClient(
        ssid=ssid,
        is_demo=is_demo,
        persistent_connection=True,
        auto_reconnect=True,
        user_name=account.name
    )

    # Connect
    if not client.is_connected:
        await client.connect()

    # Place order
    direction = PODirection.CALL if trade_data.direction == "call" else PODirection.PUT

    # Execute order
    order_result = await client.place_order(
        asset=symbol,
        amount=trade_data.amount,
        direction=direction,
        duration=trade_data.duration
    )

    # Save trade to database
    trade = Trade(
        account_id=account.id,
        asset_id=trade_data.asset_id,
        strategy_id=None,  # Manual trade
        direction=trade_data.direction,
        amount=trade_data.amount,
        entry_price=order_result.entry_price,
        duration=trade_data.duration,
        status=TradeStatus.ACTIVE,
        placed_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(seconds=trade_data.duration),
        signal_confidence=1.0,  # Manual trade
        signal_indicators={}
    )

    db.add(trade)
    await db.commit()

    return TradeResponse(
        id=trade.id,
        user_id=current_user.id,
        account_id=trade.account_id,
        asset_id=str(trade.asset_id),
        symbol=symbol,
        direction=trade.direction,
        amount=trade.amount,
        duration=trade.duration,
        entry_time=trade.placed_at,
        exit_time=trade.closed_at,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        profit=trade.profit,
        status=trade.status,
        created_at=trade.placed_at
    )
