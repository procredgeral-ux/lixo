"""
Daily Signal Summary - Tabela de agregação para relatórios rápidos

Esta tabela armazena agregações pré-computadas de sinais por dia,
permitindo queries de relatório rápidas sem escanear milhares de registros.
"""
from sqlalchemy import Column, String, Integer, Float, Date, Index, func
from sqlalchemy.orm import declarative_base
from zoneinfo import ZoneInfo
from datetime import datetime

# Timezone de Brasília (UTC-3)
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

def get_brasilia_time():
    """Retorna datetime atual no timezone de Brasília"""
    return datetime.now(BRASILIA_TZ)
from typing import Optional

Base = declarative_base()


class DailySignalSummary(Base):
    """
    Resumo diário de sinais para relatórios rápidos
    
    Campos:
    - date: Data da agregação
    - strategy_id: ID da estratégia (ou 'all' para total)
    - asset_id: ID do ativo (ou 'all' para total)
    - timeframe: Timeframe em segundos (ou 0 para todos)
    - total_signals: Total de sinais gerados
    - buy_signals: Sinais de compra
    - sell_signals: Sinais de venda
    - executed_signals: Sinais executados
    - avg_confidence: Confiança média dos sinais
    - avg_confluence: Confluência média
    - updated_at: Última atualização
    """
    
    __tablename__ = "daily_signal_summary"
    
    id = Column(String, primary_key=True)  # Formato: "DATE:STRATEGY:ASSET:TIMEFRAME"
    date = Column(Date, nullable=False, index=True)
    strategy_id = Column(String, nullable=False, default='all')
    asset_id = Column(String, nullable=False, default='all')
    timeframe = Column(Integer, nullable=False, default=0)
    
    # Métricas
    total_signals = Column(Integer, default=0)
    buy_signals = Column(Integer, default=0)
    sell_signals = Column(Integer, default=0)
    hold_signals = Column(Integer, default=0)
    executed_signals = Column(Integer, default=0)
    
    # Estatísticas
    avg_confidence = Column(Float, default=0.0)
    avg_confluence = Column(Float, default=0.0)
    min_confidence = Column(Float, default=0.0)
    max_confidence = Column(Float, default=0.0)
    
    # Timestamp
    updated_at = Column(Date, nullable=False, default=get_brasilia_time)
    
    # Índices compostos para queries comuns
    __table_args__ = (
        Index('idx_daily_summary_date_strategy', 'date', 'strategy_id'),
        Index('idx_daily_summary_date_asset', 'date', 'asset_id'),
        Index('idx_daily_summary_updated', 'updated_at'),
    )
    
    @classmethod
    def generate_id(cls, date: date, strategy_id: str = 'all', 
                    asset_id: str = 'all', timeframe: int = 0) -> str:
        """Gerar ID único para o resumo"""
        return f"{date.isoformat()}:{strategy_id}:{asset_id}:{timeframe}"


# Modelo para histórico de execução do job (SQLite não tem materialized views)
class AggregationJobLog(Base):
    """Log de execução do job de agregação"""
    
    __tablename__ = "aggregation_job_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String, nullable=False)
    started_at = Column(Date, nullable=False)
    completed_at = Column(Date, nullable=True, default=get_brasilia_time)
    records_processed = Column(Integer, default=0)
    status = Column(String, nullable=False)  # 'running', 'completed', 'failed'
    error_message = Column(String, nullable=True)
