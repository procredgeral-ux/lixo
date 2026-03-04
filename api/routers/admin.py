from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from loguru import logger
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pydantic import BaseModel
import psutil
import time

from core.database import get_db, engine
from core.security.unified import get_security_health
from models import User, Account, Strategy, Signal, Trade, Asset
from api.dependencies import get_current_active_user, get_current_superuser
from schemas import UserResponse
from services.unified_metrics import get_unified_metrics

router = APIRouter(tags=["admin"])

# Instância unificada de métricas (mesma lógica do dashboard.log)
metrics = get_unified_metrics()


class UserPlanResponse(BaseModel):
    """Response schema for user plan update"""
    role: str
    vip_start_date: datetime | None
    vip_end_date: datetime | None
    message: str


class PerformanceMetricsResponse(BaseModel):
    """Response schema for system performance metrics"""
    sistema: Dict[str, Any]
    api: Dict[str, Any]
    rede: Dict[str, Any]
    trades: Dict[str, Any]
    database: Dict[str, Any]
    processamento: Dict[str, Any]
    ativos: Dict[str, Any]
    lastUpdate: str


class DatabaseTableInfo(BaseModel):
    """Informações sobre uma tabela do banco de dados"""
    name: str
    count: int
    description: str
    size_bytes: int | None = None
    last_updated: datetime | None = None


class DatabaseTablesResponse(BaseModel):
    """Resposta com lista de tabelas"""
    tables: List[DatabaseTableInfo]
    total_tables: int
    total_records: int


class TableDataResponse(BaseModel):
    """Resposta com dados de uma tabela"""
    table_name: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int


# ... (manter endpoints existentes de users, plan, performance) ...


@router.get("/database/tables", response_model=DatabaseTablesResponse)
async def get_database_tables(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Listar todas as tabelas do banco de dados com contagens"""
    try:
        # Mapeamento de tabelas principais
        tables_info = [
            {"name": "users", "description": "Usuários do sistema", "model": User},
            {"name": "accounts", "description": "Contas de trading", "model": Account},
            {"name": "strategies", "description": "Estratégias de trading", "model": Strategy},
            {"name": "signals", "description": "Sinais gerados", "model": Signal},
            {"name": "trades", "description": "Trades executados", "model": Trade},
            {"name": "assets", "description": "Ativos disponíveis", "model": Asset},
        ]
        
        tables = []
        total_records = 0
        
        for table_info in tables_info:
            try:
                # Contar registros
                count = await db.scalar(select(func.count()).select_from(table_info["model"]))
                
                table_data = DatabaseTableInfo(
                    name=table_info["name"],
                    count=count or 0,
                    description=table_info["description"],
                    size_bytes=None,  # TODO: implementar cálculo de tamanho
                    last_updated=datetime.utcnow()
                )
                tables.append(table_data)
                total_records += count or 0
            except Exception as e:
                logger.warning(f"Erro ao contar tabela {table_info['name']}: {e}")
                # Adicionar com count 0 em caso de erro
                tables.append(DatabaseTableInfo(
                    name=table_info["name"],
                    count=0,
                    description=table_info["description"] + " (erro ao acessar)",
                    size_bytes=None,
                    last_updated=None
                ))
        
        logger.info(f"✓ [ADMIN] Database tables listadas por {current_user.email}")
        
        return DatabaseTablesResponse(
            tables=tables,
            total_tables=len(tables),
            total_records=total_records
        )
        
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro ao listar tabelas: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao listar tabelas: {str(e)}")


@router.get("/database/tables/{table_name}", response_model=TableDataResponse)
async def get_table_data(
    table_name: str,
    page: int = Query(1, ge=1, description="Página de resultados"),
    page_size: int = Query(10, ge=1, le=100, description="Itens por página"),
    filter_text: str = Query(None, description="Texto para filtrar resultados"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Obter dados de uma tabela específica com paginação"""
    try:
        # Mapeamento de tabelas permitidas (evitar SQL injection)
        allowed_tables = {
            "users": {"model": User, "columns": ["id", "email", "name", "role", "is_active", "created_at"]},
            "accounts": {"model": Account, "columns": ["id", "user_id", "name", "balance_demo", "balance_real", "is_active", "created_at"]},
            "strategies": {"model": Strategy, "columns": ["id", "user_id", "account_id", "name", "type", "is_active", "created_at"]},
            "signals": {"model": Signal, "columns": ["id", "strategy_id", "asset_id", "signal_type", "confidence", "created_at"]},
            "trades": {"model": Trade, "columns": ["id", "account_id", "asset_id", "direction", "amount", "status", "placed_at"]},
            "assets": {"model": Asset, "columns": ["id", "symbol", "name", "type", "is_active", "created_at"]},
        }
        
        if table_name not in allowed_tables:
            raise HTTPException(status_code=400, detail=f"Tabela '{table_name}' não permitida ou não existe")
        
        table_config = allowed_tables[table_name]
        model = table_config["model"]
        columns = table_config["columns"]
        
        # Calcular offset
        offset = (page - 1) * page_size
        
        # Query base
        query = select(model)
        
        # Aplicar filtro se fornecido
        if filter_text and hasattr(model, 'name'):
            query = query.where(model.name.ilike(f"%{filter_text}%"))
        elif filter_text and hasattr(model, 'email'):
            query = query.where(model.email.ilike(f"%{filter_text}%"))
        
        # Ordenar por data de criação decrescente
        if hasattr(model, 'created_at'):
            query = query.order_by(model.created_at.desc())
        
        # Paginação
        query = query.offset(offset).limit(page_size)
        
        # Executar query
        result = await db.execute(query)
        rows_db = result.scalars().all()
        
        # Contar total
        total_count = await db.scalar(select(func.count()).select_from(model))
        
        # Converter para dicionários
        rows = []
        for row in rows_db:
            row_dict = {}
            for col in columns:
                value = getattr(row, col, None)
                # Converter datetime para string
                if isinstance(value, datetime):
                    value = value.strftime("%Y-%m-%d %H:%M:%S")
                row_dict[col] = value
            rows.append(row_dict)
        
        logger.info(f"✓ [ADMIN] Dados da tabela {table_name} retornados: {len(rows)} registros (página {page})")
        
        return TableDataResponse(
            table_name=table_name,
            columns=columns,
            rows=rows,
            total_count=total_count or 0,
            page=page,
            page_size=page_size
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro ao obter dados da tabela {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter dados: {str(e)}")


@router.get("/users")
async def list_all_users(
    search: str = Query(None, description="Buscar por nome, email, plano ou telegram username"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Listar todos os usuários (apenas superusuários)"""
    result = await db.execute(select(User))
    users = result.scalars().all()
    
    # Filtrar se houver termo de busca
    if search and search.strip():
        search_lower = search.lower().strip()
        users = [u for u in users if 
            (u.name and search_lower in u.name.lower()) or
            (u.email and search_lower in u.email.lower()) or
            (u.role and search_lower in u.role.lower()) or
            (u.telegram_username and search_lower in u.telegram_username.lower())
        ]
    
    return [
        UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
            telegram_chat_id=user.telegram_chat_id,
            telegram_username=user.telegram_username,
            role=user.role or 'free',
            vip_start_date=user.vip_start_date,
            vip_end_date=user.vip_end_date
        ) for user in users
    ]


@router.get("/users/search")
async def search_user_by_email(
    email: str = Query(..., description="Email do usuário a buscar"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Buscar usuário por email (apenas superusuários)"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
        role=user.role or 'free',
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date
    )


@router.put("/users/{user_id}/plan", response_model=UserPlanResponse)
async def update_user_plan_admin(
    user_id: str,
    role: str = Query(..., description="Plano do usuário: 'free', 'vip', 'vip_plus'"),
    duration_days: int = Query(7, description="Duração em dias para VIP/VIP+"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Atualizar plano do usuário (apenas superusuários)"""
    # Validar role
    valid_roles = ['free', 'vip', 'vip_plus']
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Role inválido. Valores válidos: {', '.join(valid_roles)}"
        )
    
    # Buscar usuário
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    # Calcular datas de VIP
    now = datetime.utcnow()
    vip_start_date = None
    vip_end_date = None
    
    if role in ['vip', 'vip_plus']:
        vip_start_date = now
        vip_end_date = now + timedelta(days=duration_days)
    elif role == 'free':
        # Para plano free, remover datas VIP
        vip_start_date = None
        vip_end_date = None
    
    # Atualizar usuário
    user.role = role
    user.vip_start_date = vip_start_date
    user.vip_end_date = vip_end_date
    user.updated_at = now
    
    await db.commit()
    await db.refresh(user)
    
    logger.info(f"✓ [ADMIN] Plano do usuário {user.email} atualizado para {role.upper()}")
    
    return UserPlanResponse(
        role=user.role,
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date,
        message=f"Plano atualizado para {role.upper()}"
    )


@router.get("/performance", response_model=PerformanceMetricsResponse)
async def get_performance_metrics(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Obter métricas de performance do sistema - usa mesma lógica do dashboard.log"""
    try:
        # Coletar métricas de sistema (mesma lógica do performance_monitor.py)
        system = metrics.get_system_metrics()
        api = metrics.get_api_metrics()
        ws = metrics.get_websocket_metrics()
        database = metrics.get_database_metrics()
        cache = metrics.get_cache_metrics()
        batch = metrics.get_batch_metrics()
        
        # Contagens do banco de dados
        users_count = await db.scalar(select(func.count()).select_from(User))
        accounts_count = await db.scalar(select(func.count()).select_from(Account))
        strategies_count = await db.scalar(select(func.count()).select_from(Strategy))
        signals_count = await db.scalar(select(func.count()).select_from(Signal))
        trades_count = await db.scalar(select(func.count()).select_from(Trade))
        assets_count = await db.scalar(select(func.count()).select_from(Asset))
        
        # Contagens de hoje
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        trades_today = await db.scalar(
            select(func.count()).select_from(Trade).where(Trade.placed_at >= today)
        )
        signals_today = await db.scalar(
            select(func.count()).select_from(Signal).where(Signal.created_at >= today)
        )
        
        # Montar resposta no formato esperado pelo frontend
        performance_data = {
            "sistema": {
                "uptime": system['uptime'],
                "memoriaAtual": f"{system['memory_mb']:.1f} MB",
                "memoriaMedia": f"{system['avg_memory_mb']:.1f} MB (últimos 5min)",
                "cpuAtual": f"{system['cpu_percent']:.1f}%",
                "cpuMedia": f"{system['avg_cpu_percent']:.1f}% (últimos 5min)",
                "threads": system['threads'],
                "discoUso": f"{system['disk_usage_percent']:.1f}%",
                "discoIO": f"↓ {system['disk_read_mb']:.2f} MB ↑ {system['disk_write_mb']:.2f} MB",
                "networkIO": f"↓ {system['network_recv_mb']:.2f} MB ↑ {system['network_sent_mb']:.2f} MB",
                "loadAverage": f"{system['load_avg_1m']:.2f} / {system['load_avg_5m']:.2f} / {system['load_avg_15m']:.2f}",
                "swap": f"{system['swap_used_mb']:.1f} / {system['swap_total_mb']:.1f} MB",
            },
            "api": {
                "totalRequisicoes": api['total_requests'],
                "sucessos": f"{api['successful_requests']} ({api['success_rate']:.1f}%)",
                "falhas": api['failed_requests'],
                "erros4xx": api['http_4xx_errors'],
                "erros5xx": api['http_5xx_errors'],
                "rpsAtual": f"{api['rps_current']:.1f}/s",
                "rpsPico": f"{api['rps_current']:.1f}/s",  # Simplificado
                "latenciaMedia": f"{api['avg_latency_ms']:.1f} ms",
                "latenciaP95": f"{api['latency_p95_ms']:.1f} ms",
                "latenciaP99": f"{api['latency_p99_ms']:.1f} ms",
                "latenciaMaxima": f"{api['max_latency_ms']:.1f} ms",
            },
            "rede": {
                "conexoesUsuarios": ws['user_connections'],
                "conexoesMonitoramento": ws['monitoring_connections'],
                "totalConexoesWS": ws['ws_connections'],
                "contasAtivas": ws['active_accounts'],
                "mensagensWSEnviadas": ws['ws_messages_sent'],
                "mensagensWSRecebidas": ws['ws_messages_recv'],
                "reconexoes": ws['ws_reconnections'],
                "latenciaCorretora": f"{ws['broker_latency_ms']:.1f} ms",
            },
            "trades": {
                "tradesExecutados": trades_today,
                "tradesPendentes": 0,
                "taxaSucessoTrades": "0.0%",
                "sinaisGerados": signals_today,
                "sinaisExecutados": trades_today,
                "sinaisBaixaConf": 0,
            },
            "database": {
                "queriesExecutadas": database['db_queries'],
                "select": database['db_selects'],
                "insert": database['db_inserts'],
                "update": database['db_updates'],
                "delete": database['db_deletes'],
                "errosDB": database['db_errors'],
                "queriesLentas": database['db_slow_queries'],
                "tempoMedioQuery": f"{database['db_avg_time_ms']:.1f} ms",
                "tempoTotalQueries": f"{database['db_total_time_ms']:.1f} ms",
            },
            "processamento": {
                "cacheHits": cache['cache_hits'],
                "cacheMisses": cache['cache_misses'],
                "cacheHitRate": f"{cache['cache_hit_rate']:.1f}%",
                "batchFila": batch['batch_signals_queued'],
                "batchSalvos": batch['batch_signals_saved'],
                "batchErros": batch['batch_save_errors'],
                "batchTempoMedio": "0.0 ms",  # TODO
                "batchThroughput": "0.0 sinais/s",  # TODO
                "batchUltimoSave": batch['batch_last_save_time'],
                "agregacaoUltima": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "agregacaoStatus": "running",
            },
            "ativos": {
                "ativosDisponiveis": assets_count,
                "ativosComDados": strategies_count,
                "ativosDesatualizados": 0,
                "atrasoMaximo": "0 ms",
                "atrasoMedio": "0 ms",
            },
            "lastUpdate": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }
        
        logger.info(f"✓ [ADMIN] Métricas solicitadas por {current_user.email}")
        return performance_data
        
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@router.get("/security/health", response_model=Dict[str, Any])
async def get_security_system_health(
    current_user: User = Depends(get_current_superuser)
):
    """Health check do sistema de segurança (sessões, blacklist, auditoria)"""
    try:
        health = await get_security_health()
        
        # Adicionar status interpretável
        redis_status = "healthy" if health['redis']['redis_connected'] else "degraded"
        overall_status = "healthy" if health['redis']['redis_connected'] else "operational"
        
        response = {
            "status": overall_status,
            "redis_status": redis_status,
            "initialized": health['initialized'],
            "components": {
                "sessions": {
                    "status": "healthy",
                    "redis_hits": health['sessions'].get('redis_hits', 0),
                    "memory_hits": health['sessions'].get('memory_hits', 0),
                    "misses": health['sessions'].get('misses', 0),
                    "memory_sessions": health['sessions'].get('memory_sessions', 0)
                },
                "token_blacklist": {
                    "status": "healthy",
                    "redis_hits": health['token_blacklist'].get('redis_hits', 0),
                    "memory_entries": health['token_blacklist'].get('memory_entries', 0)
                },
                "audit": {
                    "status": "healthy",
                    "redis_writes": health['audit'].get('redis_writes', 0),
                    "db_writes": health['audit'].get('db_writes', 0),
                    "buffer_size": health['audit'].get('buffer_size', 0),
                    "stream_length": health['audit'].get('redis_stream_length', 0)
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"🔒 [SECURITY] Health check solicitado por {current_user.email}")
        return response
        
    except Exception as e:
        logger.error(f"✗ [SECURITY] Erro no health check: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")
