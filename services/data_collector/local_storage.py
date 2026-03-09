"""
Serviço de armazenamento local de dados de mercado
"""

import json
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger
from collections import defaultdict
import aiofiles
import time


class LocalStorageService:
    """Serviço para salvar dados de mercado em arquivos locais"""

    def __init__(self, base_path: str = "data/actives", max_file_size_mb: int = 50):
        self.base_path = Path(base_path)
        self._running = False
        # Locks para evitar race condition por arquivo
        self._file_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Limite máximo de tamanho por arquivo em bytes (50MB default)
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024
        # Buffers de batch para cada ativo
        self._tick_batches: Dict[str, List[Dict]] = defaultdict(list)
        # Timestamps da última flush para cada ativo
        self._last_flush_time: Dict[str, float] = {}
        # Intervalo de flush em segundos (1 segundo)
        self._flush_interval = 1.0
        # Tamanho máximo do batch antes de flush (100 ticks)
        self._max_batch_size = 100
        # Task de flush periódico
        self._flush_task: Optional[asyncio.Task] = None
        # Contador de escritas para verificação de truncagem
        self._write_counters: Dict[str, int] = {}
        # Último tamanho verificado por arquivo (evitar stat excessivo)
        self._last_file_sizes: Dict[str, int] = {}

    async def start(self, clear_on_start: bool = True):
        """Iniciar serviço de armazenamento local
        
        Args:
            clear_on_start: Se True, limpa a pasta de ativos ao iniciar (apenas no startup do sistema)
        """
        self._running = True
        
        # Limpar pasta ao iniciar APENAS se clear_on_start=True (startup do sistema)
        if clear_on_start:
            await self._clear_actives_folder()
        
        # Criar pasta se não existir
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Iniciar task de flush periódico
        self._flush_task = asyncio.create_task(self._periodic_flush())
        
        logger.info(f"[OK] Local Storage iniciado em {self.base_path} (clear_on_start={clear_on_start}, max_file_size={self._max_file_size_bytes / (1024*1024):.0f}MB por arquivo, batch_size={self._max_batch_size})")

    async def stop(self):
        """Parar serviço"""
        self._running = False
        
        # Cancelar task de flush
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await asyncio.wait_for(self._flush_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        
        # Flush final de todos os batches pendentes
        await self._flush_all_batches()
        
        logger.info("[OK] Local Storage parado")

    async def _periodic_flush(self):
        """Flush periódico dos batches pendentes"""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                
                if not self._running:
                    break
                    
                # Flush todos os batches que precisam ser salvos
                await self._flush_all_batches()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LocalStorage] Erro no flush periódico: {e}")
                await asyncio.sleep(0.1)

    async def _flush_all_batches(self):
        """Flush todos os batches pendentes"""
        current_time = time.time()
        tasks = []
        
        for asset_symbol, batch in list(self._tick_batches.items()):
            if batch:
                # Verificar se é hora de flush ou batch está cheio
                last_flush = self._last_flush_time.get(asset_symbol, 0)
                time_since_flush = current_time - last_flush
                
                if time_since_flush >= self._flush_interval or len(batch) >= self._max_batch_size:
                    tasks.append(self._flush_batch(asset_symbol, batch.copy()))
                    self._tick_batches[asset_symbol] = []
                    self._last_flush_time[asset_symbol] = current_time
        
        # Executar todos os flushes em paralelo
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _flush_batch(self, asset_symbol: str, batch: List[Dict]):
        """Flush um batch específico para o arquivo"""
        if not batch:
            return
            
        lock = self._file_locks[asset_symbol]
        
        async with lock:
            try:
                file_path = self.base_path / f"{asset_symbol}.txt"
                
                # Preparar todas as linhas
                lines = [json.dumps(tick, separators=(',', ':')) for tick in batch]
                content = "\n".join(lines) + "\n"
                
                # Verificar tamanho do arquivo antes de escrever (usar cache)
                should_truncate = False
                current_size = self._last_file_sizes.get(asset_symbol, 0)
                
                # Atualizar tamanho a cada 50 escritas ou se desconhecido
                write_count = self._write_counters.get(asset_symbol, 0)
                if write_count % 50 == 0 or current_size == 0:
                    if file_path.exists():
                        try:
                            loop = asyncio.get_event_loop()
                            stat = await loop.run_in_executor(None, file_path.stat)
                            current_size = stat.st_size
                            self._last_file_sizes[asset_symbol] = current_size
                        except:
                            current_size = 0
                    else:
                        current_size = 0
                        self._last_file_sizes[asset_symbol] = 0
                
                content_size = len(content.encode('utf-8'))
                new_size = current_size + content_size
                
                # Verificar se precisa truncar ANTES de escrever
                if new_size > self._max_file_size_bytes:
                    should_truncate = True
                
                # Se precisa truncar, fazer antes de escrever
                if should_truncate:
                    await self._truncate_file(asset_symbol, file_path)
                    # Resetar tamanho após truncagem
                    self._last_file_sizes[asset_symbol] = 0
                
                # Escrever o batch
                async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
                    await f.write(content)
                
                # Atualizar tamanho cacheado
                self._last_file_sizes[asset_symbol] = new_size if not should_truncate else content_size
                self._write_counters[asset_symbol] = write_count + len(batch)
                
            except Exception as e:
                logger.error(f"[LocalStorage] Erro ao flush batch para {asset_symbol}: {e}")

    async def _truncate_file(self, asset_symbol: str, file_path: Path):
        """Truncar arquivo mantendo apenas últimos 70% dos dados"""
        try:
            if not file_path.exists():
                return
                
            logger.info(f"[TRUNCATE] [{asset_symbol}] Truncando arquivo (limite: {self._max_file_size_bytes / (1024*1024):.0f}MB)...")
            
            # Ler todas as linhas
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                all_lines = await f.readlines()
            
            if not all_lines:
                return
                
            # Manter apenas últimos 70% das linhas
            total_lines = len(all_lines)
            keep_from = int(total_lines * 0.3)
            lines_to_keep = all_lines[keep_from:]
            
            # Reescrever arquivo
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.writelines(lines_to_keep)
            
            # Atualizar cache de tamanho
            new_size = sum(len(line.encode('utf-8')) for line in lines_to_keep)
            self._last_file_sizes[asset_symbol] = new_size
            
            logger.info(f"[TRUNCATE] [{asset_symbol}] {total_lines} -> {len(lines_to_keep)} linhas ({new_size / (1024*1024):.2f}MB)")
            
        except Exception as e:
            logger.warning(f"[TRUNCATE] Erro ao truncar {asset_symbol}: {e}")

    async def save_tick(self, asset_symbol: str, price: float, timestamp: float):
        """Salvar tick no batch (não escreve imediatamente no disco)"""
        if not self._running:
            return
            
        tick_data = {
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp).isoformat(),
            "price": price
        }
        
        # Adicionar ao batch
        self._tick_batches[asset_symbol].append(tick_data)
        
        # Se batch atingir tamanho máximo, fazer flush imediato
        if len(self._tick_batches[asset_symbol]) >= self._max_batch_size:
            batch = self._tick_batches[asset_symbol].copy()
            self._tick_batches[asset_symbol] = []
            self._last_flush_time[asset_symbol] = time.time()
            # Não await - deixar rodar em background
            asyncio.create_task(self._flush_batch(asset_symbol, batch))

    async def save_history(self, asset_symbol: str, period: int, candles: List[List[float]]):
        """Salvar histórico de candles como ticks"""
        tick_data_list = []
        for candle in candles:
            tick_data_list.append({
                "timestamp": candle[0],
                "datetime": datetime.fromtimestamp(candle[0]).isoformat(),
                "price": candle[1]
            })
        
        # Adicionar ao batch
        self._tick_batches[asset_symbol].extend(tick_data_list)

    async def _clear_actives_folder(self):
        """Limpar pasta actives ao iniciar"""
        if self.base_path.exists():
            try:
                loop = asyncio.get_event_loop()
                
                files = await loop.run_in_executor(None, lambda: list(self.base_path.glob("*.txt")))
                for file_path in files:
                    try:
                        await loop.run_in_executor(None, file_path.unlink)
                    except:
                        pass
                
                logger.info(f"[OK] Pasta {self.base_path} limpa")
            except Exception as e:
                logger.warning(f"Aviso: Não foi possível limpar pasta {self.base_path}: {e}")
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.base_path.mkdir(exist_ok=True))
        except Exception as e:
            logger.warning(f"Aviso ao criar pasta: {e}")

    async def _load_ticks_optimized(self, asset_symbol: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Carregar ticks do arquivo de forma otimizada (linha por linha)"""
        file_path = self.base_path / f"{asset_symbol}.txt"
        
        if not file_path.exists():
            return []
        
        try:
            ticks = []
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        try:
                            tick = json.loads(line)
                            ticks.append(tick)
                        except json.JSONDecodeError:
                            continue
            
            # Retornar apenas os últimos N ticks se limit especificado
            if limit and len(ticks) > limit:
                return ticks[-limit:]
            return ticks
                
        except Exception as e:
            logger.error(f"Erro ao carregar ticks para {asset_symbol}: {e}")
            return []

    def get_asset_path(self, asset_symbol: str) -> Path:
        """Obter caminho do ativo"""
        return self.base_path / asset_symbol

    def list_assets(self) -> List[str]:
        """Listar todos os ativos com dados"""
        if not self.base_path.exists():
            return []
        
        return [f.stem for f in self.base_path.glob("*.txt") if f.is_file()]

    async def load_candles_from_file(self, asset_symbol: str, timeframe: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Carregar candles do arquivo local e converter para formato OHLC (otimizado)"""
        ticks = await self._load_ticks_optimized(asset_symbol, limit=limit * 10)
        
        if not ticks:
            return []
        
        return self._convert_ticks_to_ohlc(ticks, timeframe, limit)
    
    def _convert_ticks_to_ohlc(self, ticks: List[Dict], timeframe: int, limit: int) -> List[Dict[str, Any]]:
        """Converter ticks em candles OHLC para um timeframe específico"""
        if not ticks:
            return []
        
        # Ordenar ticks por timestamp
        sorted_ticks = sorted(ticks, key=lambda x: x["timestamp"])
        
        # Agrupar ticks por timeframe
        candles_dict = {}
        
        for tick in sorted_ticks:
            timestamp = tick["timestamp"]
            price = tick["price"]
            
            # Calcular o início do candle baseado no timeframe
            candle_start = (timestamp // timeframe) * timeframe
            
            if candle_start not in candles_dict:
                candles_dict[candle_start] = {
                    "timestamp": candle_start,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1
                }
            else:
                candle = candles_dict[candle_start]
                candle["high"] = max(candle["high"], price)
                candle["low"] = min(candle["low"], price)
                candle["close"] = price
                candle["volume"] += 1
        
        # Converter para lista e ordenar
        candles = list(candles_dict.values())
        candles = sorted(candles, key=lambda x: x["timestamp"])
        
        # Retornar apenas os últimos N candles
        return candles[-limit:] if len(candles) > limit else candles
    
    async def get_candles(
        self,
        symbol: str,
        timeframe: int,
        limit: int = 100,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Obter candles para um símbolo e timeframe específicos"""
        candles = await self.load_candles_from_file(symbol, timeframe, limit)
        
        # Filtrar por intervalo de tempo se especificado
        if start_time is not None:
            candles = [c for c in candles if c["timestamp"] >= start_time]
        if end_time is not None:
            candles = [c for c in candles if c["timestamp"] <= end_time]
        
        return candles
    
    async def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obter o tick mais recente para um símbolo (otimizado - lê apenas última linha)"""
        file_path = self.base_path / f"{symbol}.txt"
        
        if not file_path.exists():
            return None
        
        try:
            # Ler apenas a última linha do arquivo (MUITO mais rápido!)
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                await f.seek(0, 2)  # SEEK_END
                file_size = await f.tell()
                
                if file_size == 0:
                    return None
                
                # Ler últimos 1KB para encontrar última linha
                read_size = min(1024, file_size)
                await f.seek(file_size - read_size)
                last_chunk = await f.read()
                
                lines = last_chunk.strip().split('\n')
                if lines:
                    last_line = lines[-1]
                    try:
                        tick = json.loads(last_line)
                        return {
                            "price": tick["price"],
                            "timestamp": tick["timestamp"]
                        }
                    except json.JSONDecodeError:
                        return None
                
                return None
                
        except Exception as e:
            logger.error(f"Erro ao carregar tick mais recente para {symbol}: {e}")
            return None
    
    async def get_available_assets(self) -> List[str]:
        """Obter lista de ativos com dados disponíveis"""
        if not self.base_path.exists():
            return []
        
        assets = []
        for file_path in self.base_path.glob("*.txt"):
            assets.append(file_path.stem)
        
        return assets

    async def delete_asset_file(self, asset_symbol: str) -> bool:
        """Apagar arquivo de dados de um ativo específico"""
        file_path = self.base_path / f"{asset_symbol}.txt"
        
        if not file_path.exists():
            return False
        
        lock = self._file_locks[asset_symbol]
        
        async with lock:
            # Tentar deletar com retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    file_path.unlink()
                    # Limpar cache
                    self._last_file_sizes.pop(asset_symbol, None)
                    self._write_counters.pop(asset_symbol, None)
                    logger.info(f"[OK] Arquivo apagado: {file_path}")
                    return True
                except PermissionError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.1 * (attempt + 1))
                    else:
                        logger.error(f"Erro ao apagar arquivo de {asset_symbol}: {e}")
                        return False
                except Exception as e:
                    logger.error(f"Erro ao apagar arquivo de {asset_symbol}: {e}")
                    return False
        
        return False


# Instância global
local_storage = LocalStorageService()
