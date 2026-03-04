"""Data collector service"""
from services.data_collector.connection_manager import UserConnectionManager

# Instância global do gerenciador de conexões (será populada pelo DataCollectorService)
connection_manager: UserConnectionManager = None
