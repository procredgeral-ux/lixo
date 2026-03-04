"""
Audit Logger com Redis Streams
Persiste logs de auditoria em Redis Streams com fallback para SQLite.
"""

import time
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict

from loguru import logger

from core.cache.redis_client import redis_manager, KeyGenerator
from core.database import get_db
from sqlalchemy import text


class AuditEventType(str, Enum):
    """Tipos de eventos de auditoria"""
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET = "password_reset"
    ACCOUNT_CREATED = "account_created"
    ACCOUNT_DELETED = "account_deleted"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    TWO_FA_ENABLED = "2fa_enabled"
    TWO_FA_DISABLED = "2fa_disabled"
    TRADE_EXECUTED = "trade_executed"
    TRADE_FAILED = "trade_failed"
    STRATEGY_CREATED = "strategy_created"
    STRATEGY_UPDATED = "strategy_updated"
    STRATEGY_DELETED = "strategy_deleted"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    DATA_EXPORTED = "data_exported"
    DATA_IMPORTED = "data_imported"
    SETTINGS_CHANGED = "settings_changed"
    API_KEY_CREATED = "api_key_created"
    API_KEY_DELETED = "api_key_deleted"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


@dataclass
class AuditEvent:
    """Evento de auditoria"""
    id: str
    event_type: str
    user_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    details: Dict
    severity: str
    timestamp: str
    unix_timestamp: float
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AuditEvent':
        # Garantir que todos os campos existam
        return cls(
            id=data.get('id', ''),
            event_type=data.get('event_type', ''),
            user_id=data.get('user_id'),
            ip_address=data.get('ip_address'),
            user_agent=data.get('user_agent'),
            details=data.get('details', {}),
            severity=data.get('severity', 'INFO'),
            timestamp=data.get('timestamp', ''),
            unix_timestamp=data.get('unix_timestamp', 0.0)
        )


class HybridAuditLogger:
    """
    Logger de auditoria híbrido (Redis Streams + SQLite + Memória)
    
    Arquitetura:
    1. Redis Streams: Primary storage, alta performance, retenção configurável
    2. SQLite: Persistência permanente para compliance (async via worker)
    3. Memória: Buffer temporário durante falhas de conectividade
    """
    
    def __init__(self):
        # Buffer em memória para fallback
        self._memory_buffer: List[AuditEvent] = []
        self._buffer_max_size = 1000
        
        # Configurações
        self._stream_maxlen = 10000  # Retenção no Redis
        self._sync_interval = 300  # Sincronizar para SQLite a cada 5 min
        self._last_sync = time.time()
        
        # Métricas
        self._redis_writes = 0
        self._memory_writes = 0
        self._db_writes = 0
        self._failed_writes = 0
    
    async def log_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[dict] = None,
        severity: str = "INFO"
    ) -> AuditEvent:
        """
        Registra evento de auditoria
        
        Args:
            event_type: Tipo do evento (enum)
            user_id: ID do usuário
            ip_address: IP do cliente
            user_agent: User agent
            details: Detalhes adicionais
            severity: INFO, WARNING, ERROR, CRITICAL
        
        Returns:
            AuditEvent: Evento registrado
        """
        now = time.time()
        event_id = f"{int(now * 1000)}-{user_id or 'system'}"
        
        event = AuditEvent(
            id=event_id,
            event_type=event_type.value if isinstance(event_type, AuditEventType) else event_type,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
            severity=severity,
            timestamp=datetime.utcnow().isoformat(),
            unix_timestamp=now
        )
        
        # Tentar Redis primeiro
        if redis_manager.is_connected:
            try:
                stream_key = KeyGenerator.audit_stream()
                
                # Adicionar ao stream
                fields = {
                    'event_id': event.id,
                    'event_type': event.event_type,
                    'user_id': event.user_id or '',
                    'ip': event.ip_address or '',
                    'user_agent': event.user_agent or '',
                    'details': json.dumps(event.details, default=str),
                    'severity': event.severity,
                    'timestamp': event.timestamp,
                    'unix_ts': str(event.unix_timestamp)
                }
                
                msg_id = await redis_manager.xadd(
                    stream_key, 
                    fields,
                    maxlen=self._stream_maxlen
                )
                
                if msg_id:
                    self._redis_writes += 1
                    logger.debug(f"[AUDIT] Evento registrado no Redis: {event.event_type}")
                    
                    # Verificar se precisa sincronizar com SQLite
                    if now - self._last_sync > self._sync_interval:
                        await self._sync_to_database()
                    
                    return event
                    
            except Exception as e:
                logger.warning(f"[AUDIT] Falha no Redis: {e}")
        
        # Fallback para memória
        self._memory_buffer.append(event)
        self._memory_writes += 1
        
        # Limitar tamanho do buffer
        if len(self._memory_buffer) > self._buffer_max_size:
            self._memory_buffer = self._memory_buffer[-self._buffer_max_size:]
        
        logger.warning(f"[AUDIT] Evento bufferizado em memória: {event.event_type}")
        
        # Tentar salvar no banco diretamente
        try:
            await self._save_to_database(event)
        except Exception as e:
            self._failed_writes += 1
            logger.error(f"[AUDIT] Falha ao salvar no banco: {e}")
        
        return event
    
    async def get_events(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
        hours: Optional[int] = None
    ) -> List[AuditEvent]:
        """Recupera eventos de auditoria"""
        
        events = []
        cutoff_time = time.time() - (hours * 3600) if hours else 0
        
        # Buscar no Redis primeiro
        if redis_manager.is_connected:
            try:
                stream_key = KeyGenerator.audit_stream()
                entries = await redis_manager.xrevrange(stream_key, count=limit * 2)
                
                for entry in entries:
                    event = self._parse_stream_entry(entry)
                    
                    if event and event.unix_timestamp >= cutoff_time:
                        # Aplicar filtros
                        if user_id and event.user_id != user_id:
                            continue
                        if event_type and event.event_type != event_type:
                            continue
                        if severity and event.severity != severity:
                            continue
                        
                        events.append(event)
                        
            except Exception as e:
                logger.warning(f"[AUDIT] Erro ao buscar no Redis: {e}")
        
        # Complementar com memória (eventos recentes que podem não estar no Redis)
        for event in reversed(self._memory_buffer):
            if event.unix_timestamp >= cutoff_time:
                if user_id and event.user_id != user_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                if severity and event.severity != severity:
                    continue
                
                # Evitar duplicatas
                if not any(e.id == event.id for e in events):
                    events.append(event)
        
        # Ordenar por timestamp (mais recentes primeiro) e limitar
        events.sort(key=lambda x: x.unix_timestamp, reverse=True)
        return events[:limit]
    
    async def get_security_events(
        self, 
        hours: int = 24,
        limit: int = 100
    ) -> List[AuditEvent]:
        """Retorna eventos relacionados à segurança"""
        
        security_types = [
            AuditEventType.LOGIN_FAILED.value,
            AuditEventType.ACCOUNT_LOCKED.value,
            AuditEventType.SUSPICIOUS_ACTIVITY.value,
            AuditEventType.PASSWORD_CHANGE.value,
            AuditEventType.TWO_FA_DISABLED.value
        ]
        
        events = await self.get_events(hours=hours, limit=limit * 2)
        return [e for e in events if e.event_type in security_types][:limit]
    
    async def get_recent_events(
        self,
        hours: int = 24,
        severity: Optional[str] = None
    ) -> List[AuditEvent]:
        """Retorna eventos recentes"""
        return await self.get_events(hours=hours, severity=severity, limit=1000)
    
    async def export_events(
        self,
        format: str = "json",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10000
    ) -> str:
        """Exporta eventos para JSON ou CSV"""
        
        # Buscar eventos do período
        events = await self.get_events(limit=limit)
        
        # Filtrar por data se especificado
        if start_date or end_date:
            filtered = []
            for event in events:
                event_date = datetime.fromtimestamp(event.unix_timestamp)
                
                if start_date:
                    start = datetime.fromisoformat(start_date)
                    if event_date < start:
                        continue
                
                if end_date:
                    end = datetime.fromisoformat(end_date)
                    if event_date > end:
                        continue
                
                filtered.append(event)
            events = filtered
        
        if format == "json":
            return json.dumps([e.to_dict() for e in events], indent=2, default=str)
        
        elif format == "csv":
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow([
                'id', 'event_type', 'user_id', 'timestamp', 'severity',
                'ip_address', 'details'
            ])
            
            for event in events:
                writer.writerow([
                    event.id,
                    event.event_type,
                    event.user_id or '',
                    event.timestamp,
                    event.severity,
                    event.ip_address or '',
                    json.dumps(event.details, default=str)
                ])
            
            return output.getvalue()
        
        return ""
    
    async def get_statistics(self) -> dict:
        """Retorna estatísticas de auditoria"""
        
        stats = {
            'redis_writes': self._redis_writes,
            'memory_writes': self._memory_writes,
            'db_writes': self._db_writes,
            'failed_writes': self._failed_writes,
            'buffer_size': len(self._memory_buffer),
            'redis_connected': redis_manager.is_connected
        }
        
        # Adicionar estatísticas do stream Redis
        if redis_manager.is_connected:
            try:
                stream_key = KeyGenerator.audit_stream()
                stream_len = await redis_manager.xlen(stream_key)
                stats['redis_stream_length'] = stream_len
            except:
                stats['redis_stream_length'] = 0
        
        return stats
    
    async def flush_buffer(self) -> int:
        """Força sincronização do buffer de memória para persistência"""
        
        if not self._memory_buffer:
            return 0
        
        flushed = 0
        
        # Tentar enviar para Redis primeiro
        if redis_manager.is_connected:
            try:
                stream_key = KeyGenerator.audit_stream()
                
                for event in self._memory_buffer:
                    fields = {
                        'event_id': event.id,
                        'event_type': event.event_type,
                        'user_id': event.user_id or '',
                        'ip': event.ip_address or '',
                        'user_agent': event.user_agent or '',
                        'details': json.dumps(event.details, default=str),
                        'severity': event.severity,
                        'timestamp': event.timestamp,
                        'unix_ts': str(event.unix_timestamp)
                    }
                    
                    await redis_manager.xadd(stream_key, fields, maxlen=self._stream_maxlen)
                    flushed += 1
                
                logger.info(f"[AUDIT] {flushed} eventos do buffer enviados para Redis")
                
            except Exception as e:
                logger.error(f"[AUDIT] Erro ao flush para Redis: {e}")
        
        # Tentar salvar no banco
        for event in self._memory_buffer:
            try:
                await self._save_to_database(event)
                flushed += 1
            except Exception as e:
                logger.error(f"[AUDIT] Erro ao salvar no banco: {e}")
        
        # Limpar buffer
        self._memory_buffer = []
        
        return flushed
    
    # Métodos privados
    
    def _parse_stream_entry(self, entry: dict) -> Optional[AuditEvent]:
        """Converte entrada do stream em AuditEvent"""
        try:
            return AuditEvent(
                id=entry.get('event_id', entry.get('id', '')),
                event_type=entry.get('event_type', ''),
                user_id=entry.get('user_id') or None,
                ip_address=entry.get('ip') or entry.get('ip_address') or None,
                user_agent=entry.get('user_agent') or None,
                details=json.loads(entry.get('details', '{}')),
                severity=entry.get('severity', 'INFO'),
                timestamp=entry.get('timestamp', ''),
                unix_timestamp=float(entry.get('unix_ts', 0))
            )
        except Exception as e:
            logger.warning(f"[AUDIT] Erro ao parsear entrada: {e}")
            return None
    
    async def _save_to_database(self, event: AuditEvent) -> bool:
        """Salva evento no banco SQLite (persistência permanente)"""
        
        try:
            async with get_db() as db:
                query = text("""
                    INSERT INTO audit_logs (
                        event_id, event_type, user_id, ip_address, user_agent,
                        details, severity, timestamp, unix_timestamp
                    ) VALUES (
                        :event_id, :event_type, :user_id, :ip_address, :user_agent,
                        :details, :severity, :timestamp, :unix_timestamp
                    )
                """)
                
                await db.execute(query, {
                    'event_id': event.id,
                    'event_type': event.event_type,
                    'user_id': event.user_id,
                    'ip_address': event.ip_address,
                    'user_agent': event.user_agent,
                    'details': json.dumps(event.details, default=str),
                    'severity': event.severity,
                    'timestamp': event.timestamp,
                    'unix_timestamp': event.unix_timestamp
                })
                
                await db.commit()
                self._db_writes += 1
                return True
                
        except Exception as e:
            logger.error(f"[AUDIT] Erro no banco: {e}")
            return False
    
    async def _sync_to_database(self) -> int:
        """Sincroniza eventos do Redis para o banco (worker periódico)"""
        
        if not redis_manager.is_connected:
            return 0
        
        synced = 0
        
        try:
            # Buscar eventos do stream
            events = await self.get_events(limit=1000, hours=24)
            
            for event in events:
                # Verificar se já existe no banco
                # Simplificação: inserir com UPSERT
                try:
                    await self._save_to_database(event)
                    synced += 1
                except:
                    pass
            
            self._last_sync = time.time()
            
            if synced > 0:
                logger.info(f"[AUDIT] {synced} eventos sincronizados para o banco")
                
        except Exception as e:
            logger.error(f"[AUDIT] Erro na sincronização: {e}")
        
        return synced


# Instância global
audit_logger = HybridAuditLogger()


# Funções de conveniência
async def log_event(
    event_type: AuditEventType,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
    severity: str = "INFO"
) -> AuditEvent:
    """Registra evento de auditoria"""
    return await audit_logger.log_event(
        event_type, user_id, ip_address, user_agent, details, severity
    )


async def get_events(
    user_id: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    hours: Optional[int] = None
) -> List[AuditEvent]:
    """Recupera eventos"""
    return await audit_logger.get_events(
        user_id, event_type, severity, limit, hours
    )


async def get_security_events(hours: int = 24, limit: int = 100) -> List[AuditEvent]:
    """Recupera eventos de segurança"""
    return await audit_logger.get_security_events(hours, limit)


async def get_statistics() -> dict:
    """Retorna estatísticas"""
    return await audit_logger.get_statistics()


__all__ = [
    'HybridAuditLogger',
    'audit_logger',
    'AuditEvent',
    'AuditEventType',
    'log_event',
    'get_events',
    'get_security_events',
    'get_statistics'
]
