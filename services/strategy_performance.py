from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
import math

from sqlalchemy import func, select, DateTime
from sqlalchemy.ext.asyncio import AsyncSession

from models import Account, StrategyPerformanceSnapshot, Trade, TradeStatus

PERIOD_DAYS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "1y": 365,
    "all": None,
}

CACHE_TTL_MINUTES = 2


def _resolve_period_days(period: str) -> Optional[int]:
    if period not in PERIOD_DAYS:
        raise ValueError("Invalid period")
    return PERIOD_DAYS[period]


def _calculate_sharpe_ratio(daily_returns: List[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0

    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum((value - mean_return) ** 2 for value in daily_returns) / len(daily_returns)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0

    return mean_return / std_dev


def _calculate_max_drawdown(profits: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for profit in profits:
        equity += profit
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    if peak == 0:
        return 0.0

    return -((max_drawdown / peak) * 100)


def _calculate_monthly_returns(trades: List[Trade], year: int) -> List[float]:
    profits_by_month = [0.0] * 12
    amounts_by_month = [0.0] * 12

    for trade in trades:
        trade_date = trade.closed_at or trade.placed_at
        if not trade_date or trade_date.year != year:
            continue

        month_index = trade_date.month - 1
        profit = float(trade.profit or 0.0)
        amount = float(trade.amount or 0.0)

        profits_by_month[month_index] += profit
        amounts_by_month[month_index] += amount

    returns = []
    for month_index in range(12):
        total_amount = amounts_by_month[month_index]
        if total_amount <= 0:
            returns.append(0.0)
        else:
            returns.append((profits_by_month[month_index] / total_amount) * 100)

    return returns


def _ensure_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Converte datetime aware para naive (UTC)"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


async def _fetch_trades(
    db: AsyncSession,
    user_id: str,
    strategy_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Trade]:
    # Converter datas para naive para evitar problema de timezone
    start_date = _ensure_naive(start_date)
    end_date = _ensure_naive(end_date)
    
    # Usar cast para garantir comparação sem timezone
    trade_date = func.coalesce(
        func.cast(Trade.closed_at, DateTime),
        func.cast(Trade.placed_at, DateTime)
    )
    query = (
        select(Trade)
        .join(Account)
        .where(
            Account.user_id == user_id,
            Trade.strategy_id == strategy_id,
            Trade.status.in_([TradeStatus.WIN, TradeStatus.LOSS]),
            trade_date >= start_date,
            trade_date <= end_date,
        )
    )

    result = await db.execute(query)
    return result.scalars().all()


async def get_strategy_performance_snapshot(
    db: AsyncSession,
    user_id: str,
    strategy_id: str,
    period: str,
    cache_ttl_minutes: int = CACHE_TTL_MINUTES,
) -> StrategyPerformanceSnapshot:
    period_days = _resolve_period_days(period)
    now = datetime.utcnow().replace(tzinfo=None)  # Garantir naive
    start_date = now - timedelta(days=period_days) if period_days else datetime(1970, 1, 1)

    snapshot_result = await db.execute(
        select(StrategyPerformanceSnapshot).where(
            StrategyPerformanceSnapshot.user_id == user_id,
            StrategyPerformanceSnapshot.strategy_id == strategy_id,
            StrategyPerformanceSnapshot.period == period,
        )
    )
    snapshot = snapshot_result.scalar_one_or_none()

    if snapshot and snapshot.calculated_at is not None:
        age_seconds = (now - snapshot.calculated_at).total_seconds()
        if age_seconds <= cache_ttl_minutes * 60:
            return snapshot

    trades = await _fetch_trades(db, user_id, strategy_id, start_date, now)
    trades_sorted = sorted(trades, key=lambda trade: trade.closed_at or trade.placed_at or now)
    profits = [float(trade.profit or 0.0) for trade in trades_sorted]

    total_trades = len(trades_sorted)
    winning_trades = sum(1 for trade in trades_sorted if trade.status == TradeStatus.WIN)
    losing_trades = sum(1 for trade in trades_sorted if trade.status == TradeStatus.LOSS)
    total_profit = sum(profit for profit in profits if profit > 0)
    total_loss = sum(abs(profit) for profit in profits if profit < 0)
    net_profit = total_profit - total_loss
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 0.0

    avg_win = (total_profit / winning_trades) if winning_trades > 0 else 0.0
    avg_loss = -(total_loss / losing_trades) if losing_trades > 0 else 0.0
    
    # Calculate largest win and loss safely
    winning_profits = [profit for profit in profits if profit > 0]
    largest_win = max(winning_profits) if winning_profits else 0.0
    
    losing_profits = [profit for profit in profits if profit < 0]
    largest_loss = min(losing_profits) if losing_profits else 0.0

    max_drawdown = _calculate_max_drawdown(profits)

    daily_returns = {}
    for trade in trades_sorted:
        trade_date = (trade.closed_at or trade.placed_at or now).date()
        daily_returns.setdefault(trade_date, 0.0)
        daily_returns[trade_date] += float(trade.profit or 0.0)

    sharpe_ratio = _calculate_sharpe_ratio(list(daily_returns.values()))

    consecutive_wins = 0
    consecutive_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    for trade in trades_sorted:
        if trade.status == TradeStatus.WIN:
            consecutive_wins += 1
            consecutive_losses = 0
        elif trade.status == TradeStatus.LOSS:
            consecutive_losses += 1
            consecutive_wins = 0

        max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

    monthly_returns = _calculate_monthly_returns(trades_sorted, now.year)

    if snapshot is None:
        snapshot = StrategyPerformanceSnapshot(
            user_id=user_id,
            strategy_id=strategy_id,
            period=period,
        )
        db.add(snapshot)

    snapshot.start_date = start_date
    snapshot.end_date = now
    snapshot.total_trades = total_trades
    snapshot.winning_trades = winning_trades
    snapshot.losing_trades = losing_trades
    snapshot.win_rate = win_rate
    snapshot.total_profit = total_profit
    snapshot.total_loss = total_loss
    snapshot.net_profit = net_profit
    snapshot.profit_factor = profit_factor
    snapshot.max_drawdown = max_drawdown
    snapshot.sharpe_ratio = sharpe_ratio
    snapshot.avg_win = avg_win
    snapshot.avg_loss = avg_loss
    snapshot.largest_win = largest_win
    snapshot.largest_loss = largest_loss
    snapshot.consecutive_wins = max_consecutive_wins
    snapshot.consecutive_losses = max_consecutive_losses
    snapshot.monthly_returns = monthly_returns
    snapshot.calculated_at = now

    await db.commit()
    await db.refresh(snapshot)

    return snapshot
