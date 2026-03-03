"""Execução de trades no fechamento da vela"""
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


async def execute_trade_on_candle_close(
    pending_trade,
    trade_executor,
    realtime_collector
) -> Optional[Any]:
    """
    Executar trade agendado no fechamento da vela.
    
    Args:
        pending_trade: Trade pendente do TradeTimingManager
        trade_executor: Instância do TradeExecutor
        realtime_collector: Instância do RealtimeDataCollector
        
    Returns:
        Trade executado ou None se falhar
    """
    try:
        current_time = time.time()
        scheduled_for = pending_trade.scheduled_for

        # Verificar se estamos dentro da janela de fechamento (DEPOIS do fechamento, ate 2.0 segundos)
        # Só executa se já passou do fechamento da vela
        time_diff = current_time - scheduled_for
        if time_diff < 0:
            logger.warning(
                f"⏰ Trade agendado ainda não chegou no fechamento da vela: {pending_trade.symbol} {pending_trade.timeframe}s "
                f"(faltam {abs(time_diff):.3f}s)"
            )
            return None
        if time_diff > 2.0:
            logger.warning(
                f"⏰ Trade agendado expirou: {pending_trade.symbol} {pending_trade.timeframe}s "
                f"(diferença: {time_diff:.3f}s)"
            )
            return None
        
        logger.info(
            f"🎯 Executando trade no fechamento da vela: {pending_trade.symbol} "
            f"{pending_trade.timeframe}s @ {datetime.fromtimestamp(scheduled_for).strftime('%H:%M:%S.%f')[:-3]} "
            f"(latência: {time_diff*1000:.0f}ms)"
        )
        
        # Validar sinal no fechamento da vela
        if not await validate_signal_at_candle_close(
            pending_trade.signal,
            pending_trade.symbol,
            pending_trade.timeframe,
            realtime_collector
        ):
            logger.info(
                f"❌ Sinal inválido no fechamento da vela: {pending_trade.symbol} {pending_trade.timeframe}s"
            )
            return None
        
        # Executar trade imediatamente (bypassando verificação de trade_timing)
        # Precisamos executar a lógica de execução normal, mas sem agendar novamente
        signal = pending_trade.signal
        autotrade_config = pending_trade.autotrade_config
        
        # Executar trade usando o TradeExecutor
        # Precisamos chamar o método que executa o trade, mas sem verificar trade_timing novamente
        # Vamos criar um método auxiliar no TradeExecutor para isso
        
        # Por enquanto, vamos executar o trade diretamente
        trade = await execute_pending_trade(
            trade_executor,
            signal,
            pending_trade.symbol,
            pending_trade.timeframe,
            autotrade_config
        )
        
        if trade:
            logger.success(
                f"✅ Trade executado com sucesso no fechamento da vela: "
                f"{pending_trade.symbol} {pending_trade.timeframe}s"
            )
        else:
            logger.warning(
                f"⚠️ Trade não executado no fechamento da vela: "
                f"{pending_trade.symbol} {pending_trade.timeframe}s"
            )
        
        return trade
        
    except Exception as e:
        logger.error(f"Erro ao executar trade no fechamento da vela: {e}", exc_info=True)
        return None


async def validate_signal_at_candle_close(
    signal: Dict[str, Any],
    symbol: str,
    timeframe: int,
    realtime_collector,
    validate_direction: bool = False  # ← Validação de direção é OPCIONAL
) -> bool:
    """
    Validar se o sinal ainda é válido no fechamento da vela.
    
    Args:
        signal: Sinal original
        symbol: Símbolo do asset
        timeframe: Timeframe em segundos
        realtime_collector: Instância do RealtimeDataCollector
        validate_direction: Se True, valida direção do preço (padrão: False)

    Returns:
        True se o sinal ainda é válido, False caso contrário
        
    Nota:
        - Por padrão, não valida direção do preço para permitir estratégias de reversão
        - Validação de direção pode ser ativada se necessário via validate_direction=True
    """
    try:
        # Obter candles atuais
        buffers = realtime_collector._candle_buffers.get(symbol, {})
        buffer = buffers.get(timeframe, [])

        if len(buffer) < 2:
            logger.warning(f"Buffer insuficiente para validar sinal: {len(buffer)} < 2")
            return False

        # Validação de direção é OPCIONAL (desabilitada por padrão)
        if validate_direction:
            # Obter candle atual e anterior
            current_candle = buffer[-1]
            previous_candle = buffer[-2]

            # Verificar a direção do sinal
            signal_type = signal.signal_type

            # Validar direção do sinal baseado no fechamento da vela
            current_close = current_candle.get('close', 0)
            previous_close = previous_candle.get('close', 0)

            # Para BUY: preço deve estar subindo
            if signal_type == 'BUY':
                if current_close <= previous_close:
                    logger.debug(f"Sinal BUY inválido: preço não subiu ({current_close} <= {previous_close})")
                    return False

            # Para SELL: preço deve estar caindo
            elif signal_type == 'SELL':
                if current_close >= previous_close:
                    logger.debug(f"Sinal SELL inválido: preço não caiu ({current_close} >= {previous_close})")
                    return False

        logger.debug(
            f"Sinal {signal.signal_type} válido no fechamento da vela: "
            f"{symbol} {timeframe}s (validação de direção: {'ativa' if validate_direction else 'desativada'})"
        )

        return True

    except Exception as e:
        logger.error(f"Erro ao validar sinal no fechamento da vela: {e}", exc_info=True)
        return False


async def execute_pending_trade(
    trade_executor,
    signal: Dict[str, Any],
    symbol: str,
    timeframe: int,
    autotrade_config: Dict[str, Any]
) -> Optional[Any]:
    """
    Executar trade pendente sem verificar trade_timing.
    
    Args:
        trade_executor: Instância do TradeExecutor
        signal: Sinal
        symbol: Símbolo do asset
        timeframe: Timeframe em segundos
        autotrade_config: Configuração de autotrade
        
    Returns:
        Trade executado ou None se falhar
    """
    try:
        # Obter conexão para a conta
        connection, account = await trade_executor._get_connection_for_account_id(
            autotrade_config['account_id']
        )
        
        if not connection:
            logger.warning(f"⚠️ Nenhuma conexão ativa para conta {autotrade_config['account_id']}")
            return None
        
        # 🚨 VERIFICAÇÃO CRÍTICA: Verificar se há trades ativos antes de executar
        # Isso previne múltiplos trades simultâneos quando execute_all_signals está desativado
        execute_all_signals = autotrade_config.get('execute_all_signals', False)
        if not execute_all_signals:
            has_no_active = await trade_executor._check_no_active_trades(
                account_id=autotrade_config['account_id'],
                symbol=symbol,
                execute_all_signals=False
            )
            if not has_no_active:
                logger.warning(
                    f"🔒 [CandleClose] Trade bloqueado - já existe trade ativo no ativo {symbol} "
                    f"(account_id={autotrade_config['account_id'][:8]})"
                )
                return None
        else:
            logger.info(f"🚀 [CandleClose] EXECUTAR TODOS SINAIS ativo - ignorando bloqueio de trades simultâneos")
        
        # USAR LOCK do trade_executor para evitar trades simultâneos no mesmo ativo
        # Isso garante sincronização com o fluxo principal de execução
        asset_lock_key = f"{autotrade_config['account_id']}:{symbol}"
        
        # Criar lock se não existir (thread-safe)
        if hasattr(trade_executor, '_asset_locks_creation_lock') and hasattr(trade_executor, '_asset_locks'):
            async with trade_executor._asset_locks_creation_lock:
                if asset_lock_key not in trade_executor._asset_locks:
                    import asyncio
                    trade_executor._asset_locks[asset_lock_key] = asyncio.Lock()
            
            async with trade_executor._asset_locks[asset_lock_key]:
                # Verificar NOVAMENTE dentro do lock (double-check pattern)
                # Outro trade pode ter sido criado enquanto aguardávamos o lock
                if not execute_all_signals:
                    has_no_active = await trade_executor._check_no_active_trades(
                        account_id=autotrade_config['account_id'],
                        symbol=symbol,
                        execute_all_signals=False
                    )
                    if not has_no_active:
                        logger.warning(f"🔒 [CandleClose] Trade bloqueado (double-check) - já existe trade ativo no ativo {symbol}")
                        return None
                
                # Calcular valor do trade
                amount = autotrade_config['amount']
                
                # Executar trade
                trade = await trade_executor._place_order(
                    connection=connection,
                    symbol=symbol,
                    signal=signal,
                    amount=amount,
                    duration=timeframe,
                    strategy_id=autotrade_config['strategy_id']
                )
                
                if trade:
                    logger.success(f"✅ [CandleClose] Trade executado: {symbol}")
                
                return trade
        else:
            # Fallback se trade_executor não tiver locks (não deveria acontecer)
            logger.warning(f"⚠️ [CandleClose] TradeExecutor sem locks, executando sem proteção")
            amount = autotrade_config['amount']
            trade = await trade_executor._place_order(
                connection=connection,
                symbol=symbol,
                signal=signal,
                amount=amount,
                duration=timeframe,
                strategy_id=autotrade_config['strategy_id']
            )
            return trade
        
    except Exception as e:
        logger.error(f"Erro ao executar trade pendente: {e}", exc_info=True)
        return None
