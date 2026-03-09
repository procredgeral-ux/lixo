"""
System State Manager - Controle global do estado do backend
Permite ligar/desligar módulos de coleta, análise e execução de trades
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Set, Dict, Any
from datetime import datetime
from loguru import logger
import asyncio


class SystemModule(Enum):
    """Módulos do sistema que podem ser controlados"""
    DATA_COLLECTION = "data_collection"  # Coleta de dados de ativos
    ANALYSIS = "analysis"                # Análise de sinais/indicadores
    TRADE_EXECUTION = "trade_execution"  # Execução de novos trades
    SIGNAL_GENERATION = "signal_generation"  # Geração de novos sinais
    NOTIFICATIONS = "notifications"      # Notificações Telegram/email


@dataclass
class SystemState:
    """Estado atual do sistema"""
    enabled: bool = True
    disabled_modules: Set[SystemModule] = field(default_factory=set)
    disabled_at: datetime | None = None
    enabled_at: datetime = field(default_factory=datetime.utcnow)
    last_toggle_by: str | None = None
    trades_in_progress: int = 0  # Contador de trades em andamento
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "disabled_modules": [m.value for m in self.disabled_modules],
            "disabled_at": self.disabled_at.isoformat() if self.disabled_at else None,
            "enabled_at": self.enabled_at.isoformat(),
            "last_toggle_by": self.last_toggle_by,
            "trades_in_progress": self.trades_in_progress,
            "status": "running" if self.enabled else "maintenance"
        }


class SystemManager:
    """Gerenciador singleton do estado do sistema"""
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._state = SystemState()
            cls._instance._trade_locks: Dict[str, asyncio.Lock] = {}
        return cls._instance
    
    @property
    def state(self) -> SystemState:
        """Retorna o estado atual do sistema"""
        return self._state
    
    def is_module_enabled(self, module: SystemModule) -> bool:
        """Verifica se um módulo específico está habilitado"""
        if self._state.enabled:
            return True
        return module not in self._state.disabled_modules
    
    def is_data_collection_enabled(self) -> bool:
        """Verifica se coleta de dados está habilitada"""
        return self.is_module_enabled(SystemModule.DATA_COLLECTION)
    
    def is_analysis_enabled(self) -> bool:
        """Verifica se análise está habilitada"""
        return self.is_module_enabled(SystemModule.ANALYSIS)
    
    def is_trade_execution_enabled(self) -> bool:
        """Verifica se execução de novos trades está habilitada"""
        return self.is_module_enabled(SystemModule.TRADE_EXECUTION)
    
    def is_signal_generation_enabled(self) -> bool:
        """Verifica se geração de sinais está habilitada"""
        return self.is_module_enabled(SystemModule.SIGNAL_GENERATION)
    
    def is_notifications_enabled(self) -> bool:
        """Verifica se notificações estão habilitadas"""
        return self.is_module_enabled(SystemModule.NOTIFICATIONS)
    
    def can_execute_new_trade(self) -> bool:
        """
        Verifica se pode executar NOVO trade
        Trades em andamento continuam mesmo com sistema desligado
        """
        return self.is_trade_execution_enabled()
    
    def can_generate_signal(self) -> bool:
        """Verifica se pode gerar novo sinal"""
        return self.is_signal_generation_enabled()
    
    async def toggle_system(
        self, 
        enabled: bool, 
        modules: list[str] | None = None,
        user_id: str | None = None
    ) -> SystemState:
        """
        Alterna o estado do sistema
        
        Args:
            enabled: True para ligar, False para desligar
            modules: Lista de módulos afetados (None = todos)
            user_id: ID do usuário que fez a ação
        """
        async with self._lock:
            if modules:
                # Converter strings para enums
                affected_modules = {
                    SystemModule(m) for m in modules 
                    if m in [mod.value for mod in SystemModule]
                }
            else:
                # Todos os módulos por padrão
                affected_modules = set(SystemModule)
            
            if enabled:
                # LIGAR: Remove módulos da lista de desabilitados
                self._state.disabled_modules -= affected_modules
                
                # Se não há mais módulos desabilitados, sistema está totalmente ligado
                if not self._state.disabled_modules:
                    self._state.enabled = True
                    self._state.enabled_at = datetime.utcnow()
                    logger.info(f"[SYSTEM] Sistema totalmente ligado por {user_id}")
                else:
                    logger.info(f"[SYSTEM] Módulos reativados: {[m.value for m in affected_modules]}")
            else:
                # DESLIGAR: Adiciona módulos à lista de desabilitados
                self._state.disabled_modules |= affected_modules
                self._state.enabled = False
                self._state.disabled_at = datetime.utcnow()
                logger.warning(
                    f"[SYSTEM] Sistema desligado por {user_id}. "
                    f"Módulos desabilitados: {[m.value for m in affected_modules]}. "
                    f"Trades em andamento: {self._state.trades_in_progress} continuarão"
                )
            
            self._state.last_toggle_by = user_id
            return self._state
    
    def register_trade_start(self, trade_id: str) -> None:
        """Registra início de um trade"""
        self._state.trades_in_progress += 1
        logger.debug(f"[SYSTEM] Trade {trade_id} iniciado. Total em andamento: {self._state.trades_in_progress}")
    
    def register_trade_end(self, trade_id: str) -> None:
        """Registra fim de um trade"""
        self._state.trades_in_progress = max(0, self._state.trades_in_progress - 1)
        logger.debug(f"[SYSTEM] Trade {trade_id} finalizado. Total em andamento: {self._state.trades_in_progress}")
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status completo do sistema"""
        return {
            **self._state.to_dict(),
            "modules": {
                "data_collection": self.is_data_collection_enabled(),
                "analysis": self.is_analysis_enabled(),
                "trade_execution": self.is_trade_execution_enabled(),
                "signal_generation": self.is_signal_generation_enabled(),
                "notifications": self.is_notifications_enabled()
            },
            "can_execute_new_trades": self.can_execute_new_trade(),
            "can_generate_signals": self.can_generate_signal()
        }


class LoggerManager:
    """Gerenciador de níveis de log"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._log_levels = {
                "DEBUG": True,
                "INFO": True,
                "WARNING": True,
                "ERROR": True,
                "SUCCESS": True
            }
        return cls._instance
    
    def set_log_level_enabled(self, level: str, enabled: bool) -> bool:
        """Ativa ou desativa um nível de log"""
        if level in self._log_levels:
            self._log_levels[level] = enabled
            return True
        return False
    
    def get_log_levels(self) -> Dict[str, bool]:
        """Retorna o estado atual dos níveis de log"""
        return self._log_levels.copy()
    
    def is_level_enabled(self, level: str) -> bool:
        """Verifica se um nível de log está habilitado"""
        return self._log_levels.get(level, True)


# Instância global do gerenciador de logs
logger_manager = LoggerManager()


def get_logger_manager() -> LoggerManager:
    """Retorna instância do gerenciador de logs"""
    return logger_manager


# Instância global do gerenciador
system_manager = SystemManager()


def get_system_manager() -> SystemManager:
    """Retorna instância do gerenciador de sistema"""
    return system_manager
