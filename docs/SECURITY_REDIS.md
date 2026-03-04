# Sistema de Segurança Redis - Documentação

## Visão Geral

O sistema de segurança do Tunestrade foi aprimorado para usar **Redis** como backend principal, garantindo:

- ✅ **Persistência de sessões** entre reinícios do servidor
- ✅ **Blacklist de tokens** permanente (tokens revogados não voltam a ser válidos)
- ✅ **Auditoria** escalável via Redis Streams
- ✅ **Fallback automático** para memória quando Redis indisponível
- ✅ **Escalabilidade horizontal** (múltiplas instâncias compartilham estado)

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    API FastAPI                              │
└─────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐   ┌────────────┐  ┌────────────┐
    │  Sessions  │   │  Token     │  │   Audit    │
    │  Manager   │   │  Blacklist │  │   Logger   │
    └─────┬──────┘   └─────┬──────┘  └─────┬──────┘
          │                │               │
          └────────────────┼───────────────┘
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
    ┌────────────┐                 ┌────────────┐
    │   Redis    │                 │   Memory   │
    │  (Primary) │                 │  (Fallback)│
    │            │                 │            │
    │ • Sessions │                 │ • Sessions │
    │ • Blacklist│                 │ • Blacklist│
    │ • Streams  │                 │ • Audit    │
    └────────────┘                 └────────────┘
                                           │
                                           ▼
                                    ┌────────────┐
                                    │  SQLite    │
                                    │(Audit      │
                                    │ persistence│
                                    └────────────┘
```

---

## Configuração

### 1. Ativar Redis

Edite o arquivo `.env`:

```env
# Redis - Security & Session Persistence
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
# REDIS_PASSWORD=your-password-here  # Opcional

# Cache TTL em segundos (default: 5 min)
REDIS_CACHE_TTL=300
```

### 2. Instalar/Verificar Redis

**Docker (recomendado):**
```bash
docker run -d --name redis-tunestrade \
  -p 6379:6379 \
  redis:7-alpine
```

**Verificar conexão:**
```bash
redis-cli ping
# Deve retornar: PONG
```

---

## API de Uso

### Sessões

```python
from core.security.unified import (
    create_user_session,
    get_user_session,
    revoke_user_session,
    revoke_user_all_sessions
)

# Criar sessão
session = await create_user_session(
    user_id="user-123",
    token="jwt-token-here",
    refresh_token="refresh-token-here",
    ip="192.168.1.1",
    user_agent="Mozilla/5.0..."
)

# Verificar sessão
session_data = await get_user_session("jwt-token-here")
if session_data:
    print(f"User: {session_data['user_id']}")
    print(f"IP: {session_data['ip_address']}")

# Revogar sessão (logout)
await revoke_user_session("jwt-token-here")

# Revogar todas as sessões do usuário (ex: mudança de senha)
count = await revoke_user_all_sessions("user-123")
print(f"Revogadas {count} sessões")
```

### Token Blacklist

```python
from core.security.unified import (
    add_token_to_blacklist,
    check_token_blacklist
)

# Adicionar token à blacklist (logout, token comprometido)
await add_token_to_blacklist("jwt-token-here", reason="logout")

# Verificar se token está na blacklist
is_blacklisted = await check_token_blacklist("jwt-token-here")
if is_blacklisted:
    raise HTTPException(status_code=401, detail="Token revoked")
```

### Auditoria

```python
from core.security.unified import (
    log_security_event,
    get_security_audit_events,
    AuditEventType
)

# Registrar evento de segurança
await log_security_event(
    event_type=AuditEventType.LOGIN_FAILED,
    user_id="user-123",
    ip_address="192.168.1.1",
    details={'reason': 'invalid_password', 'attempt': 3},
    severity='WARNING'
)

# Consultar eventos de segurança (últimas 24h)
events = await get_security_audit_events(hours=24)
for event in events:
    print(f"{event['timestamp']} | {event['event_type']} | {event['severity']}")
```

### Health Check

```python
from core.security.unified import get_security_health

# Verificar saúde do sistema
health = await get_security_health()
print(f"Redis conectado: {health['redis']['redis_connected']}")
print(f"Sessões em memória: {health['sessions']['memory_sessions']}")
print(f"Tokens na blacklist: {health['token_blacklist']['memory_entries']}")
```

---

## Endpoints Admin

### Health Check de Segurança

```http
GET /api/v1/admin/security/health
Authorization: Bearer {admin_token}
```

**Response:**
```json
{
  "status": "healthy",
  "redis_status": "healthy",
  "initialized": true,
  "components": {
    "sessions": {
      "status": "healthy",
      "redis_hits": 150,
      "memory_hits": 10,
      "misses": 5,
      "memory_sessions": 3
    },
    "token_blacklist": {
      "status": "healthy",
      "redis_hits": 50,
      "memory_entries": 5
    },
    "audit": {
      "status": "healthy",
      "redis_writes": 1000,
      "db_writes": 500,
      "buffer_size": 0,
      "stream_length": 10000
    }
  },
  "timestamp": "2026-03-04T10:30:00"
}
```

---

## Migração de Dados

Se você tem dados em memória que quer migrar para o Redis:

```bash
# Simulação (dry-run)
python scripts/migrate_security_to_redis.py --dry-run

# Migração real
python scripts/migrate_security_to_redis.py

# Verificar estado após migração
python scripts/migrate_security_to_redis.py --verify-only
```

---

## Monitoramento

### Métricas Redis

O sistema expõe métricas automaticamente:

| Métrica | Descrição |
|---------|-----------|
| `redis_hits` | Operações que usaram Redis |
| `memory_hits` | Operações que usaram memória (fallback) |
| `misses` | Falhas de cache |
| `buffer_size` | Eventos de audit pendentes na memória |

### Logs

O sistema loga automaticamente:

```
🔒 Initializing security system...
✅ Security system initialized with Redis
# ou
⚠️ Security system initialized in fallback mode (Redis unavailable)
```

---

## Troubleshooting

### Redis não conecta

1. Verifique se Redis está rodando:
   ```bash
   docker ps | grep redis
   ```

2. Verifique configurações no `.env`:
   ```bash
   grep REDIS .env
   ```

3. Teste conexão manual:
   ```python
   import asyncio
   from core.cache.redis_client import initialize_redis
   
   async def test():
       ok = await initialize_redis()
       print(f"Conectado: {ok}")
   
   asyncio.run(test())
   ```

### Sistema operando em fallback

Se o Redis estiver indisponível, o sistema:
- Continua operando normalmente com memória local
- Loga avisos: `⚠️ Security system initialized in fallback mode`
- Reconecta automaticamente quando Redis voltar

---

## Comparação: Antes vs Depois

| Aspecto | Memória (Antes) | Redis (Depois) |
|---------|-----------------|----------------|
| Persistência | ❌ Perdido no restart | ✅ Persistente |
| Escalabilidade | ❌ Uma instância | ✅ Múltiplas instâncias |
| Token Revogado | ❌ Volta após restart | ✅ Permanece revogado |
| Audit Logs | ❌ 10k limitados | ✅ Ilimitado (streams) |
| Performance | ✅ Latência zero | ✅ ~1ms (aceitável) |

---

## Checklist de Deploy

- [ ] Redis instalado/configurado
- [ ] `.env` atualizado com `REDIS_ENABLED=true`
- [ ] Aplicação reiniciada
- [ ] Health check retorna `status: healthy`
- [ ] Testar login/logout (sessão persistida)
- [ ] Testar revoke de token (token não volta)

---

## Arquivos do Sistema

```
core/
├── cache/
│   └── redis_client.py          # Cliente Redis centralizado
└── security/
    ├── session_redis.py         # Session manager híbrido
    ├── token_blacklist.py       # Blacklist híbrida
    ├── audit_redis.py           # Auditoria com streams
    └── unified.py               # Interface unificada

scripts/
└── migrate_security_to_redis.py  # Ferramenta de migração
```

---

## Suporte

Para dúvidas ou problemas:
1. Verificar logs: `logs/app.log`
2. Verificar health: `GET /api/v1/admin/security/health`
3. Testar Redis: `redis-cli ping`
