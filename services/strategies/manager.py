"""Strategy manager for managing and executing trading strategies"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
from loguru import logger

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from models import Strategy, Signal, Account, Asset, Trade, TradeStatus, TradeDirection, Indicator, strategy_indicators
from core.database import get_db_context
from services.strategies.base import BaseStrategy
from services.strategies.custom_strategy import CustomStrategy
from services.data_collector.local_storage import local_storage
from services.utils.retry import retry_on_exception, CONNECTION_RETRY_CONFIG, RetryableError


class StrategyManager:
    """Manager for trading strategies - uses only CustomStrategy with indicators"""

    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.is_running = False

    async def load_strategies(self):
        """Load all active strategies from database"""
        logger.info("Loading strategies from database...")

        async with get_db_context() as db:
            result = await db.execute(
                select(Strategy).where(Strategy.is_active == True)
            )
            strategies = result.scalars().all()

            for strategy in strategies:
                await self._load_strategy(strategy)

        logger.info(f"Loaded {len(self.strategies)} strategies")

    async def _load_strategy(self, strategy: Strategy):
        """Load a single strategy - uses CustomStrategy with indicators"""
        try:
            # Usar CustomStrategy com indicadores
            indicator_configs = []
            async with get_db_context() as db:
                    indicators_result = await db.execute(
                        select(Indicator, strategy_indicators.c.parameters)
                        .join(strategy_indicators, Indicator.id == strategy_indicators.c.indicator_id)
                        .where(strategy_indicators.c.strategy_id == strategy.id)
                    )
                    indicator_configs = [
                        {
                            "id": indicator_obj.id,
                            "name": indicator_obj.name,
                            "type": indicator_obj.type,
                            "parameters": params if params is not None else (indicator_obj.parameters or {})
                        }
                        for indicator_obj, params in indicators_result.all()
                    ]

                if not indicator_configs and strategy.indicators:
                    indicator_configs = [
                        {
                            "id": indicator.id,
                            "name": indicator.name,
                            "type": indicator.type,
                            "parameters": indicator.parameters or {}
                        }
                        for indicator in strategy.indicators
                    ]

                # All strategies now use CustomStrategy with indicators
                instance = CustomStrategy(
                    name=strategy.name,
                    strategy_type="custom",
                    account_id=strategy.account_id,
                    parameters=strategy.parameters,
                    assets=strategy.assets,
                    indicators=indicator_configs
                )
                logger.info(f"Loaded strategy: {strategy.name} (Custom with {len(indicator_configs or [])} indicators)")

            self.strategies[strategy.id] = instance

        except ImportError as e:
            logger.error(f"Failed to import strategy module for {strategy.name}: {e}", exc_info=True)
        except AttributeError as e:
            logger.error(f"Strategy class not found for {strategy.name}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to load strategy {strategy.name}: {e}", exc_info=True)

    async def start(self):
        """Start strategy execution"""
        logger.info("Starting strategy manager...")
        self.is_running = True
        await self.load_strategies()

    async def stop(self):
        """Stop strategy execution"""
        logger.info("Stopping strategy manager...")
        self.is_running = False

    async def execute_strategies(self):
        """Execute all active strategies"""
        if not self.is_running:
            return

        for strategy_id, strategy in self.strategies.items():
            if not strategy.is_active:
                continue

            try:
                await self._execute_strategy(strategy_id, strategy)
            except ConnectionError as e:
                logger.error(f"Connection error executing strategy {strategy.name}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error executing strategy {strategy.name}: {e}", exc_info=True)

    async def _execute_strategy(self, strategy_id: str, strategy: BaseStrategy):
        """Execute a single strategy"""
        # Get candles for each asset
        for asset_symbol in strategy.assets:
            try:
                # Get timeframe from parameters
                timeframe = strategy.parameters.get("timeframe", 60)
                
                # Carregar candles do armazenamento local
                candles_data = await local_storage.load_candles_from_file(
                    asset_symbol, 
                    timeframe, 
                    limit=100
                )
                
                if not candles_data:
                    logger.debug(f"No candles found for {asset_symbol} timeframe={timeframe}")
                    continue
                
                # Converter dicionários para objetos Candle
                from services.strategies.base import Candle as StrategyCandle
                candles = [
                    StrategyCandle(
                        timestamp=datetime.fromtimestamp(c["timestamp"]),
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c.get("volume", 0)
                    )
                    for c in candles_data
                ]
                
                # Use min_confidence period if available
                min_period = strategy.parameters.get("min_candles", 20)
                if len(candles) < min_period:
                    continue

                # Analyze and generate signal
                signal = await strategy.analyze(candles)

                if signal:
                    # Check if signal meets confidence threshold
                    min_confidence = strategy.parameters.get("min_confidence", 0.7)
                    
                    if signal.confidence >= min_confidence:
                        # Só salva sinal que vai executar trade
                        signal.strategy_id = strategy_id
                        signal.timeframe = timeframe
                        
                        # Get asset ID from database
                        async with get_db_context() as db:
                            asset_result = await db.execute(
                                select(Asset).where(Asset.symbol == asset_symbol)
                            )
                            asset = asset_result.scalar_one_or_none()
                            if asset:
                                signal.asset_id = asset.id
                        
                        # Save signal and execute trade em sessões separadas
                        await self._save_signal(signal)
                        # Execute trade
                        await self._execute_trade(strategy, signal)

            except ValueError as e:
                logger.error(f"Error analyzing {asset_symbol}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error executing strategy for {asset_symbol}: {e}", exc_info=True)

    async def _save_signal(self, signal: Signal):
        """Save signal to database"""
        try:
            async with get_db_context() as db:
                db.add(signal)
                await db.commit()
                logger.debug(f"Signal saved: {signal.signal_type} for asset {signal.asset_id}")
        except Exception as e:
            logger.error(f"Failed to save signal: {e}", exc_info=True)

    @retry_on_exception(CONNECTION_RETRY_CONFIG, exceptions=(ConnectionError, RetryableError))
    async def _execute_trade(self, strategy: BaseStrategy, signal: Signal):
        """Execute trade based on signal"""
        try:
            # Get account em sessão separada
            async with get_db_context() as db:
                account_result = await db.execute(
                    select(Account).where(Account.id == strategy.account_id)
                )
                account = account_result.scalar_one_or_none()

            if not account:
                logger.warning(f"Account not found: {strategy.account_id}")
                return

            # Import PocketOption client
            from services.pocketoption.client import AsyncPocketOptionClient
            from services.pocketoption.constants import ASSETS

            # Find asset symbol
            symbol = None
            for sym, aid in ASSETS.items():
                if aid == signal.asset_id:
                    symbol = sym
                    break

            if not symbol:
                logger.warning(f"Asset symbol not found for ID: {signal.asset_id}")
                return

            # Create client
            # Usar ssid_demo ou ssid_real baseado em autotrade_demo/autotrade_real
            ssid = None
            is_demo = None
            
            if account.autotrade_demo and account.ssid_demo:
                ssid = account.ssid_demo
                is_demo = True
            elif account.autotrade_real and account.ssid_real:
                ssid = account.ssid_real
                is_demo = False
            
            if not ssid:
                logger.warning(f"SSID não encontrado para conta {account.name}")
                return
            
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
            from services.pocketoption.models import OrderDirection as PODirection

            direction = PODirection.CALL if signal.signal_type == SignalType.BUY else PODirection.PUT

            # Execute order
            order_result = await client.place_order(
                asset=symbol,
                amount=strategy.amount,
                direction=direction,
                duration=strategy.duration
            )

            # Save trade to database em sessão separada
            async with get_db_context() as db:
                trade = Trade(
                    account_id=account.id,
                    asset_id=signal.asset_id,
                    strategy_id=strategy.id if hasattr(strategy, 'id') else signal.strategy_id,
                    direction=TradeDirection.CALL if signal.signal_type == SignalType.BUY else TradeDirection.PUT,
                    amount=strategy.amount,
                    entry_price=order_result.entry_price,
                    duration=strategy.duration,
                    status=TradeStatus.ACTIVE,
                    placed_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(seconds=strategy.duration),
                    signal_confidence=signal.confidence,
                    signal_indicators=signal.indicators
                )

                db.add(trade)
                await db.commit()

                if getattr(signal, "id", None):
                    executed_at = trade.placed_at or datetime.utcnow()
                    signal.is_executed = True
                    signal.trade_id = trade.id
                    signal.executed_at = executed_at
                    await db.execute(
                        update(Signal)
                        .where(Signal.id == signal.id)
                        .values(
                            is_executed=True,
                            trade_id=trade.id,
                            executed_at=executed_at
                        )
                    )
                    await db.commit()
                    logger.info(f"Sinal atualizado como executado: {signal.id}")
                
                # Registrar sinal como executado no performance monitor
                try:
                    from services.performance_monitor import performance_monitor
                    performance_monitor.record_signal(executed=True)
                except Exception:
                    pass

            logger.info(f"Trade executed: {symbol} {signal.signal_type} ${strategy.amount}")

        except ConnectionError as e:
            logger.error(f"Connection error executing trade: {e}", exc_info=True)
        except ValueError as e:
            logger.error(f"Validation error executing trade: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to execute trade: {e}", exc_info=True)

    async def get_strategy_performance(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Get performance metrics for a strategy"""
        async with get_db_context() as db:
            # Get strategy
            strategy_result = await db.execute(
                select(Strategy).where(Strategy.id == strategy_id)
            )
            strategy = strategy_result.scalar_one_or_none()

            if not strategy:
                return None

            # Get trades
            trades_result = await db.execute(
                select(Trade).where(Trade.strategy_id == strategy_id)
            )
            trades = trades_result.scalars().all()

            # Calculate metrics
            total_trades = len(trades)
            winning_trades = sum(1 for t in trades if t.status == TradeStatus.WIN)
            losing_trades = sum(1 for t in trades if t.status == TradeStatus.LOSS)
            total_profit = sum(t.profit or 0 for t in trades if t.profit and t.profit > 0)
            total_loss = sum(abs(t.profit) for t in trades if t.profit and t.profit < 0)

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            return {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": win_rate,
                "total_profit": total_profit,
                "total_loss": total_loss,
                "net_profit": total_profit - total_loss
            }

    async def backtest_strategy(
        self,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Backtest a strategy using local storage data"""
        async with get_db_context() as db:
            # Get strategy
            strategy_result = await db.execute(
                select(Strategy).where(Strategy.id == strategy_id)
            )
            strategy = strategy_result.scalar_one_or_none()

            if not strategy:
                raise ValueError(f"Strategy not found: {strategy_id}")

            # Get candles from local storage for all assets
            all_candles = []
            for asset_symbol in strategy.assets:
                candles_data = await local_storage.load_candles_from_file(
                    asset_symbol,
                    strategy.parameters.get("timeframe", 60),
                    limit=10000  # Get more candles for backtest
                )
                
                # Filter by date range
                start_timestamp = start_date.timestamp()
                end_timestamp = end_date.timestamp()
                
                filtered_candles = [
                    c for c in candles_data
                    if start_timestamp <= c["timestamp"] <= end_timestamp
                ]
                
                all_candles.extend(filtered_candles)

            if not all_candles:
                raise ValueError("No candles found for backtest period")

            # Convert to Candle objects
            from services.strategies.base import Candle as StrategyCandle
            candles = [
                StrategyCandle(
                    timestamp=datetime.fromtimestamp(c["timestamp"]),
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c.get("volume", 0)
                )
                for c in all_candles
            ]

            # Create strategy instance
            # Use CustomStrategy for all strategies
            instance = CustomStrategy(
                name=strategy.name,
                strategy_type="custom",
                account_id=strategy.account_id,
                parameters=strategy.parameters,
                assets=strategy.assets,
                indicators=strategy.indicators if hasattr(strategy, 'indicators') else []
            )

            # Run backtest
            results = await instance.backtest(list(candles))

            return {
                "strategy_id": strategy_id,
                "start_date": start_date,
                "end_date": end_date,
                "results": results
            }


