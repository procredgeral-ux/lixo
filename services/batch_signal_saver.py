"""
Batch Signal Saver - Sistema de salvamento em lote de sinais
Reduz carga no banco de dados acumulando sinais e salvando em batch
"""
import asyncio
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
import uuid


@dataclass
class PendingSignal:
    """Sinal pendente para salvamento em batch"""
    id: str
    account_id: str
    symbol: str
    strategy_id: Optional[str]
    timeframe: int
    signal_type: str
    confidence: float
    price: float
    indicators: Optional[List[Dict]] = None
    confluence: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BatchSignalSaver:
    """
    Gerenciador de salvamento em lote de sinais
    
    Estratégia:
    - Acumula sinais em memória
    - Salva em batch a cada X segundos OU quando atinge N sinais
    - Usa INSERT OR REPLACE para atualizar sinais existentes eficientemente
    """
    
    def __init__(
        self,
        flush_interval: float = 5.0,  # Segundos entre flushes
        max_batch_size: int = 100,   # Máximo de sinais antes de flush forçado
        max_retries: int = 3,
        max_buffer_size: int = 500,  # Limite máximo de sinais no buffer
        on_flush_complete: Optional[Callable] = None
    ):
        self.flush_interval = flush_interval
        self.max_batch_size = max_batch_size
        self.max_retries = max_retries
        self.max_buffer_size = max_buffer_size
        self.on_flush_complete = on_flush_complete
        
        # Buffer de sinais pendentes
        self._pending_signals: List[PendingSignal] = []
        self._pending_index: Dict[str, PendingSignal] = {}  # O(1) lookup para deduplicação
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._is_flushing = False  # Flag para evitar race conditions
        
        # Fila de sinais que falharam (dead letter)
        self._dead_letter_signals: List[PendingSignal] = []
        self._max_dead_letter_size = 100
        
        # Estatísticas
        self._stats = {
            'total_saved': 0,
            'total_errors': 0,
            'total_batch_signals': 0,
            'last_flush_time': 0,
            'avg_batch_size': 0,
            'flush_count': 0
        }
    
    async def start(self):
        """Iniciar o processo de flush periódico"""
        self._is_running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(f"[BATCH SAVER] Iniciado | interval={self.flush_interval}s | max_batch={self.max_batch_size}")
    
    async def stop(self):
        """Parar e fazer flush final de todos os sinais pendentes"""
        self._is_running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Flush final
        await self._flush_buffer(force=True)
        logger.info(f"[BATCH SAVER] Parado | total_saved={self._stats['total_saved']}")
    
    async def add_signal(
        self,
        account_id: str,
        symbol: str,
        signal: Any,
        strategy_id: Optional[str],
        timeframe: int,
        metrics: Dict[str, Any],
        signal_id: Optional[str] = None
    ) -> str:
        """
        Adicionar sinal ao buffer para salvamento em lote
        Com deduplicação: atualiza sinal existente se mesmo symbol+timeframe+tipo
        """
        signal_id = signal_id or str(uuid.uuid4())
        
        # Extrair dados do sinal
        signal_type_str = signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
        indicators_data = []
        if hasattr(signal, 'indicators') and signal.indicators:
            indicators_data = signal.indicators
        
        async with self._lock:
            # DEDUPLICAÇÃO O(1): Usar dict de lookup
            dedup_key = f"{account_id}_{symbol}_{timeframe}_{signal_type_str.lower()}"
            
            if dedup_key in self._pending_index:
                existing = self._pending_index[dedup_key]
                # Atualizar sinal existente com maior confiança e dados mais recentes
                existing.confidence = max(existing.confidence, signal.confidence or 0.0)
                existing.price = signal.price or existing.price
                existing.confluence = max(existing.confluence or 0, metrics.get('confluence', 0))
                existing.indicators = indicators_data or existing.indicators
                existing.created_at = datetime.now()  # Atualizar timestamp
                
                # Log silenciado
                # logger.debug(
                #     f"[BATCH SAVER] Sinal atualizado no buffer: {symbol} ({signal_type_str}) | "
                #     f"conf={existing.confidence:.2f} (era {signal.confidence:.2f})"
                # )
                return existing.id
            
            # Criar novo sinal (não existe duplicata)
            pending = PendingSignal(
                id=signal_id,
                account_id=account_id,
                symbol=symbol,
                strategy_id=strategy_id,
                timeframe=timeframe,
                signal_type=signal_type_str.lower(),
                confidence=signal.confidence or 0.0,
                price=signal.price or 0.0,
                indicators=indicators_data,
                confluence=metrics.get('confluence', 0),
                metadata={
                    'source': 'indicators',
                    'is_executed': False
                }
            )
            
            # Adicionar ao buffer e ao índice O(1)
            self._pending_signals.append(pending)
            self._pending_index[dedup_key] = pending
            current_size = len(self._pending_signals)
        
        # Se atingiu o tamanho máximo, forçar flush (apenas se estiver rodando)
        if current_size >= self.max_batch_size and self._is_running and not self._is_flushing:
            logger.info(f"[BATCH SAVER] Batch cheio ({current_size}), forçando flush...")
            asyncio.create_task(self._flush_buffer())
        
        # Registrar métrica no performance monitor
        try:
            from services.performance_monitor import performance_monitor
            performance_monitor.record_batch(queued=len(self._pending_signals))
        except Exception:
            pass
        
        return signal_id
    
    async def _periodic_flush(self):
        """Task periódica para flush do buffer"""
        while self._is_running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BATCH SAVER] Erro no flush periódico: {e}")
    
    async def _flush_buffer(self, force: bool = False):
        """Salvar todos os sinais pendentes em batch"""
        # Verificar se já está em flush (evitar race condition)
        if self._is_flushing and not force:
            logger.debug("[BATCH SAVER] Flush já em andamento, ignorando...")
            return
        
        self._is_flushing = True
        
        try:
            async with self._lock:
                if not self._pending_signals and not force:
                    return
                
                signals_to_save = self._pending_signals.copy()
                self._pending_signals.clear()
            
            if not signals_to_save:
                return
            
            start_time = time.time()
            success = await self._save_batch(signals_to_save)
            duration = time.time() - start_time
            
            if success:
                self._stats['total_saved'] += len(signals_to_save)
                self._stats['flush_count'] += 1
                self._stats['last_flush_time'] = time.time()
                # Cálculo mais limpo da média
                self._stats['total_batch_signals'] = self._stats.get('total_batch_signals', 0) + len(signals_to_save)
                
                # Registrar métricas no performance monitor com tempo
                try:
                    from services.performance_monitor import performance_monitor
                    performance_monitor.record_batch(
                        saved=len(signals_to_save),
                        time_ms=duration * 1000  # Converter para ms
                    )
                except Exception:
                    pass
                
                logger.info(
                    f"[BATCH SAVER] Flush OK | {len(signals_to_save)} sinais | "
                    f"{duration*1000:.0f}ms | total_saved={self._stats['total_saved']}"
                )
                
                # WRITE-THROUGH CACHE: Popula Redis após salvar no DB
                await self._cache_saved_signals(signals_to_save)
                
                if self.on_flush_complete:
                    try:
                        self.on_flush_complete(len(signals_to_save), duration)
                    except Exception:
                        pass
            else:
                self._stats['total_errors'] += 1
                
                # Registrar erro no performance monitor
                try:
                    from services.performance_monitor import performance_monitor
                    performance_monitor.record_batch(errors=1)
                except Exception:
                    pass
                
                # Devolver sinais ao buffer preservando ordem (sinais antigos primeiro)
                async with self._lock:
                    # Verificar se buffer não está muito cheio
                    if len(self._pending_signals) + len(signals_to_save) > self.max_buffer_size:
                        # Mover sinais excedentes para dead letter
                        overflow_count = (len(self._pending_signals) + len(signals_to_save)) - self.max_buffer_size
                        overflow_signals = signals_to_save[:overflow_count]
                        signals_to_requeue = signals_to_save[overflow_count:]
                        
                        # Adicionar ao dead letter (limitado)
                        self._dead_letter_signals.extend(overflow_signals)
                        if len(self._dead_letter_signals) > self._max_dead_letter_size:
                            self._dead_letter_signals = self._dead_letter_signals[-self._max_dead_letter_size:]
                        
                        logger.error(
                            f"[BATCH SAVER] Buffer overflow! {overflow_count} sinais movidos para dead letter. "
                            f"Total dead letter: {len(self._dead_letter_signals)}"
                        )
                    else:
                        signals_to_requeue = signals_to_save
                    
                    # Preservar ordem cronológica: sinais que falharam primeiro
                    self._pending_signals = signals_to_requeue + self._pending_signals
                    
                    # Reconstruir índice O(1) após reordenar
                    self._pending_index.clear()
                    for s in self._pending_signals:
                        dedup_key = f"{s.account_id}_{s.symbol}_{s.timeframe}_{s.signal_type}"
                        self._pending_index[dedup_key] = s
                    
        finally:
            self._is_flushing = False
    
    async def _cache_saved_signals(self, signals: List[PendingSignal]):
        """Write-through cache: popula Redis após salvar no DB com granularidade account+symbol"""
        try:
            from services.redis_client import redis_client
            from collections import defaultdict
            
            # Usar defaultdict para agrupar sem depender de ordenação
            groups = defaultdict(list)
            for s in signals:
                groups[(s.account_id, s.symbol)].append(s)
            
            # Cachear por account_id + symbol
            for (account_id, symbol), group_signals in groups.items():
                cache_key = f"signals:{account_id}:{symbol}:latest"
                
                # Converter para dict para serialização JSON
                signals_data = [
                    {
                        'id': s.id,
                        'symbol': s.symbol,
                        'timeframe': s.timeframe,
                        'signal_type': s.signal_type,
                        'confidence': s.confidence,
                        'price': s.price,
                        'created_at': s.created_at.isoformat(),
                        'confluence': s.confluence,
                        'indicators': s.indicators
                    }
                    for s in group_signals
                ]
                
                await redis_client.set_json(cache_key, signals_data[-50:], ttl=30)
                logger.debug(f"[BATCH SAVER] Cache write-through: {len(group_signals)} sinais para {account_id[:8]}:{symbol}")
                
        except Exception as e:
            logger.warning(f"[BATCH SAVER] Falha ao cachear sinais: {e}")
    
    async def _save_batch(self, signals: List[PendingSignal]) -> bool:
        """Salvar lote de sinais no banco de dados usando bulk insert"""
        from core.database import get_db_context
        from sqlalchemy import select
        from models import Signal, Asset, SignalType
        
        for attempt in range(self.max_retries):
            try:
                async with get_db_context() as db:
                    # 1. Buscar todos os assets necessários em uma única query
                    symbols = list(set(s.symbol for s in signals))
                    result = await db.execute(
                        select(Asset.id, Asset.symbol).where(Asset.symbol.in_(symbols))
                    )
                    asset_map = {row[1]: row[0] for row in result.all()}
                    
                    # 2. Preparar sinais para inserção
                    signals_to_insert = []
                    for signal in signals:
                        asset_id = asset_map.get(signal.symbol)
                        if not asset_id:
                            logger.warning(f"[BATCH SAVER] Asset {signal.symbol} não encontrado")
                            continue
                        
                        new_signal = Signal(
                            id=signal.id,
                            strategy_id=signal.strategy_id,
                            asset_id=asset_id,
                            timeframe=signal.timeframe,
                            signal_type=SignalType(signal.signal_type),
                            confidence=signal.confidence,
                            price=signal.price,
                            indicators=signal.indicators,
                            confluence=signal.confluence,
                            signal_source='indicators',
                            is_executed=False,
                            created_at=signal.created_at
                        )
                        signals_to_insert.append(new_signal)
                    
                    # 3. Bulk insert (muito mais rápido que inserts individuais)
                    if signals_to_insert:
                        db.add_all(signals_to_insert)
                        await db.commit()
                        
                        # Tracking manual do INSERT para o performance monitor
                        try:
                            from services.performance_monitor import performance_monitor
                            num_inserts = len(signals_to_insert)
                            for _ in range(num_inserts):
                                performance_monitor.record_db_query(time_ms=0, error=False, query_type='insert')
                        except Exception:
                            pass
                    
                    return True
                    
            except Exception as e:
                logger.error(f"[BATCH SAVER] Erro ao salvar batch (tentativa {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                else:
                    return False
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Obter estatísticas do salvamento em lote"""
        flush_count = self._stats.get('flush_count', 0)
        total_batch_signals = self._stats.get('total_batch_signals', 0)
        
        return {
            **self._stats,
            'pending_count': len(self._pending_signals),
            'dead_letter_count': len(self._dead_letter_signals),
            'flush_interval': self.flush_interval,
            'max_batch_size': self.max_batch_size,
            'avg_batch_size': total_batch_signals / max(flush_count, 1),
            'is_flushing': self._is_flushing
        }
    
    async def force_flush(self) -> int:
        """Forçar salvamento imediato (útil para shutdown gracioso)"""
        await self._flush_buffer(force=True)
        return self._stats['total_saved']
