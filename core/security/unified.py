"""
Unified Security Interface
Conecta os componentes de segurança antigos com a nova arquitetura Redis.
Mantém compatibilidade backward enquanto migra para persistência.
"""

import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from loguru import logger

from core.cache.redis_client import (
    redis_manager, 
    initialize_redis, 
    close_redis,
    KeyGenerator
)
from core.security.session_redis import (
    HybridSessionManager,
    session_manager as _session_manager_redis,
    create_session as _create_session_redis,
    get_session as _get_session_redis,
    revoke_session as _revoke_session_redis,
    revoke_all_sessions as _revoke_all_sessions_redis,
    blacklist_token as _blacklist_token_redis,
    is_token_blacklisted as _is_token_blacklisted_redis,
    get_active_sessions as _get_active_sessions_redis
)
from core.security.token_blacklist import (
    HybridTokenBlacklist,
    token_blacklist as _token_blacklist,
    blacklist_token as _add_to_blacklist,
    is_token_blacklisted as _check_blacklist,
    remove_from_blacklist as _remove_from_blacklist,
    cleanup_expired_tokens as _cleanup_tokens,
    get_blacklisted_tokens as _get_blacklisted
)
from core.security.audit_redis import (
    HybridAuditLogger,
    audit_logger as _audit_logger,
    log_event as _log_event,
    get_events as _get_events,
    get_security_events as _get_security_events,
    AuditEventType
)

# Importar managers legados para compatibilidade
from core.security.session import session_manager as _legacy_session_manager
from core.security.audit import audit_logger as _legacy_audit_logger


class UnifiedSecurityManager:
    """
    Gerenciador unificado de segurança
    
    Provê interface única para:
    - Sessões (Redis + Memória)
    - Token Blacklist (Redis + Memória)
    - Auditoria (Redis Streams + SQLite + Memória)
    
    Features:
    - Auto-inicialização do Redis
    - Fallback automático entre storages
    - Métricas e health checks
    - Compatibilidade com código legado
    """
    
    def __init__(self):
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # Componentes
        self.sessions = _session_manager_redis
        self.token_blacklist = _token_blacklist
        self.audit = _audit_logger
        
        # Métricas
        self._health_metrics = {
            'redis_connected': False,
            'sessions_in_memory': 0,
            'tokens_blacklisted': 0,
            'audit_buffer_size': 0
        }
    
    async def initialize(self) -> bool:
        """Inicializa sistema de segurança (idempotente)"""
        
        if self._initialized:
            return True
        
        async with self._init_lock:
            if self._initialized:
                return True
            
            try:
                # Inicializar Redis
                redis_ok = await initialize_redis()
                self._health_metrics['redis_connected'] = redis_ok
                
                if redis_ok:
                    logger.info("[SECURITY] Sistema inicializado com Redis")
                else:
                    logger.warning("[SECURITY] Sistema inicializado em modo fallback (sem Redis)")
                
                self._initialized = True
                return True
                
            except Exception as e:
                logger.error(f"[SECURITY] Erro na inicialização: {e}")
                return False
    
    async def shutdown(self):
        """Finaliza sistema de segurança"""
        
        if not self._initialized:
            return
        
        try:
            # Flush audit buffer
            flushed = await self.audit.flush_buffer()
            if flushed > 0:
                logger.info(f"[SECURITY] {flushed} eventos de audit flushados")
            
            # Fechar Redis
            await close_redis()
            
            self._initialized = False
            logger.info("[SECURITY] Sistema finalizado")
            
        except Exception as e:
            logger.error(f"[SECURITY] Erro no shutdown: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Retorna status de saúde do sistema de segurança"""
        
        # Atualizar métricas
        self._health_metrics.update({
            'redis_connected': redis_manager.is_connected,
            'sessions_in_memory': len(self.sessions._memory_sessions),
            'tokens_blacklisted': len(self.token_blacklist._memory_blacklist),
            'audit_buffer_size': len(self.audit._memory_buffer)
        })
        
        # Adicionar estatísticas dos componentes
        stats = {
            'initialized': self._initialized,
            'redis': self._health_metrics,
            'sessions': self.sessions.get_statistics(),
            'token_blacklist': self.token_blacklist.get_statistics(),
            'audit': await self.audit.get_statistics()
        }
        
        return stats
    
    @asynccontextmanager
    async def context(self):
        """Context manager para inicialização automática"""
        await self.initialize()
        try:
            yield self
        finally:
            pass  # Não desligar no contexto, deixar para o app lifecycle
    
    # === Métodos de conveniência ===
    
    async def create_session(self, user_id: str, token: str, refresh_token: str, 
                           ip: str, user_agent: str) -> Dict:
        """Cria sessão"""
        await self.initialize()
        return await _create_session_redis(user_id, token, refresh_token, ip, user_agent)
    
    async def get_session(self, token: str) -> Optional[Dict]:
        """Recupera sessão"""
        await self.initialize()
        return await _get_session_redis(token)
    
    async def revoke_session(self, token: str) -> bool:
        """Revoga sessão e adiciona à blacklist"""
        await self.initialize()
        
        # Revogar sessão
        revoked = await _revoke_session_redis(token)
        
        # Adicionar à blacklist
        if revoked:
            await _add_to_blacklist(token, "session_revoked")
        
        return revoked
    
    async def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoga todas as sessões de um usuário"""
        await self.initialize()
        
        # Obter sessões ativas
        sessions = await _get_active_sessions_redis(user_id)
        
        # Revogar cada uma
        count = 0
        for session in sessions:
            # Aqui precisaríamos do token original, mas temos apenas o hash
            # Em produção, armazenar token criptografado no Redis
            pass
        
        # Usar método direto
        count = await _revoke_all_sessions_redis(user_id)
        
        # Log de auditoria
        if count > 0:
            await _log_event(
                AuditEventType.ACCOUNT_LOCKED if count > 0 else AuditEventType.SETTINGS_CHANGED,
                user_id=user_id,
                details={'sessions_revoked': count, 'reason': 'security_action'}
            )
        
        return count
    
    async def blacklist_token(self, token: str, reason: str = "logout") -> bool:
        """Adiciona token à blacklist"""
        await self.initialize()
        return await _add_to_blacklist(token, reason)
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """Verifica se token está na blacklist"""
        await self.initialize()
        return await _check_blacklist(token)
    
    async def log_security_event(self, event_type: AuditEventType, 
                                user_id: Optional[str] = None,
                                ip_address: Optional[str] = None,
                                details: Optional[Dict] = None,
                                severity: str = "INFO"):
        """Registra evento de segurança"""
        await self.initialize()
        return await _log_event(event_type, user_id, ip_address, None, details, severity)
    
    async def get_recent_security_events(self, hours: int = 24) -> list:
        """Retorna eventos de segurança recentes"""
        await self.initialize()
        events = await _get_security_events(hours)
        return [e.to_dict() for e in events]
    
    async def cleanup_expired_data(self) -> Dict[str, int]:
        """Limpa dados expirados de todos os componentes"""
        await self.initialize()
        
        results = {
            'sessions_cleaned': await self.sessions.cleanup_expired_sessions(),
            'tokens_cleaned': await _cleanup_tokens(),
            'audit_flushed': await self.audit.flush_buffer()
        }
        
        logger.info(f"[SECURITY] Cleanup: {results}")
        return results


# Instância global
security_manager = UnifiedSecurityManager()


# === Funções de conveniência para importação direta ===

async def initialize_security() -> bool:
    """Inicializa sistema de segurança"""
    return await security_manager.initialize()


async def shutdown_security():
    """Finaliza sistema de segurança"""
    await security_manager.shutdown()


async def get_security_health() -> Dict[str, Any]:
    """Retorna health check do sistema"""
    return await security_manager.health_check()


# Sessões
async def create_user_session(user_id: str, token: str, refresh_token: str,
                              ip: str, user_agent: str) -> Dict:
    return await security_manager.create_session(user_id, token, refresh_token, ip, user_agent)


async def get_user_session(token: str) -> Optional[Dict]:
    return await security_manager.get_session(token)


async def revoke_user_session(token: str) -> bool:
    return await security_manager.revoke_session(token)


async def revoke_user_all_sessions(user_id: str) -> int:
    return await security_manager.revoke_all_user_sessions(user_id)


# Blacklist
async def add_token_to_blacklist(token: str, reason: str = "logout") -> bool:
    return await security_manager.blacklist_token(token, reason)


async def check_token_blacklist(token: str) -> bool:
    return await security_manager.is_token_blacklisted(token)


# Auditoria
async def log_security_event(event_type: AuditEventType, 
                            user_id: Optional[str] = None,
                            ip_address: Optional[str] = None,
                            details: Optional[Dict] = None,
                            severity: str = "INFO"):
    return await security_manager.log_security_event(
        event_type, user_id, ip_address, details, severity
    )


async def get_security_audit_events(hours: int = 24) -> list:
    return await security_manager.get_recent_security_events(hours)


# Maintenance
async def run_security_cleanup() -> Dict[str, int]:
    return await security_manager.cleanup_expired_data()


__all__ = [
    # Classes
    'UnifiedSecurityManager',
    'security_manager',
    
    # Inicialização
    'initialize_security',
    'shutdown_security',
    'get_security_health',
    
    # Sessões
    'create_user_session',
    'get_user_session',
    'revoke_user_session',
    'revoke_user_all_sessions',
    
    # Blacklist
    'add_token_to_blacklist',
    'check_token_blacklist',
    
    # Auditoria
    'log_security_event',
    'get_security_audit_events',
    
    # Manutenção
    'run_security_cleanup',
    
    # Types
    'AuditEventType'
]
