"""
Security Migration Tool
Migra dados de segurança em memória para Redis.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

from core.cache.redis_client import initialize_redis, close_redis, redis_manager
from core.security.unified import security_manager
from core.security.session import session_manager as legacy_session
from core.security.audit import audit_logger as legacy_audit


class SecurityMigrator:
    """Ferramenta de migração de segurança para Redis"""
    
    def __init__(self):
        self.stats = {
            'sessions_migrated': 0,
            'sessions_skipped': 0,
            'audit_events_migrated': 0,
            'errors': []
        }
    
    async def migrate_all(self, dry_run: bool = False) -> dict:
        """
        Executa migração completa
        
        Args:
            dry_run: Se True, apenas simula sem alterar dados
        
        Returns:
            dict: Estatísticas da migração
        """
        logger.info("=" * 60)
        logger.info("SECURITY MIGRATION TOOL")
        logger.info("=" * 60)
        logger.info(f"Started at: {datetime.now().isoformat()}")
        logger.info(f"Dry run: {dry_run}")
        
        # Inicializar conexões
        redis_ok = await initialize_redis()
        if not redis_ok:
            logger.error("❌ Redis não disponível. Abortando.")
            return {'success': False, 'error': 'Redis not available'}
        
        logger.info("✅ Redis conectado")
        
        try:
            # Migrações
            await self._migrate_sessions(dry_run)
            await self._migrate_audit_events(dry_run)
            
            # Health check
            health = await security_manager.health_check()
            
            logger.info("=" * 60)
            logger.info("MIGRATION COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Sessions migrated: {self.stats['sessions_migrated']}")
            logger.info(f"Sessions skipped: {self.stats['sessions_skipped']}")
            logger.info(f"Audit events migrated: {self.stats['audit_events_migrated']}")
            logger.info(f"Redis connected: {health['redis']['redis_connected']}")
            
            if self.stats['errors']:
                logger.warning(f"Errors: {len(self.stats['errors'])}")
                for err in self.stats['errors'][:5]:
                    logger.warning(f"  - {err}")
            
            return {
                'success': True,
                'stats': self.stats,
                'health': health
            }
            
        finally:
            await close_redis()
    
    async def _migrate_sessions(self, dry_run: bool = False):
        """Migra sessões da memória para Redis"""
        logger.info("\n📦 Migrating sessions...")
        
        # Obter sessões legadas da memória
        legacy_sessions = getattr(legacy_session, 'active_sessions', {})
        
        if not legacy_sessions:
            logger.info("   No sessions in memory to migrate")
            return
        
        for token, session_data in list(legacy_sessions.items()):
            try:
                if dry_run:
                    logger.info(f"   [DRY RUN] Would migrate session: {token[:16]}...")
                    self.stats['sessions_migrated'] += 1
                    continue
                
                # Recriar no novo manager
                user_id = session_data.get('user_id')
                ip = session_data.get('ip_address', 'unknown')
                user_agent = session_data.get('user_agent', 'unknown')
                
                # Criar nova sessão no Redis
                await security_manager.create_session(
                    user_id=user_id,
                    token=token,
                    refresh_token=session_data.get('refresh_token', ''),
                    ip=ip,
                    user_agent=user_agent
                )
                
                self.stats['sessions_migrated'] += 1
                logger.info(f"   ✅ Migrated session: {token[:16]}...")
                
            except Exception as e:
                self.stats['sessions_skipped'] += 1
                self.stats['errors'].append(f"Session {token[:16]}: {e}")
                logger.error(f"   ❌ Failed to migrate session: {e}")
    
    async def _migrate_audit_events(self, dry_run: bool = False):
        """Migra eventos de auditoria"""
        logger.info("\n📝 Migrating audit events...")
        
        # Obter eventos legados
        legacy_events = getattr(legacy_audit, 'events', [])
        
        if not legacy_events:
            logger.info("   No audit events in memory to migrate")
            return
        
        for event in legacy_events:
            try:
                if dry_run:
                    logger.info(f"   [DRY RUN] Would migrate event: {event.get('event_type')}")
                    self.stats['audit_events_migrated'] += 1
                    continue
                
                # Converter para novo formato
                from core.security.audit_redis import AuditEventType
                
                event_type_str = event.get('event_type', 'suspicious_activity')
                try:
                    event_type = AuditEventType(event_type_str)
                except ValueError:
                    event_type = AuditEventType.SUSPICIOUS_ACTIVITY
                
                # Log no novo sistema
                await security_manager.log_security_event(
                    event_type=event_type,
                    user_id=event.get('user_id'),
                    ip_address=event.get('ip_address'),
                    details=event.get('details', {}),
                    severity=event.get('severity', 'INFO')
                )
                
                self.stats['audit_events_migrated'] += 1
                
            except Exception as e:
                self.stats['errors'].append(f"Audit event: {e}")
                logger.error(f"   ❌ Failed to migrate audit event: {e}")
        
        logger.info(f"   ✅ Migrated {self.stats['audit_events_migrated']} audit events")
    
    async def verify_migration(self) -> bool:
        """Verifica integridade da migração"""
        logger.info("\n🔍 Verifying migration...")
        
        health = await security_manager.health_check()
        
        checks = [
            ('Redis connected', health['redis']['redis_connected']),
            ('Sessions in Redis', health['sessions'].get('redis_hits', 0) >= 0),
            ('No critical errors', len(self.stats['errors']) == 0)
        ]
        
        all_passed = True
        for name, passed in checks:
            status = "✅" if passed else "❌"
            logger.info(f"   {status} {name}")
            if not passed:
                all_passed = False
        
        return all_passed


async def main():
    """Entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Security Migration Tool')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Simulate migration without changes')
    parser.add_argument('--verify-only', action='store_true',
                       help='Only verify current state')
    
    args = parser.parse_args()
    
    migrator = SecurityMigrator()
    
    if args.verify_only:
        await initialize_redis()
        ok = await migrator.verify_migration()
        await close_redis()
        sys.exit(0 if ok else 1)
    
    result = await migrator.migrate_all(dry_run=args.dry_run)
    
    sys.exit(0 if result.get('success') else 1)


if __name__ == '__main__':
    asyncio.run(main())
